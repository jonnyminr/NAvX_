# DATA SOURCES / SCIENTIFIC PROVENANCE

This document outlines the official, scientifically validated datasets used by the Antarctic Sea-Ice, Iceberg Trajectory, and Navigation Decision Support System (SIH26059).

---

## 1. Antarctic Sea-Ice Concentration

*   **Official Provider:** National Snow and Ice Data Center (NSIDC) / NOAA
*   **Dataset Name:** Sea Ice Index, Version 4
*   **Dataset Identifier:** G02135
*   **Official URL:** [https://nsidc.org/data/g02135/versions/4](https://nsidc.org/data/g02135/versions/4)
*   **DOI:** https://doi.org/10.7265/a98x-0f50
*   **Variables:** Sea Ice Concentration, Sea Ice Extent
*   **Units:** Percentage (%) for concentration
*   **Spatial Resolution:** 25 km x 25 km
*   **Temporal Resolution:** Daily
*   **Coverage:** Antarctic (South Polar Stereographic)
*   **Projection/Coordinate System:** EPSG:3412 for the supplied G02135 Southern Hemisphere GeoTIFFs (read from file metadata at runtime)
*   **File Format:** GeoTIFF (and shapefiles)
*   **Access Requirements:** Public/Open (No authentication required via noaadata.apps.nsidc.org)
*   **License:** Public Domain / Open Data
*   **Update Frequency:** Daily
*   **Known Limitations:** Passive microwave sensors can struggle with surface melt (during austral summer) leading to underestimation of ice concentration. 25km resolution limits near-shore precision.

## 2. Antarctic Iceberg Tracking Data

*   **Official Provider:** U.S. National Ice Center (USNIC)
*   **Dataset Name:** USNIC Antarctic Iceberg Data
*   **Dataset Identifier:** N/A (Maintained Database)
*   **Official URL:** [https://usicecenter.gov/Products/AntarcIcebergs](https://usicecenter.gov/Products/AntarcIcebergs)
*   **Variables:** Iceberg ID, Latitude, Longitude, Size, Date observed
*   **Units:** Decimal degrees (Lat/Lon), Nautical Miles (Size)
*   **Spatial Resolution:** Point observations
*   **Temporal Resolution:** Weekly (Updated as observed via satellite)
*   **Coverage:** Antarctic Ocean
*   **Projection/Coordinate System:** WGS 84 (EPSG:4326)
*   **File Format:** CSV, Shapefile
*   **Access Requirements:** Public/Open
*   **License:** Public Domain
*   **Update Frequency:** Weekly
*   **Known Limitations:** Only tracks icebergs > 10 nm along the longest axis. Smaller ice hazards ("growlers") are not tracked in this dataset, which poses a limitation for fine-scale navigation risk.

## 3. Atmospheric and Weather Data

*   **Official Provider:** Copernicus Climate Change Service (C3S) / ECMWF
*   **Dataset Name:** ERA5 hourly data on single levels from 1940 to present
*   **Dataset Identifier:** reanalysis-era5-single-levels
*   **Official URL:** [https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-single-levels](https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-single-levels)
*   **DOI:** 10.24381/cds.adbb2d47
*   **Variables:** 10m u-component of wind, 10m v-component of wind, 2m temperature, Mean sea level pressure
*   **Units:** m/s (Wind), K (Temperature), Pa (Pressure)
*   **Spatial Resolution:** 0.25° x 0.25° (~30 km)
*   **Temporal Resolution:** Hourly
*   **Coverage:** Global (Filtered to Antarctic bounding box)
*   **Projection/Coordinate System:** WGS 84
*   **File Format:** NetCDF, GRIB
*   **Access Requirements:** Free registration and API key required (CDS API)
*   **License:** Copernicus License (Open and Free)
*   **Update Frequency:** Daily (with a ~5 day delay for ERA5, or ERA5T for near-current)
*   **Known Limitations:** Reanalysis data uses a fixed model grid. Wind forecasting in coastal Antarctica can be affected by katabatic winds not fully resolved at 0.25° resolution.

## 4. Ocean Currents and Sea-Ice Drift

*   **Official Provider:** Copernicus Marine Service
*   **Dataset Name:** Global Ocean Physics Analysis and Forecast
*   **Dataset Identifier:** GLOBAL_ANALYSISFORECAST_PHY_001_024
*   **Official URL:** [https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024](https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024)
*   **Variables:** Sea water velocity (eastward, northward), Sea ice drift velocity
*   **Units:** m/s
*   **Spatial Resolution:** 1/12° (approx. 8 km)
*   **Temporal Resolution:** Daily mean / Hourly
*   **Coverage:** Global
*   **Projection/Coordinate System:** WGS 84
*   **File Format:** NetCDF
*   **Access Requirements:** Free registration and API key required
*   **License:** Copernicus License (Open and Free)
*   **Update Frequency:** Daily
*   **Known Limitations:** Ocean models can have biases in the Southern Ocean near the ice edge and grounding lines.

## 5. Sentinel-1 SAR Catalogue Metadata

* **Official Provider:** Copernicus Data Space Ecosystem / Sentinel Hub Catalog API
* **Collection:** `sentinel-1-grd`
* **Authentication:** OAuth2 client credentials (`SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET`)
* **NAV-X use in this build:** Automatic Antarctic scene discovery and metadata persistence only.
* **Integrity rule:** A catalogue result is not presented as an analysed iceberg detection. Actual SAR product download, preprocessing and validated detection must occur before any detection claim.

## 6. NOAA NDBC Marine/Buoy Observations

* **Official Provider:** NOAA National Data Buoy Center
* **Source:** NDBC latest observations HTTPS file
* **Authentication:** None for this public feed
* **NAV-X use:** Automatic fetch, Southern Ocean latitude filtering, and persistence of the actual station observations returned by NDBC.
* **Integrity rule:** Zero matching Antarctic/Southern Ocean stations is a valid result and is not replaced with synthetic observations.

## 7. NASA Earthdata

Earthdata Login is an authentication service rather than one scientific dataset. The `.env` includes an optional `EARTHDATA_TOKEN` placeholder, but NAV-X does **not** make a generic NASA download request because doing so without a specific named product would be scientifically ambiguous. Add a NASA ingestion job only after selecting the exact dataset, collection identifier, variables, spatial subset and cadence required by the project.

---

*Note: All data ingested into the system is stored without modifying the original raw files. Processing and visualization steps are documented in the respective metadata sidecar files.*
