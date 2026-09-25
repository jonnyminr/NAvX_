# Data Provenance

Antarctic NAV-X strictly enforces data provenance tracking to ensure no synthetic data is passed off as real observation.

## 1. CMEMS Ocean Currents
*   **Provider:** Mercator Ocean International / Copernicus
*   **Product ID:** `GLOBAL_ANALYSISFORECAST_PHY_001_024`
*   **Variables:** `uo`, `vo`
*   **Status:** REAL DATA (Cached Offline)

## 2. ERA5 Wind
*   **Provider:** ECMWF / CDS
*   **Product ID:** `reanalysis-era5-single-levels`
*   **Variables:** `10u`, `10v`
*   **Status:** REAL DATA (Cached Offline)

## 3. NSIDC Sea Ice
*   **Provider:** National Snow and Ice Data Center
*   **Product ID:** `NSIDC-G02135`
*   **Variables:** `concentration`
*   **Status:** REAL DATA (Cached Offline)

## 4. USNIC Icebergs
*   **Provider:** U.S. National Ice Center
*   **Variables:** Current Coordinates, Sizes
*   **Status:** REAL DATA (Cached Offline Snapshot)

## Simulated Inputs
*   **Vessel Routes:** In SIH Demo Mode, the vessel routes are manually selected paths simulating an expedition for the purpose of demonstrating the hazard engine against the Real Data environment.
