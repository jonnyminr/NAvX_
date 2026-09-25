# ANTARCTIC NAV-X Frontend Redesign V10

This build replaces the operator frontend with a clean white/ice-blue NAV-X interface inspired by the supplied multi-page reference while preserving the existing FastAPI routing, real-data providers, route optimizer, GPS workflow, MapLibre map, AIS handling, iceberg forecasting, and scientific provenance behavior.

## Pages

- Home
- Live Map
- Environmental Forecast
- Voyage Planner
- Route Details
- Risk Dashboard
- Data Observatory
- Risk / Iceberg Details
- Alerts & Notifications
- Scenario Simulator
- Historical Replay
- Iceberg Catalog
- AIS Vessel Catalog
- Profile & Settings

Every sidebar item is a real hash hyperlink that swaps the complete workspace view instead of scrolling to sections.

## Scientific-integrity rules

- Official iceberg observations are from USNIC only.
- AIS rows/markers appear only for positions actually received from the configured provider.
- Environmental values come from fresh model guidance when available, otherwise the bundled verified CMEMS/ERA5/NSIDC scientific files are explicitly identified as cached fallback.
- Missing data stays `DATA UNAVAILABLE`; the frontend does not fabricate waves, ships, iceberg fixes, risk values, routes, or source freshness.
- Future iceberg positions are labelled model forecasts and are never presented as observations.
- Scenario Simulator changes only operator-supported route parameters (speed and safety buffer) while keeping the same real scientific inputs.
- Historical Replay reads archived official USNIC CSV snapshots and does not interpolate between dates.

## New API

`GET /api/data/icebergs/archive` exposes the bundled official USNIC archived snapshots to Historical Replay. It returns exact archived coordinates and source metadata only.

## Security

Keep credentials in `.env` only. Do not commit or redistribute a populated `.env`. The deliverable keeps `.env.example` as the configuration template.

## Verification

The full automated test suite passes after the redesign, including integrity, routing, trajectory, data, and new V10 frontend/archive tests.
