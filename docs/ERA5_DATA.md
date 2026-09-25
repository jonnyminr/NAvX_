# ERA5 Meteorological Data (Copernicus C3S)

## 1. Overview
Meteorological conditions heavily influence Antarctic sea-ice drift and iceberg trajectories. The Antarctic Navigation Decision Support System uses ERA5 hourly data on single levels from the Copernicus Climate Change Service (C3S) as its ground-truth historical and near-current atmospheric data.

## 2. Dataset Specifications

*   **Official Source:** Copernicus Climate Change Service (C3S) / ECMWF
*   **Dataset Name:** ERA5 hourly data on single levels from 1940 to present
*   **Dataset Identifier:** `reanalysis-era5-single-levels`
*   **Official URL:** [https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-single-levels](https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-single-levels)
*   **Selected Variables:**
    *   `10m_u_component_of_wind` (u10): Eastward wind component at 10m height (m/s). Positive = blowing towards East.
    *   `10m_v_component_of_wind` (v10): Northward wind component at 10m height (m/s). Positive = blowing towards North.
    *   `2m_temperature` (t2m): Air temperature at 2m height (Kelvin).
    *   `mean_sea_level_pressure` (msl): Atmospheric pressure at sea level (Pascals).
*   **Spatial Resolution:** 0.25° x 0.25° grid (~30 km).
*   **Temporal Resolution:** Hourly.
*   **Spatial Subset Strategy:** Bounding box covering the Southern Ocean / Antarctica (Latitudes -90 to -50, Longitudes -180 to 180).
*   **Access Mechanism:** CDS API (`cdsapi` Python client). Requires a registered Copernicus user token.
*   **Licensing:** Free, open data under the Copernicus license.

## 3. Data Processing & Units
*   **Raw Format:** NetCDF4 (`.nc`).
*   **Unit Conversions & Derived Variables:**
    *   **Wind Speed:** Calculated as `sqrt(u10² + v10²)`. Units remain `m/s`.
    *   **Temperature:** Stored in Kelvin. Can be converted to Celsius via `K - 273.15` in the frontend/API if requested, but retained in Kelvin for physics models.
    *   **Pressure:** Stored in Pascals (Pa). Often divided by 100 to yield Hectopascals (hPa) for visualization.

## 4. API & Authentication Limitations
Accessing ERA5 data programmatically requires setting up `.cdsapirc` in the user's home directory or passing credentials securely via environment variables.

### Required User Action if Download Fails:
1. Register for an account at [https://cds.climate.copernicus.eu/](https://cds.climate.copernicus.eu/)
2. Accept the Terms & Conditions for the ERA5 dataset.
3. Retrieve your Personal API Token from your profile.
4. Create a `.cdsapirc` file in your home directory (e.g., `C:\Users\YOUR_USER\.cdsapirc`) with the following structure:
```text
url: https://cds.climate.copernicus.eu/api/v2
key: YOUR_UID:YOUR_API_KEY
```
If credentials are absent, the ingestion pipeline will gracefully fail and report the missing authentication without fabricating weather data.
