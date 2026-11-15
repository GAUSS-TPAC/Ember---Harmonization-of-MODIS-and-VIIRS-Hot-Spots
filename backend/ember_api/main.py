"""FastAPI application: analytics over the harmonized table + static frontend."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import analytics
from .firms import FirmsClient, FirmsUnavailable, recent_hotspots_csv
from .geometry import bbox_of, rings_of
from .live import LiveHarmonizer, LiveService, last_complete_month, merge_live
from .schemas import AnalyzeRequest, BBox, parse_ym
from .store import HarmonizedStore, open_store

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "processed" / "harmonized_monthly.parquet"
FRONTEND = ROOT / "frontend"


def create_app(store: HarmonizedStore | None = None, live: LiveService | None = None) -> FastAPI:
    app = FastAPI(title="Ember API", version="0.1.0",
                  description="Harmonized MODIS + VIIRS burning-activity calendar")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    if store is None:
        path = Path(os.environ.get("EMBER_DATA", DEFAULT_DATA))
        if not path.exists():
            raise FileNotFoundError(f"harmonized table not found at {path}; run scripts/make_demo_data.py "
                                    f"or set EMBER_DATA")
        store = open_store(path)
    app.state.store = store
    if live is None:
        live = LiveService(FirmsClient(), LiveHarmonizer(store.factors))
    app.state.live = live

    @app.get("/api/health")
    def health():
        return {"status": "ok", "rows": int(len(store.df)),
                "live": bool(live and live.enabled), "factors": store.factors is not None}

    @app.get("/api/coverage")
    def coverage():
        c = store.coverage()
        return {"first": f"{c.first[0]}-{c.first[1]:02d}", "last": f"{c.last[0]}-{c.last[1]:02d}",
                "cells": c.cells, "bounds": {"south": c.bounds[0], "west": c.bounds[1],
                                              "north": c.bounds[2], "east": c.bounds[3]},
                "resolution_deg": store.res}

    def _run(req: AnalyzeRequest):
        try:
            area = req.area()
            start, end = parse_ym(req.start), parse_ym(req.end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if start > end:
            raise HTTPException(status_code=422, detail="start must be before end")
        if live is not None and live.enabled:  # never show months that have not happened yet
            today = live.today()
            end = min(end, (today.year, today.month))
            if start > end:
                raise HTTPException(status_code=422, detail="period starts in the future")
        sel = store.select(area, start, end)
        live_info = {"status": "disabled"}
        if req.live and live is not None and live.enabled:
            first = live.first_live_month()
            if end >= first:
                try:
                    recent = live.recent([bbox_of(r) for r in rings_of(area)][0])
                    recent = recent.loc[store.select_mask(recent, area)] if len(recent) else recent
                    sel = merge_live(sel, recent, first)
                    sel = sel.loc[(sel["year"].astype(int) * 100 + sel["month"].astype(int)) <= end[0] * 100 + end[1]]
                    live_info = {"status": "ok", "first_month": f"{first[0]}-{first[1]:02d}",
                                 "window_days": live.days, "hotspot_rows": int(len(recent))}
                except FirmsUnavailable as exc:
                    live_info = {"status": "unavailable", "reason": str(exc)}
        series = analytics.complete_series(analytics.monthly_series(sel), start, end)
        app.state.last_live_info = live_info
        return area, start, end, sel, series

    @app.post("/api/analyze")
    def analyze(req: AnalyzeRequest):
        area, start, end, sel, series = _run(req)
        clim = analytics.climatology(series, req.baseline)
        if req.target:
            ty, tm = parse_ym(req.target)
        else:  # default: the last complete calendar month (provisional NRT months count)
            ty, tm = int(series["year"].iloc[-1]), int(series["month"].iloc[-1])
            if live is not None and live.enabled:
                ty, tm = min((ty, tm), last_complete_month(live.today()))
        return {
            "live": app.state.last_live_info,
            "period_effective": {"start": f"{start[0]}-{start[1]:02d}", "end": f"{end[0]}-{end[1]:02d}"},
            "area": {"cells": int(sel[["lat_cell", "lon_cell"]].drop_duplicates().shape[0]),
                     "bbox": [bbox_of(r) for r in rings_of(area)][0]},
            "period": {"start": req.start, "end": req.end},
            "series": series.to_dict(orient="records"),
            "calendar": analytics.calendar(series),
            "climatology": clim,
            "season": analytics.season(clim),
            "anomaly": analytics.anomaly(series, ty, tm, req.baseline),
            "top_years": analytics.yearly_ranking(series),
            "cells": analytics.cell_summary(sel),
        }

    @app.post("/api/export.csv")
    def export_csv(req: AnalyzeRequest):
        _, _, _, _, series = _run(req)
        buf = io.StringIO()
        series.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=ember_series.csv"})

    @app.get("/api/hotspots/recent.csv")
    def recent_hotspots(south: float, west: float, north: float, east: float, days: int = 7,
                        source: str = "VIIRS_NOAA20_NRT"):
        BBox(south=south, west=west, north=north, east=east)
        try:
            text = recent_hotspots_csv((south, west, north, east), days=days, source=source)
        except FirmsUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return StreamingResponse(iter([text]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=firms_recent.csv"})

    if FRONTEND.exists():
        app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
    return app


def app_factory() -> FastAPI:
    return create_app()


try:  # `uvicorn ember_api.main:app` for the common case
    app = create_app()
except FileNotFoundError:  # tests build their own app with an in-memory store
    app = None
