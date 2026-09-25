# START HERE — NAV-X Database + Automatic Fetching

Use this file after extracting the ZIP on Windows.

## A. First run with the built-in SQLite database

Open PowerShell in the folder that directly contains `src` and `requirements.txt`.

```powershell
python --version
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/init_database.py
python scripts/check_setup.py
python -m src.api.main
```

Open:

`http://localhost:8000/app/`

Check:

`http://localhost:8000/api/system/health`

`http://localhost:8000/api/system/ingestion`

`http://localhost:8000/api/data/database/summary`

With `DATABASE_URL` blank, NAV-X automatically uses `data/navx.db`.

## B. Switch to PostgreSQL

Install PostgreSQL for Windows, then open **SQL Shell (psql)** and connect as the `postgres` administrator. Run:

```sql
CREATE USER navx_user WITH PASSWORD 'CHANGE_THIS_PASSWORD';
CREATE DATABASE navx_db OWNER navx_user;
\c navx_db
GRANT ALL ON SCHEMA public TO navx_user;
\q
```

Then set this in `.env`:

```env
DATABASE_URL=postgresql+psycopg://navx_user:YOUR_PASSWORD@localhost:5432/navx_db
```

Restart the terminal/venv if needed, then run:

```powershell
python scripts/init_database.py
python scripts/check_setup.py
```

Do not keep both SQLite and PostgreSQL active. `DATABASE_URL` decides which one
NAV-X uses when the process starts.

## C. Add provider credentials to `.env`

```env
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=

COPERNICUSMARINE_SERVICE_USERNAME=
COPERNICUSMARINE_SERVICE_PASSWORD=

CDSAPI_URL=https://cds.climate.copernicus.eu/api
CDSAPI_KEY=

SENTINEL_CLIENT_ID=
SENTINEL_CLIENT_SECRET=
```

USNIC, NSIDC G02135 and NOAA NDBC do not require API keys in this build.

## D. Test each provider

```powershell
python scripts/ingest_now.py usnic
python scripts/ingest_now.py nsidc
python scripts/ingest_now.py ndbc
python scripts/ingest_now.py sentinel1
python scripts/ingest_now.py cmems
python scripts/ingest_now.py era5
```

AIS is a long-lived WebSocket, so test it by starting the server and opening:

`http://localhost:8000/api/data/vessels`

## E. Normal run

```powershell
.\venv\Scripts\Activate.ps1
python -m src.api.main
```

The automatic scheduler starts with the FastAPI application. Only configured
credentialed providers are scheduled; keyless USNIC/NSIDC/NDBC jobs can run
automatically.

## Python 3.14 note

The project uses compiled scientific packages. Try your installed Python 3.14
first. If `pip install -r requirements.txt` reports that a scientific dependency
has no compatible wheel/build for Python 3.14, install Python 3.12 and create the
venv with:

```powershell
py -3.12 -m venv venv
```

Then repeat the installation inside that venv.
