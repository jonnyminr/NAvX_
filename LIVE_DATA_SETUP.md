# Live Data Setup — AIS Ships + Freshest Official USNIC Icebergs

## What is actually real-time?

### Ships — live AIS
NAV-X can consume live vessel position messages from **AISStream.io** through a backend WebSocket. The secret API key is never sent to the browser. The frontend polls the local FastAPI snapshot every 5 seconds and updates ship icons on Mappls.

AISStream documentation: https://aisstream.io/documentation

### Icebergs — freshest official observation, not continuous telemetry
The U.S. National Ice Center (USNIC) is the authoritative public naming/tracking source for large Antarctic icebergs. Its iceberg table is an official periodic/weekly product, not a real-time GPS feed. NAV-X downloads the current USNIC CSV in the background every 30 minutes and always uses the latest official positions available.

USNIC Antarctic icebergs: https://usicecenter.gov/Products/AntarcIcebergs/

This distinction is intentional: NAV-X does not claim a weekly satellite-derived iceberg observation is a live GPS fix.

## 1. Create an AISStream key

1. Open https://aisstream.io/account
2. Sign in/create the account requested by AISStream.
3. Create a new API key.
4. Copy it once and keep it private.

## 2. Put the key in `.env`

From the project folder containing `src` and `requirements.txt`:

```powershell
notepad .env
```

Add:

```env
MAPPLS_STATIC_KEY=YOUR_MAPPLS_STATIC_KEY
AISSTREAM_API_KEY=YOUR_AISSTREAM_API_KEY
```

Do not put quotes around the values. Do not commit `.env`.

## 3. Install the new live-stream dependency

If you already had the old venv, activate it and update requirements:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The new dependency is `websockets`.

## 4. Run NAV-X

```powershell
.\venv\Scripts\Activate.ps1
python -m src.api.main
```

Open:

```text
http://localhost:8000/app/
```

If you use a legacy Mappls Web key with domain restrictions, whitelist your deployed HTTPS hostname in the Mappls developer console.

## 5. Confirm the feeds

Safe status endpoint:

```text
http://localhost:8000/api/system/health
```

Live-source status:

```text
http://localhost:8000/api/config/realtime
```

Recent vessels:

```text
http://localhost:8000/api/data/vessels
```

Freshest cached official icebergs:

```text
http://localhost:8000/api/data/icebergs
```

The header shows `AIS LIVE (N)` after the backend receives position messages. If AIS is configured but there are zero ships, that can be legitimate because Antarctic AIS reception and vessel activity are sparse.

## Map symbols

- Iceberg symbol: cyan/white iceberg icon — official USNIC observed location.
- Selected iceberg: larger highlighted iceberg icon + ID label.
- Ship symbol: amber vessel/heading icon — recent live AIS position.
- Orange line: predicted iceberg trajectory.
- Blue line: demonstration vessel route.
- Green line: recommended alternative route.

## Accuracy and limits

- AIS `PositionAccuracy` is displayed as the AIS-reported accuracy flag; NAV-X does not convert it into an unsupported exact error radius.
- USNIC coordinates are shown at their source precision. Extra decimal places are not invented.
- New USNIC icebergs automatically appear when the official current table changes.
- Smaller untracked icebergs are not fabricated. Detecting them reliably would require an additional satellite-imagery detection pipeline (for example Sentinel-1 SAR), validation, and a different validated detection workflow.
- This is research/decision-support software, not a certified ECDIS or collision-avoidance system.


## V4 actual-vessel controls

The V4 map includes a **Live Vessel** selector. Once AIS messages arrive, choose a vessel to center Mappls on its latest genuine AIS position. Keep **Selected track** enabled to draw that vessel's recent received AIS path.

Marker freshness:

- Green: LIVE, received within 2 minutes
- Amber: RECENT, received within 15 minutes
- Red: STALE, older than 15 minutes but still inside the configured cache window

Optional `.env` tuning:

```env
AIS_MIN_LAT=-45
AIS_CACHE_HOURS=6
```

`AIS_MIN_LAT=-45` captures Southern Ocean approach traffic as well as Antarctic waters. Use `-60` if you want only the Antarctic Treaty-area latitude band. The application does not invent vessels when the stream is quiet.
