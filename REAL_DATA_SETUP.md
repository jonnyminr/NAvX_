# ANTARCTIC NAV-X — Genuine Data and Provider Setup

ANTARCTIC NAV-X is designed to fail visibly when required verified data is unavailable. It does not replace missing scientific/AIS observations with fabricated values.

## 1. Operator basemap — OpenFreeMap + OpenStreetMap fallback

The operator-facing map is intentionally keyless. NAV-X keeps MapLibre GL JS for interaction and uses:

- **Primary:** OpenFreeMap `liberty` vector style (OpenStreetMap-derived data)
- **Fallback:** OpenStreetMap standard raster tiles

Default configuration:

```env
OPENFREEMAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
MAPPLS_STATIC_KEY=
```

No basemap API key is required. `/api/config/map` returns safe provider/status metadata only. `/api/map/style` returns the fallback raster style and contains no secrets. Scientific observations, forecasts, hazards, routes, CPA/TCA and environmental overlays remain independent NAV-X data/model outputs.

`MAPPLS_STATIC_KEY` is retained only for compatibility with older deployments and is not required by the current operator map.

## 2. USNIC Antarctic iceberg observations

Source: U.S. National Ice Center (USNIC).

- Public product: https://usicecenter.gov/Products/Antarcicebergs
- No API key is required for the public iceberg observations used by NAV-X.
- Bundled official observations remain available as a real-data cache.
- Observation date/source/position are retained.
- Missing dimensions or uncertainty stay `N/A`; they are not invented.
- Observed positions are visually/semantically distinct from model forecast positions.

USNIC observations are periodic official observations, not continuous iceberg GPS tracks.

## 3. CMEMS / Copernicus Marine

Source: Copernicus Marine Service.

Register at:

```text
https://marine.copernicus.eu/
```

Authenticate with the official toolbox flow when refreshing data:

```powershell
copernicusmarine login
```

For automated/headless operation use the official Copernicus Marine environment variables:

```env
COPERNICUSMARINE_SERVICE_USERNAME=
COPERNICUSMARINE_SERVICE_PASSWORD=
```

The older `COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD` aliases remain accepted for backwards compatibility.

Bundled genuine CMEMS NetCDF data remains available for reproducible offline current forcing and ocean-validity checks. NAV-X does not interpret missing CMEMS cells as zero current or automatically navigable water.

## 4. ERA5 / ECMWF

Source: Copernicus Climate Data Store / ECMWF ERA5.

Register/sign in at:

```text
https://cds.climate.copernicus.eu/
```

Configure the official CDS API token in `~/.cdsapirc` according to the CDS API instructions. No CDS credential belongs in frontend JavaScript.

Bundled genuine ERA5 data may be used as cached forcing when a live refresh is not being performed. The application reports provenance/freshness rather than presenting the cache as a live observation.

## 5. NSIDC Antarctic sea ice

Source: National Snow and Ice Data Center (NSIDC).

The repository contains genuine Antarctic sea-ice concentration data used by the routing/environmental pipeline. The G02135 files used by this build are fetched from NOAA@NSIDC's public HTTPS file system and do not require an API key. The downloader automatically discovers the newest available current/recent month.

NAV-X does not create a synthetic sea-ice grid when NSIDC data is unavailable.

## 6. Real AIS

Set one provider in `.env`. If none is configured or no positions are received, `/api/data/vessels` returns an empty real-data response.

### AISStream

```env
AIS_PROVIDER=aisstream
AISSTREAM_API_KEY=your_private_key
```

The API key remains server-side. Only actual received AIS records populate the catalogue/map.

### AISHub

```env
AIS_PROVIDER=aishub
AISHUB_USERNAME=your_member_username
AISHUB_POLL_SECONDS=65
```

AISHub access is membership/contributor dependent. NAV-X enforces a polling interval above one minute.

### Datalastic

```env
AIS_PROVIDER=datalastic
DATALASTIC_API_KEY=your_private_key
DATALASTIC_CACHE_SECONDS=120
```

The provider integration uses genuine area-query results and caches repeated scans briefly to avoid unnecessary API-credit use.

### MarineTraffic

No generic MarineTraffic adapter is fabricated because its API products/schema depend on the subscription contract. Integrate only an endpoint and schema actually supplied by your MarineTraffic plan.

## 7. Data-unavailable behavior

Expected operational messages include:

```text
DATA UNAVAILABLE
INSUFFICIENT VERIFIED DATA
NO CURRENT AIS POSITIONS RECEIVED
NO VERIFIED ROUTE AVAILABLE
```

These states are intentional safeguards. They must not be replaced with random values, generated ships, straight-line routes or fake graph metrics.

## 8. Provenance

The API exposes safe scientific provenance through:

```text
GET /api/system/provenance
GET /api/system/health
```

These endpoints report source/status/freshness metadata and are tested not to echo configured Mappls or AIS secret values.
