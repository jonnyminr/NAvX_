# ANTARCTIC NAV-X — START HERE

This ZIP contains one FastAPI application serving both the frontend and backend. It is not a Vite/React project, so there is no `npm install`, `npm run build`, or separate frontend server.

## 1. Extract and open

Extract the ZIP, open the project folder in VS Code, then open **Terminal > New Terminal**.

## 2. Create the Python environment

```powershell
py -3.12 --version
py -3.12 -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Create private configuration

```powershell
Copy-Item .env.example .env
notepad .env
```

Do not commit or share the resulting `.env` file.

### Map — no API key required

The current operator map uses OpenFreeMap with an automatic OpenStreetMap fallback. Keep the default unless you intentionally operate another compatible OpenFreeMap style endpoint:

```env
OPENFREEMAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
MAPPLS_STATIC_KEY=
```

There is no MapTiler key to create, restrict, or debug.

### Real AIS — AISStream example

```env
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=YOUR_REAL_AISSTREAM_KEY
```

If AIS is not configured, the system deliberately shows 0 current vessels instead of simulated positions.

## 4. Start frontend + backend

```powershell
python -m src.api.main
```

Open:

```text
http://localhost:8000/app/
```

That single command starts both the API and the supplied frontend.

## 5. GPS

On localhost, grant browser location permission when requested.

For phone/public testing, publish the app as an HTTPS web service using `PUBLISH_SITE.md`. Then open the deployed HTTPS URL and grant Location permission in the browser.

Use **Use GPS** for a single fix. Use **Start Live GPS** only when continuous tracking is wanted, **Stop GPS** to end the watch, and **Follow GPS** to control map recentering.

## 6. Run tests

```powershell
python -m pytest -q
```

Expected release result for this AI/ML build:

```text
68 passed
```


## 7. AI / ML training

The ZIP includes a trained physics-informed iceberg residual model and a separate AIS anomaly training pipeline. To retrain the iceberg model from the real archived USNIC + CMEMS/ERA5 data:

```powershell
python -m src.ml.train_all --only iceberg
```

To train every ML component for which enough genuine data exists:

```powershell
python -m src.ml.train_all
```

Open the **NAV-X AI / ML** page in the sidebar to see model status and held-out validation metrics. Full instructions are in `AI_ML_SETUP_AND_TRAINING.md`.

## 8. Main configuration variables

```env
OPENFREEMAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
MAPPLS_STATIC_KEY=

AIS_PROVIDER=auto
AISSTREAM_API_KEY=
AISHUB_USERNAME=
AISHUB_POLL_SECONDS=65
DATALASTIC_API_KEY=
DATALASTIC_CACHE_SECONDS=120
AIS_MIN_LAT=-45
AIS_MAX_POSITION_AGE_MINUTES=180
AIS_CACHE_HOURS=6

COPERNICUS_USERNAME=
COPERNICUS_PASSWORD=

HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=
```

ERA5/CDS uses the official `~/.cdsapirc` credentials rather than a browser key.

## 9. Real data sources

- USNIC: official Antarctic iceberg observations / project extent source files
- CMEMS: ocean currents and ocean validity cells
- NSIDC: Antarctic sea-ice concentration
- ERA5 / ECMWF: wind/atmospheric forcing
- AISStream, AISHub or Datalastic: real AIS only when configured

See `REAL_DATA_SETUP.md` for provider-specific registration details.

## 10. Important behavior

- Latitude and longitude are validated separately and never silently swapped.
- Invalid speed/departure/coordinates return useful errors.
- Map clicks are validated before being used as route points.
- Routes use the real CMEMS/NSIDC navigation surface.
- Unknown/non-navigable cells are rejected.
- No verified path means **NO VERIFIED ROUTE AVAILABLE**.
- Missing risk evidence means **INSUFFICIENT VERIFIED DATA**, not a made-up score.
- No AIS reception means an empty real-data state, not fake vessels.
