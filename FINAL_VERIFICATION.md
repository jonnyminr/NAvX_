# ANTARCTIC NAV-X — OpenMap Release Verification

Release verification date: 2026-09-07

## Architecture

- Backend + frontend server: FastAPI
- Frontend: `src/api/static/index.html` (plain HTML/CSS/JavaScript; no Vite/React build step)
- Operator map: MapLibre GL JS
- Primary basemap: OpenFreeMap `liberty` vector style
- Automatic fallback basemap: OpenStreetMap standard raster tiles
- Basemap API key: **not required**
- Navigation surface: `RealOceanSurface` using CMEMS + NSIDC
- Router: `PolarAStarRouter`

The basemap is visual context only. USNIC observations, CMEMS/ERA5/NSIDC overlays, AIS positions, route geometry, CPA/TCA and risk outputs remain NAV-X backend/scientific data products.

## Start command

```powershell
python -m src.api.main
```

Open `http://localhost:8000/app/`.

## Map configuration

No MapTiler/Mapbox/Google key is required. Optional override:

```env
OPENFREEMAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
MAPPLS_STATIC_KEY=
```

`/api/config/map` reports `KEYLESS_WITH_FALLBACK`. `/api/map/style` provides the same-origin OpenStreetMap raster fallback style. The retired `/api/map/tiles/{z}/{x}/{y}` MapTiler proxy returns HTTP 410 so an old client cannot silently use it.

## AIS configuration

For AISStream:

```env
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=
```

Without an AIS credential NAV-X returns zero current vessels rather than fabricated positions.

## Tests executed

```powershell
python -m pytest -q
```

Result on the final source:

```text
64 passed, 17 warnings
```

The warnings are existing FastAPI `on_event()` and Python `datetime.utcnow()` deprecation notices; they are not failures.

Frontend module syntax was also checked with `node --check` after extracting the inline module script.

## Local server/API smoke verification

The exact final source was started on port 8012 and returned HTTP 200 for:

- `/app/`
- `/api/config/map`
- `/api/map/style`
- `/api/system/health`
- `/api/locations/antarctica`
- `/api/data/icebergs`
- `/api/data/vessels`
- `/api/data/ice-extent-trends`
- `/api/system/provenance`
- `/api/navigation/surface-check?lat=-60&lon=-56`
- `/api/navigation/optimize`

The optimizer smoke request returned 3 route records and 3 backend comparison-metric rows for the tested verified open-ocean corridor.

## Map verification status

The local map configuration, fallback style JSON, frontend initialization/fallback logic and MapLibre JavaScript syntax were verified. The packaging environment cannot make outbound DNS requests to map CDNs, so it could not truthfully render external OpenFreeMap/OpenStreetMap tiles during packaging. The UI automatically tries OpenFreeMap first and switches to the OpenStreetMap fallback when the primary basemap cannot initialize.

MapLibre GL JS itself remains loaded from UNPKG with a jsDelivr fallback because the packaging environment could not download/vendor the library asset.

## Security

- No `.env` containing real credentials is included in the release ZIP.
- The current basemap requires no API credential.
- `MAPPLS_STATIC_KEY`, `AISSTREAM_API_KEY`, Datalastic credentials and scientific-service credentials remain server/private configuration values.
- Previously supplied MapTiler/CDS credential strings were scanned for and are not present in the release files.

## Scientific integrity

The release preserves bundled USNIC, CMEMS, NSIDC and ERA5 scientific data. Operational routing does not use a straight-line fallback through invalid/unknown navigation cells. Missing verified data is represented as unavailable/insufficient rather than filled with fabricated values.

This is a real-data, physics-informed decision-support prototype; it is not an ECDIS replacement or certified navigation system.
