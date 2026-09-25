# USNIC Antarctic Iceberg Data

## 1. Overview
The United States National Ice Center (USNIC) tracks Antarctic icebergs that meet minimum size criteria (usually 20 square nautical miles or greater, or 10 nautical miles on the longest axis). This dataset serves as the definitive observational ground truth for large maritime hazards in the Southern Ocean.

## 2. Dataset Specifications

*   **Source:** U.S. National Ice Center (USNIC)
*   **Official URL:** [https://usicecenter.gov/Products/AntarcIcebergs](https://usicecenter.gov/Products/AntarcIcebergs)
*   **Access Method:** Direct CSV download endpoint (`/File/DownloadCurrent?pId=134`)
*   **File Format:** CSV (Comma-Separated Values)
*   **Fields:** 
    *   `Iceberg`: Unique Alphanumeric ID (e.g., A76C) based on quadrant of origin and sequential number.
    *   `Length (NM)`: Length of the iceberg in nautical miles.
    *   `Width (NM)`: Width of the iceberg in nautical miles.
    *   `Latitude`: Decimal degrees (negative for southern hemisphere).
    *   `Longitude`: Decimal degrees (negative for west, positive for east).
    *   `Area (sqMI)`: Area in square statute miles.
    *   `Area (sqNM)`: Area in square nautical miles.
    *   `Area (sqKM)`: Area in square kilometers.
    *   `Last Update`: Date the iceberg was last observed/tracked (MM/DD/YYYY).
*   **Units:** Nautical Miles (NM) for dimensions, Decimal Degrees for coordinates, sqKM/sqNM for area.
*   **Coordinate System:** WGS 84 (EPSG:4326) for raw data. Reprojected to Antarctic Polar Stereographic (EPSG:3412) in the processed pipeline.
*   **Update Frequency:** Weekly.
*   **Historical Coverage:** Active icebergs currently tracked. (Archive endpoints exist but are excluded for the MVP per Phase 2 scope).
*   **Known Limitations:** 
    *   Only tracks large icebergs (> 10 NM). Smaller fragments ("bergy bits" and "growlers") are not included but represent significant navigational risks.
    *   Position data is updated weekly; an iceberg's true position between updates will vary due to drift.

## 3. Ingestion Pipeline
1.  **Download:** Automated HTTP GET to the USNIC endpoint.
2.  **Raw Storage:** Preserved exactly as downloaded in `/data/raw/usnic_icebergs_<date>.csv`.
3.  **Validation:** Coordinates checked for Antarctic bounds (`Latitude < -50`). Timestamps validated.
4.  **Transformation:** Normalized into GeoJSON with points reprojected to `EPSG:3412`.
5.  **Output:** Processed file stored in `/data/processed/icebergs.geojson`.
