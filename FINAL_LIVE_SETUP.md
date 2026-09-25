# ANTARCTIC NAV-X — Final Live Build

This build keeps current and historical iceberg data separate and automatically collects genuine AIS observations for anomaly-model training.

## What is active

- **Current iceberg hazards:** official current USNIC table, polled automatically.
- **Historical iceberg tracks:** BYU/NIC consolidated published archive in the database, refreshed automatically on a slower cadence.
- **AIS:** configured AIS provider is a continuous live stream; positions are persisted to the database every 30 seconds by default.
- **AIS anomaly ML:** Isolation Forest trained only from genuine stored AIS observations. No synthetic vessels or fake anomaly labels are generated.
- **CMEMS, ERA5, NSIDC, NOAA NDBC:** existing automatic ingestion remains intact.

## First run

1. Create/activate your venv.
2. Install dependencies:
   `python -m pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your real credentials. Never expose `.env` in the frontend or Git.
4. Run:
   `python scripts/check_setup.py`
5. Start:
   `python -m src.api.main`
6. Open:
   `http://localhost:8000/app/`

## Historical iceberg data

The **Iceberg Catalog** intentionally shows only the current official USNIC set. The **Iceberg History & Current Tracking** page contains the large database-backed historical catalogue and per-iceberg tracks.

Useful endpoints:

- `/api/data/icebergs` — current USNIC only
- `/api/data/icebergs/history/catalog` — database-wide historical catalogue
- `/api/data/icebergs/A23A/history` — backward-compatible official USNIC fixes only
- `/api/data/icebergs/A23A/history/all` — full stored published history + USNIC fixes

Manual historical refresh, if needed:

`python scripts/ingest_now.py iceberg_history`

The scheduler checks the historical archive every `BYU_HISTORY_REFRESH_DAYS` (default 7). Current USNIC remains independently refreshed every `USNIC_REFRESH_MINUTES` (default 30).

## AIS anomaly ML

Default real-data gate:

- 30 valid genuine AIS samples
- at least 2 distinct vessels
- automatic training check every 15 minutes

The UI shows progress such as `COLLECTING_REAL_AIS_DATA` until the real-data gate is satisfied. Once trained it changes automatically to `ACTIVE_REAL_AIS_MODEL`; FastAPI does not need to be restarted because the runtime model wrapper reloads a newly trained model file.

Manual training check:

`python scripts/train_ais_now.py`

A result of `COLLECTING_REAL_AIS_DATA` is not an error; it means the database has not yet accumulated enough valid genuine AIS observations.

## Important scientific-data rule

Historical iceberg positions are never placed into the current hazard layer. Current route/hazard calculations continue to use current verified USNIC observations. Historical positions are for replay, analysis and model research.
