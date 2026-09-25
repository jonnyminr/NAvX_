# Actual Live AIS Vessels — V4

This build upgrades the live vessel layer so the Mappls ship markers are driven only by genuine AIS position messages received by the FastAPI backend from AISStream.io.

## What changed

- 45°S–90°S Southern Ocean subscription by default.
- Position reports for Class A, standard Class B and extended Class B vessels.
- Optional ship static/voyage metadata enrichment.
- 5-second browser snapshot refresh.
- LIVE / RECENT / STALE age classification.
- Selected-vessel dropdown and map centering.
- Selected-vessel rolling AIS track.
- Genuine received-position cache with original timestamps.
- Live/recent/stale counts and last-message diagnostics.

## Required `.env`

```env
MAPPLS_STATIC_KEY=YOUR_MAPPLS_KEY
AISSTREAM_API_KEY=YOUR_AISSTREAM_KEY
AIS_MIN_LAT=-45
AIS_CACHE_HOURS=6
```

Run with:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m src.api.main
```

Open `http://localhost:8000/app/` for local testing, or use the HTTPS URL of your deployed service for public access.

## Important limitation

AISStream is event-driven and Antarctic reception is sparse. A zero-vessel count can be a real operational state. The application does not synthesize missing ships.
