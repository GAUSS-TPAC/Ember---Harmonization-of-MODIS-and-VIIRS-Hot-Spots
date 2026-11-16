# Ember — Harmonized MODIS + VIIRS Burning Activity Calendar

NASA Space Apps Challenge 2026 · *Harmonization of MODIS and VIIRS Hot Spots*

Ember is a harmonized burning-activity calendar built from 25+ years of NASA FIRMS
active-fire hotspots. It calibrates MODIS (2000–) onto VIIRS (2012–) so sensor
changes no longer bias trends, then serves an interactive web app: draw an area,
explore seasonal patterns and anomalies against the historical median, and export
the results as CSV.

## The problem

Satellites have tracked active fires for more than two decades, but the record is
split across two sensor families that cannot be compared directly:

- **MODIS** (Terra 2000–, Aqua 2002–): 1 km pixels, the long historical series,
  now approaching end of life.
- **VIIRS** (Suomi-NPP 2012–, NOAA-20 2018–, NOAA-21 2024–): 375 m pixels, far
  more sensitive to small fires, the future of the record.

For the same fire, VIIRS typically reports 3 to 5 times more hotspots than MODIS.
Counting raw detections across the full period produces an artificial jump in
2012 that masks real trends. Fire managers are left without a consistent picture
of when and where burning has occurred.

## What Ember does

**1. Harmonization pipeline.** Hotspots from NASA FIRMS are aggregated on a common
0.1° grid at monthly resolution, filtered for confidence and vegetation-fire type,
then MODIS counts are calibrated onto a VIIRS-equivalent scale using the
2012–2025 overlap period (Aqua and Suomi-NPP share the same 13:30 overpass, which
isolates the sensor effect). The transfer function is fitted per cell and
validated on held-out years, with uncertainty bands on the pre-2012 reconstruction.

**2. Web application.** Draw an area of interest or enter coordinates, pick a date
range, and get:

- a burning-activity calendar (year × month heatmap, accessible color ramp)
  from 2000 to today, with the sensor of origin no longer mattering;
- the current month compared with the historical median and percentiles
  (anomaly score);
- fire season onset, peak and length for the selected area;
- a CSV export of the harmonized series and of the raw hotspots in the search.

Historical data are precomputed once; the current month is fetched live from the
FIRMS API and passed through the same harmonization.

## Who it is for

Early-warning and emergency responders, land managers, scientists and firefighters
who need to know which periods of the year carry the most fire activity, which
years were exceptional, and how the current season compares with the past.

## Data

- NASA FIRMS active-fire archives, MODIS Collection 6.1 and VIIRS 375 m
  (Suomi-NPP, NOAA-20, NOAA-21), standard-quality processing, 2000–2025.
- NASA FIRMS near-real-time API for the last two months.

## Stack

Python (Polars, DuckDB) for the pipeline, Kaggle notebooks for the global run,
FastAPI backend over Parquet, React + MapLibre frontend.

## Team

Three students from the National Advanced School of Engineering of Yaoundé
(ENSPY), Cameroon:

- **Alan Tchapda**
- **Aghetseh Ngoh**
<<<<<<< HEAD
- **Arreyntow Enow**

## Repository layout

```
pipeline/ember_pipeline/   stage 1 aggregate.py: raw FIRMS CSV/zip -> monthly 0.1° cell counts
                           stage 2 harmonize.py: transfer factors MODIS -> VIIRS scale, validation
                           synth.py: synthetic data for demos and tests
backend/ember_api/         FastAPI: /api/analyze, /api/export.csv, /api/hotspots/recent.csv, static frontend
frontend/                  no-build web app (Leaflet + Chart.js from CDN)
notebooks/                 Kaggle runners: 01 aggregate the global archive, 02 harmonize + validate
scripts/make_demo_data.py  builds data/processed/*.parquet from synthetic data
docs/DATA_CONTRACT.md      the one table shared by pipeline, notebooks and backend
data/samples/              small FIRMS extracts used by the tests
```

## Run locally

```bash
pip install -r pipeline/requirements.txt -r backend/requirements.txt

# 1. data: synthetic demo now, Kaggle outputs later (copy them to data/processed/)
PYTHONPATH=pipeline python scripts/make_demo_data.py

# 2. API + web app
cd backend && PYTHONPATH=.:../pipeline uvicorn ember_api.main:app --reload
# open http://127.0.0.1:8000  (API docs at /docs)
```

Optional: set `FIRMS_MAP_KEY` to enable the raw-hotspot CSV export of the last days
through the FIRMS near-real-time API. Point `EMBER_DATA` at another
`harmonized_monthly.parquet` to serve a different dataset.

## Tests

```bash
(cd pipeline && python -m unittest discover -s tests)
(cd backend && PYTHONPATH=.:../pipeline python -m unittest discover -s tests)
```

## Deploy

`Dockerfile` bundles API, frontend and the processed data; it runs as is on Cloud Run
(`gcloud run deploy ember --source .`).

## Global run on Kaggle

1. Upload the FIRMS per-country yearly zips as a Kaggle Dataset.
2. Run `notebooks/01_aggregate_kaggle.ipynb` against it (CPU, about 10–20 min).
3. Run `notebooks/02_harmonize_kaggle.ipynb` on the output of 01.
4. Copy `harmonized_monthly.parquet` to `data/processed/` and redeploy.
=======
- **Arreyntow Enow**

## Run locally (Linux)

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/make_mock_data.py
python scripts/check_data.py
streamlit run app/streamlit_app.py
```

The app opens at http://localhost:8501. The default `DATA_MODE` is `mock`, which
uses synthetic demonstration data and displays a warning in the app. To set it
explicitly before launching, run `export DATA_MODE=mock`. Use `DATA_MODE=real`
only after pointing the Parquet paths in `app/config.py` to verified real data.
>>>>>>> a464498aa2174f64e519041f31096fb4e8e0cde3
