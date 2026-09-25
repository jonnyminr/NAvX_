# ANTARCTIC NAV-X — Database Build Summary

This package is the database-enabled real-data build of the uploaded NAV-X project.

## Added

- SQLAlchemy persistence with automatic SQLite fallback
- PostgreSQL support through `DATABASE_URL`
- observation tables for USNIC icebergs, AIS vessel positions and NOAA NDBC buoys
- dataset provenance/checksum table for large NSIDC/CMEMS/ERA5 files
- Sentinel-1 GRD catalogue scene metadata table
- provider fetch audit table and scheduler state table
- APScheduler-based automatic ingestion
- automatic latest-month discovery for NSIDC G02135
- official Copernicus Marine headless credential environment names
- current CDS personal-access-token support
- Copernicus Data Space OAuth client support for Sentinel-1 catalogue metadata
- protected manual ingestion API using `NAVX_ADMIN_TOKEN`
- setup/verification scripts under `scripts/`

## Preserved

- existing frontend
- existing route planner and `PolarAStarRouter`
- `RealOceanSurface`
- current physics/ML trajectory logic
- real-data-only behavior
- existing AIS provider manager
- existing offline scientific data fallback

## Validation

The supplied repository test suite passes after the changes:

`70 passed`

No real API keys, passwords, database passwords or tokens are included in the ZIP.
