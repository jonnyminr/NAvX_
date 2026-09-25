# ANTARCTIC NAV-X — Database + Automatic Real-Data Ingestion

This build adds persistent storage and scheduled real-data ingestion while
preserving the existing frontend, routing, physics and ML behavior.

## 1. What is stored where

### SQL database

- official USNIC iceberg observations
- genuine AIS vessel position history
- NOAA NDBC buoy/marine observations
- Sentinel-1 catalogue scene metadata
- scientific dataset provenance/checksums
- provider-fetch audit history
- scheduler state

### Files under `data/`

Large scientific source files remain intact on disk:

- CMEMS NetCDF
- ERA5 NetCDF
- NSIDC GeoTIFF
- other large scientific files

NAV-X intentionally does not expand entire NetCDF/GeoTIFF grids into millions of
SQL rows. The database stores provenance and references to the original files.

## 2. Automatic jobs

Default schedule:

- AIS current-state snapshot -> DB: every 60 seconds, only when an AIS provider is configured
- USNIC current iceberg table: every 30 minutes
- NSIDC G02135 Antarctic sea ice: every 6 hours
- NOAA NDBC latest observations: every 10 minutes
- Sentinel-1 GRD catalogue metadata: every 6 hours when OAuth credentials exist
- Copernicus Marine currents: daily at 02:00 UTC when credentials exist
- ERA5: daily at 03:00 UTC when CDS credentials exist

All intervals are configurable in `.env`.

## 3. Database modes

### Local zero-setup mode

Leave `DATABASE_URL` blank. NAV-X automatically creates:

`data/navx.db`

This is the easiest way to verify the build before installing PostgreSQL.

### PostgreSQL mode — recommended for deployment

Create a PostgreSQL database and set, for example:

`DATABASE_URL=postgresql+psycopg://navx_user:YOUR_PASSWORD@localhost:5432/navx_db`

If the password contains special URL characters such as `@`, `:`, `/` or `#`,
URL-encode the password before putting it in `DATABASE_URL`.

Then run:

`python scripts/init_database.py`

## 4. Provider credentials

### AISStream

Generate a key in your AISStream account and keep it server-side:

`AIS_PROVIDER=aisstream`
`AISSTREAM_API_KEY=...`

The browser never receives the key. AIS is a continuous WebSocket; the scheduler
periodically persists the latest genuine vessel states into SQL.

### USNIC

No API key is required by this build. NAV-X downloads the official public
Antarctic iceberg CSV, archives original snapshots and persists observations.

### NSIDC G02135

No API key is required for the NOAA@NSIDC HTTPS files used here. The downloader
automatically searches the current/recent month directories and selects the
newest available Southern Hemisphere concentration GeoTIFF.

### NOAA NDBC

No API key is required for the public latest-observations HTTPS file. NAV-X
persists only the actual observations returned by NDBC and filters them to the
configured Southern Ocean latitude band (`NDBC_MIN_LAT`). Zero matching stations
is treated as a valid real-data result.

### Copernicus Marine / CMEMS

Either run:

`copernicusmarine login`

or configure the current official environment variable names:

`COPERNICUSMARINE_SERVICE_USERNAME=...`
`COPERNICUSMARINE_SERVICE_PASSWORD=...`

### ERA5 / CDS

Create `%USERPROFILE%\.cdsapirc`:

`url: https://cds.climate.copernicus.eu/api`
`key: YOUR_PERSONAL_ACCESS_TOKEN`

Alternatively use:

`CDSAPI_URL=https://cds.climate.copernicus.eu/api`
`CDSAPI_KEY=...`

Accept the terms for the ERA5 dataset in CDS before the first automated request.

### Sentinel-1 / Copernicus Data Space

Create an OAuth Client in the Copernicus Data Space / Sentinel Hub dashboard and
set:

`SENTINEL_CLIENT_ID=...`
`SENTINEL_CLIENT_SECRET=...`

This build automatically discovers and stores real `sentinel-1-grd` catalogue
scene metadata for the Antarctic region. It intentionally does **not** claim that
SAR imagery has been downloaded, preprocessed or used for iceberg detection.
That requires a separate validated image-processing workflow.

### NASA Earthdata

`EARTHDATA_TOKEN` is included only as an optional credential placeholder.
Earthdata Login is authentication, not a scientific dataset. NAV-X does not make
a generic NASA request because a specific NASA collection/product must first be
selected and validated.

## 5. Verification commands

Initialize the database:

`python scripts/init_database.py`

Check configuration without printing any secret values:

`python scripts/check_setup.py`

Run a source manually:

`python scripts/ingest_now.py usnic`
`python scripts/ingest_now.py nsidc`
`python scripts/ingest_now.py ndbc`
`python scripts/ingest_now.py sentinel1`
`python scripts/ingest_now.py cmems`
`python scripts/ingest_now.py era5`

AIS is best tested while the FastAPI server is running because its source is a
continuous WebSocket stream.

Start NAV-X:

`python -m src.api.main`

Inspect:

- `/api/system/health`
- `/api/system/ingestion`
- `/api/data/database/summary`
- `/api/data/buoys`
- `/api/data/satellite/scenes`

The manual HTTP ingestion POST endpoint is disabled unless `NAVX_ADMIN_TOKEN` is
configured. This prevents a public visitor from triggering expensive downloads.
Prefer the local `scripts/ingest_now.py` commands for administration.

## 6. Production scheduler warning

Use only one in-process ingestion scheduler. If you deploy multiple Uvicorn/web
workers, run ingestion in one dedicated worker/cron service or otherwise ensure
that only one process has `AUTO_INGESTION_ENABLED=true`.
