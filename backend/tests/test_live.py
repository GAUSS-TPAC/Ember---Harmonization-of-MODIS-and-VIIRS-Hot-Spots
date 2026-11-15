import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

from ember_pipeline.harmonize import harmonize  # noqa: E402
from ember_pipeline.synth import synthetic_monthly  # noqa: E402
from ember_api.firms import FirmsClient, FirmsUnavailable  # noqa: E402
from ember_api.live import LiveHarmonizer, LiveService, live_config, merge_live  # noqa: E402
from ember_api.main import create_app  # noqa: E402
from ember_api.store import HarmonizedStore  # noqa: E402

HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"


def fake_csv(acq_date: str, n: int, lat=4.05, lon=11.05) -> str:
    rows = [f"{lat},{lon},340.0,0.4,0.4,{acq_date},1300,N20,VIIRS,n,2.0NRT,300.0,5.0,D" for _ in range(n)]
    return HEADER + "\n".join(rows) + "\n"


class FakeFetch:
    """Returns 3 NOAA-20 hotspots per requested day in one cell, and records the URLs."""

    def __init__(self):
        self.urls = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        parts = url.rsplit("/", 2)
        days, start = int(parts[1]), date.fromisoformat(parts[2])
        chunks = [fake_csv((start + pd.Timedelta(days=i)).isoformat(), 3) for i in range(days)]
        return HEADER + "".join(c[len(HEADER):] for c in chunks)


class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        monthly = synthetic_monthly(bbox=(4.0, 11.0, 4.3, 11.3), years=(2010, 2026), seed=5)
        cls.harmonized, cls.factors = harmonize(monthly)
        cls.fetch = FakeFetch()
        client = FirmsClient(map_key="TESTKEY", fetch=cls.fetch)
        cls.service = LiveService(client, LiveHarmonizer(cls.factors), days=45, today=date(2026, 11, 15))
        cls.store = HarmonizedStore(cls.harmonized, factors=cls.factors)

    def test_client_splits_window_into_10_day_requests(self):
        fetch = FakeFetch()
        service = LiveService(FirmsClient(map_key="K", fetch=fetch), LiveHarmonizer(self.factors), days=45, today=date(2026, 11, 15))
        service.recent((4.0, 11.0, 4.3, 11.3))
        self.assertEqual(len(fetch.urls), 9)  # 45 days -> 9 windows of 5 days
        self.assertTrue(fetch.urls[0].endswith("/5/2026-10-02"))
        self.assertIn("/VIIRS_NOAA20_NRT/11.000,4.000,11.300,4.300/", fetch.urls[0])
        service.recent((4.0, 11.0, 4.3, 11.3))
        self.assertEqual(len(fetch.urls), 9)  # second call served from cache

    def test_live_months_are_scaled_and_provisional(self):
        live = self.service.recent((4.0, 11.0, 4.3, 11.3))
        self.assertTrue((live["provisional"]).all())
        self.assertEqual(set(live["source"]), {"VIIRS_NOAA20"})
        k = float(self.factors.set_index(["lat_cell", "lon_cell"]).loc[(4.0, 11.0), "k_VIIRS_NOAA20"])
        nov = live[(live["year"] == 2026) & (live["month"] == 11)].iloc[0]
        self.assertAlmostEqual(nov["n_harm"], 15 * 3 * k, places=1)  # Nov 1-15, 3 hotspots/day

    def test_live_config_moves_reference_end(self):
        cfg = live_config((2026, 10))
        self.assertEqual(cfg.coverage["VIIRS_SNPP"].end, (2026, 9))

    def test_merge_replaces_archive_months(self):
        live = self.service.recent((4.0, 11.0, 4.3, 11.3))
        merged = merge_live(self.harmonized, live, (2026, 10))
        ym = merged["year"].astype(int) * 100 + merged["month"].astype(int)
        self.assertTrue(merged.loc[ym >= 202610, "provisional"].all())
        self.assertFalse(merged.loc[ym < 202610, "provisional"].any())

    def test_api_reports_live_status_and_picks_last_complete_month(self):
        app = create_app(self.store, live=self.service)
        c = TestClient(app)
        r = c.post("/api/analyze", json={"bbox": {"south": 4.0, "west": 11.0, "north": 4.3, "east": 11.3},
                                         "start": "2020-01", "end": "2026-12"})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["live"]["status"], "ok")
        self.assertEqual((data["anomaly"]["year"], data["anomaly"]["month"]), (2026, 10))
        prov = [s for s in data["series"] if s["provisional"]]
        self.assertEqual([(s["year"], s["month"]) for s in prov], [(2026, 10), (2026, 11)])
        self.assertTrue(c.get("/api/health").json()["live"])

    def test_api_without_key_falls_back_to_archive(self):
        service = LiveService(FirmsClient(map_key=None, fetch=self.fetch), LiveHarmonizer(self.factors))
        c = TestClient(create_app(self.store, live=service))
        data = c.post("/api/analyze", json={"bbox": {"south": 4.0, "west": 11.0, "north": 4.3, "east": 11.3},
                                            "start": "2020-01", "end": "2026-12"}).json()
        self.assertEqual(data["live"]["status"], "disabled")

    def test_firms_failure_is_reported_not_fatal(self):
        def boom(url):
            raise FirmsUnavailable("timeout")
        service = LiveService(FirmsClient(map_key="K", fetch=boom), LiveHarmonizer(self.factors), today=date(2026, 11, 15))
        c = TestClient(create_app(self.store, live=service))
        data = c.post("/api/analyze", json={"bbox": {"south": 4.0, "west": 11.0, "north": 4.3, "east": 11.3},
                                            "start": "2020-01", "end": "2026-12"}).json()
        self.assertEqual(data["live"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()


class ModisOnlyLiveTests(unittest.TestCase):
    def test_without_factors_uses_modis_nrt_unscaled(self):
        urls = []

        def fetch(url):
            urls.append(url)
            start = url.rsplit("/", 1)[1]
            return HEADER.replace("bright_ti4", "brightness").replace("bright_ti5", "bright_t31") + \
                f"4.05,11.05,320.0,1.0,1.0,{start},1030,T,MODIS,80,6.1NRT,300.0,9.0,D\n"
        service = LiveService(FirmsClient(map_key="K", fetch=fetch), LiveHarmonizer(None), days=10,
                              today=date(2026, 11, 15))
        live = service.recent((4.0, 11.0, 4.3, 11.3))
        self.assertIn("/MODIS_NRT/", urls[0])
        self.assertEqual(set(live["source"]), {"MODIS_raw"})
        self.assertEqual(live["n_harm"].sum(), 2)  # one detection per 5-day request
