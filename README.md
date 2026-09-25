# ANTARCTIC NAV-X — SIH 2026 Decision-Support Prototype


## Publish without a tunnel

For a public HTTPS deployment, use the included `render.yaml` and follow `PUBLISH_SITE.md`. No local tunnel is required.

ANTARCTIC NAV-X is a real-data, physics-informed + machine-learning Antarctic / Southern Ocean navigation decision-support prototype. It combines official iceberg observations, ocean and sea-ice constraints, atmospheric forcing, optional real AIS positions, browser GPS, trajectory forecasting, CPA/TCA analysis, and ocean-surface-constrained route alternatives.

It is **not** an autonomous ship controller, certified navigation system, ECDIS replacement, or guarantee of navigational safety.

## Architecture

This repository is a single FastAPI application. The frontend is plain HTML/CSS/JavaScript served from `src/api/static/index.html`; it is **not** a React/Vite project and has no separate Node build step.

- Backend/API: FastAPI (`src/api/main.py`)
- Frontend: `src/api/static/index.html`
- Scientific routing: `RealOceanSurface` + `PolarAStarRouter`
- ML: `NAVX-DRIFT-ML-v1.0` residual Random Forest + gated runtime integration (`src/ml/`)
- AI decision layer: structured explainable route recommendation and evidence (`src/ai/`)
- Real/cached scientific data: `data/raw/`, `data/processed/`, `data/metadata/`
- Operational URL: `http://localhost:8000/app/`

## Real data sources

- **USNIC** — official Antarctic iceberg observations and sea-ice extent source files
- **CMEMS / Copernicus Marine** — ocean-current forcing and ocean validity cells
- **NSIDC** — Antarctic sea-ice concentration / coast-ocean support
- **ERA5 / ECMWF** — atmospheric/wind forcing
- **AISStream / AISHub / Datalastic** — optional real AIS positions when configured

NAV-X does not invent vessels, iceberg observations, environmental measurements, route metrics, CPA/TCA, or risk values. When required verified data is unavailable, the UI/API reports an unavailable or insufficient-data state.


## AI / ML layer

This build includes a persistent database and automatic real-data ingestion layer in addition to the physics-informed machine-learning system. SQLite is the zero-setup local fallback; PostgreSQL is recommended for deployment. Large NetCDF/GeoTIFF scientific files remain on disk while observations, provenance, checksums, scheduler state, and ingestion audits are stored in SQL. The included iceberg ML model is trained only from archived official USNIC transitions plus cached CMEMS current and ECMWF/ERA5 wind features. It predicts a residual correction to the physical drift baseline; it does **not** replace the official observation. Runtime activation is gated by held-out validation against the physics-only baseline.

The sidebar now includes **AI Decision Center**, which shows the saved model card, training-sample count, held-out endpoint errors, validation gate, AIS anomaly-model state, route recommendation evidence, quantified trade-offs, and a route-comparison matrix.

Retrain:

```powershell
python -m src.ml.train_all --only iceberg
```

See `AI_ML_SETUP_AND_TRAINING.md` for the AIS collection/training workflow and SIH explanation.

## Map configuration

The operator map now uses **MapLibre GL JS + OpenFreeMap** as the primary keyless basemap, with an automatic **OpenStreetMap raster fallback**. No MapTiler, Mapbox, Google Maps, or other basemap API key is required.

The default primary style is:

```env
OPENFREEMAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
```

You normally do not need to change it. `/api/config/map` exposes only safe provider/status metadata and `/api/map/style` provides the keyless OpenStreetMap fallback style. Scientific overlays and all route geometry continue to come from NAV-X backend data/models, not from the basemap provider.

`MAPPLS_STATIC_KEY` remains an optional legacy compatibility variable and is never exposed through `/api/config/*`; it is not required by the current operator map.

## First-time Windows / VS Code setup

Use your installed Python 3.x (Python 3.12+ recommended for the scientific stack):

```powershell
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python -m src.api.main
```

Open:

```text
http://localhost:8000/app/
```

There is no separate frontend start command; FastAPI serves the frontend and backend together.

## Normal run after setup

```powershell
.\venv\Scripts\Activate.ps1
python -m src.api.main
```

## Public/mobile GPS

For phone or public use, publish the FastAPI service over HTTPS by following `PUBLISH_SITE.md`. Browser geolocation generally requires HTTPS outside `localhost`.

## GPS behavior

- **Use GPS** performs a controlled one-shot `getCurrentPosition()` request.
- **Start Live GPS** enables `watchPosition()` with `enableHighAccuracy: true`.
- **Stop GPS** stops the watch.
- **Follow GPS** controls whether live updates recenter the map.
- Browser-reported accuracy and timestamp are displayed; NAV-X does not claim high accuracy unless the device/browser actually reports it.

GPS positions are validated and cannot silently swap latitude/longitude. A GPS fix outside the configured Antarctic/Southern Ocean operating area may be displayed but is not automatically accepted as a navigable route origin.

## Route planner

The planner supports:

- verified named Antarctic reference locations
- Pick Start / Pick Destination on the map
- one-shot or live browser GPS
- real AIS vessel as route origin where data is available
- explicit coordinate validation
- vessel speed and departure-time validation
- FASTEST / BALANCED / SAFEST AVAILABLE profiles
- CMEMS + NSIDC ocean-surface validation
- time-aware iceberg hazard evaluation
- distance, transit time, arrival UTC and initial bearing
- risk/clearance/CPA/TCA only when the required verified inputs exist
- dynamic backend-derived route comparison graph

If no verified path exists through the available navigation surface, NAV-X returns/displays:

```text
NO VERIFIED ROUTE AVAILABLE
```

There is no straight-line or heuristic navigation fallback presented as an operational route.

## AIS behavior

Set one provider in `.env`, for example:

```env
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=your_private_aisstream_key
```

If no provider is configured or no current positions are received, NAV-X returns zero vessels and reports the provider/coverage state. It does not create simulated ships.

## Database + automatic ingestion

The application creates the SQL schema at startup. With no `DATABASE_URL`, local development uses `data/navx.db`. For a persistent deployment set a PostgreSQL URL such as `postgresql+psycopg://...`. Automatic jobs persist USNIC and AIS observations and track NSIDC/CMEMS/ERA5 scientific-file provenance. See `REAL_DATA_DATABASE_SETUP.md`.

Useful verification commands:

```powershell
python scripts/init_database.py
python scripts/check_setup.py
python scripts/ingest_now.py usnic
```

Useful runtime endpoints:

- `/api/system/health`
- `/api/system/ingestion`
- `/api/data/database/summary`

## Scientific-data refresh credentials

Bundled genuine cached CMEMS, ERA5, NSIDC and USNIC files are included for reproducible offline analysis. Optional refresh credentials are documented in `REAL_DATA_SETUP.md` and `REAL_DATA_DATABASE_SETUP.md`.

## Tests

Run:

```powershell
python -m pytest -q
```

Release baseline for this AI/ML build:

```text
70 passed
```

The additional tests cover secret handling, map configuration modes, GPS UI contracts, input validation, ocean-surface routing rejection, unavailable routes, AIS freshness/integrity, route A/B/C API/render contracts, route-comparison metrics, bundled overlays and scientific-data UI behavior.

## Security

Never commit `.env`. Real credentials are intentionally not included in the ZIP.

Secret/server credentials include:

- `MAPPLS_STATIC_KEY`
- `AISSTREAM_API_KEY`
- `DATALASTIC_API_KEY`
- scientific service credentials/tokens

The current basemap requires no API credential and no basemap secret is returned to the browser.
