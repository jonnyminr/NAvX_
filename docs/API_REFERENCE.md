# ANTARCTIC NAV-X API Reference

The bundled frontend is same-origin with FastAPI. All JSON endpoints are under `/api/`.

## Configuration / health

- `GET /api/config/map` — safe keyless map provider/status metadata for OpenFreeMap + OpenStreetMap fallback. No basemap API key is required or returned.
- `GET /api/map/style` — same-origin keyless OpenStreetMap raster fallback style for MapLibre GL JS.
- `GET /api/map/tiles/{z}/{x}/{y}` — retired compatibility path; returns HTTP 410 so old clients cannot silently use the removed MapTiler proxy.
- `GET /api/config/realtime` — safe realtime-provider status.
- `GET /api/system/health` — data/map/provider availability and freshness metadata.
- `GET /api/system/provenance` — scientific-source provenance and operator-map status.
- `GET /api/system/ingestion` — scheduler jobs, database reachability and recent provider-fetch audit records.
- `GET /api/data/database/summary` — row counts and latest persisted observation timestamps.

## Antarctic reference locations / navigation surface

- `GET /api/locations/antarctica` — verified project reference locations with coordinates/source/precision/route eligibility metadata.
- `GET /api/navigation/surface-check?lat=...&lon=...` — validates a point against the real CMEMS/NSIDC navigation surface.

## Scientific data

- `GET /api/data/icebergs` — official/cached USNIC iceberg observations; no fabricated records.
- `GET /api/data/icebergs/{iceberg_id}/history` — observed history available for an iceberg.
- `POST /api/data/icebergs/refresh` — refresh path for official observations.
- `GET /api/data/vessels` — received AIS data only; empty result when no provider/positions are available.
- `GET /api/data/buoys` — persisted real NOAA NDBC observations filtered to the configured Southern Ocean latitude band.
- `GET /api/data/satellite/scenes` — authenticated Copernicus Data Space Sentinel-1 GRD catalogue metadata only; no SAR detection claim is made by this endpoint.
- `GET /api/data/weather` — available atmospheric data metadata/samples.
- `GET /api/data/ocean` — available ocean-current data metadata/samples.
- `GET /api/data/ice-extent-trends` — bundled official USNIC sea-ice extent trend series; missing dates are not fabricated.
- `GET /api/environmental/sample?lat=...&lon=...` — real/cached environmental forcing sample.
- `GET /api/environmental/precision-sample?lat=...&lon=...` — precision environmental sampling response where supported.

## Forecast / risk / navigation

- `POST /api/prediction/trajectory` — physics-informed iceberg trajectory forecast from verified observation/environment inputs.
- `POST /api/navigation/risk` — route/forecast hazard assessment.
- `POST /api/navigation/analyze` — analysis endpoint retained for compatibility; it does not advertise heuristic synthetic alternatives as operational routes.
- `POST /api/navigation/optimize` — primary Route A/B/C ocean-surface-constrained optimizer.
- `POST /api/navigation/routes` — compatibility alias to the exact same optimizer implementation; it does not create a second routing engine.

The verified optimizer uses `RealOceanSurface` + `PolarAStarRouter`. Invalid/unknown navigation cells fail closed. If no verified route exists, the response marks the route unavailable rather than returning a straight line.

Route-comparison rows contain backend-calculated metrics including distance, transit time, risk/clearance fields when supported by verified inputs, initial bearing and arrival UTC. Missing risk evidence remains unavailable rather than being coerced to zero.

## Model diagnostics

- `GET /api/model/evaluation`
- `GET /api/model/calibration`

These endpoints expose available model evaluation/calibration metadata; sensitivity ensembles must not be interpreted as calibrated confidence intervals unless explicitly supported by the model metadata.
