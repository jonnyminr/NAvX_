# Ocean and Sea-Ice Drift Data (Copernicus Marine)

## 1. Overview
Ocean currents and sea-ice drift vectors are primary physical forcing agents governing the kinematics of Antarctic icebergs. Phase 4 of the Navigation Intelligence system integrates these fields to build the baseline environmental feature matrix for trajectory prediction.

## 2. Dataset Specifications

### A. Ocean Surface Currents
*   **Source:** Copernicus Marine Environment Monitoring Service (CMEMS)
*   **Product ID:** `GLOBAL_ANALYSISFORECAST_PHY_001_024`
*   **Dataset ID:** `cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m`
*   **Variables:** `uo` (Eastward velocity, m/s), `vo` (Northward velocity, m/s)
*   **Depth Selected:** ~0.494m (Surface). *Scientific Justification:* Icebergs are predominantly forced by surface/near-surface ocean drag, surface wind shear, and pack-ice collisions. Without precise draft/keel measurements for every iceberg, surface currents provide the most statistically significant advection vector.
*   **Spatial Resolution:** 0.083° x 0.083° (~8 km)
*   **Temporal Resolution:** Daily Mean
*   **Spatial Extent:** Global (Subset applied dynamically: Latitude <= -50°)

### B. Sea-Ice Velocity (Model Derived)
*   **Source:** Copernicus Marine Environment Monitoring Service (CMEMS)
*   **Product ID:** `GLOBAL_ANALYSISFORECAST_PHY_001_024`
*   **Dataset ID:** `cmems_mod_glo_phy-si_anfc_0.083deg_P1D-m`
*   **Variables:** `usi` (Eastward sea ice velocity, m/s), `vsi` (Northward sea ice velocity, m/s)
*   **Spatial Resolution:** 0.083° x 0.083° (~8 km)
*   **Temporal Resolution:** Daily Mean
*   **Spatial Extent:** Global (Subset applied dynamically: Latitude <= -50°)
*   *Validation Note:* This model-derived sea-ice drift is preferred for continuous operational prediction input due to lack of satellite occlusion gaps (clouds/darkness). For rigorous validation, it can later be compared against L3/L4 Satellite products (`SEAICE_ANT_PHY_L3_MY_011_018`).

## 3. Data Processing & Calculations
*   **Raw Format:** NetCDF4 (`.nc`), retrieved via `copernicusmarine` Python client.
*   **Calculations (Vector Physics):**
    *   `ocean_speed = sqrt(uo² + vo²)`
    *   `ocean_direction = atan2(vo, uo)` (Output in radians, following mathematical convention)
    *   `sea_ice_speed = sqrt(usi² + vsi²)`
    *   `sea_ice_direction = atan2(vsi, usi)`
*   **Missing Values:** Cells masked as NaN (e.g., landmasses) remain NaN. Artificial extrapolation is strictly disabled.
*   **Alignment/Data Fusion:** Variables are unified into a normalized structure (`time, latitude, longitude`). Spatial interpolation uses nearest-neighbor to align the 0.083° ocean grid with the 0.25° ERA5 weather grid for unified risk/navigation processing.

## 4. API, Authentication, and Dual-Mode Architecture
The system supports a highly robust Dual-Mode Data Provider architecture to guarantee functionality during live demonstrations without network access.

### A. CMEMS LIVE PROVIDER
If a valid token is found at `~/.copernicusmarine/.copernicusmarine-credentials`, the system securely requests the exact temporal and spatial subset via the official API, ensuring maximum data freshness.
*   **API Response Tag:** `CMEMS LIVE`

### B. LOCAL NETCDF PROVIDER (Offline Cache)
If the CMEMS API is unreachable or unauthenticated, the data orchestrator seamlessly falls back to authoritative offline files stored in the cache. 
*   **API Response Tag:** `CMEMS DOWNLOADED OFFLINE DATA`

#### Offline Data Injection Instructions (For SIH Evaluators/Developers)
To manually inject an authoritative offline cache file without credentials:
1. Download a NetCDF file containing `uo` and `vo` from CMEMS manually via browser.
2. Move the file into the project directory at: `data/raw/`
3. Ensure the filename matches the pattern `ocean_*.nc` (e.g., `ocean_currents_offline.nc`).
4. The system's `LocalNetCDFProvider` will automatically detect the file, process the vector magnitude and direction physically, and serve it via the API. Never fake or randomly generate this file.
