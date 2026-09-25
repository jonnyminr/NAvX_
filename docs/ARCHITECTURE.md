# SYSTEM ARCHITECTURE

## 1. Overview
The Antarctic Navigation Decision Support System is designed as a decoupled, multi-tier application separating data ingestion, physical/statistical modeling, dynamic routing, and user interface.

## 2. Directory Structure

```text
/sih2026-antarctic-nav
│
├── data/                    # Managed via external volumes in production
│   ├── raw/                 # Original, unmodified datasets (GeoTIFFs, NetCDF, CSV)
│   ├── processed/           # Cleaned, standardized arrays for model input
│   ├── cache/               # Tile caches for mapping
│   ├── metadata/            # Source provenance and processing logs
│   └── simulation/          # Hypothetical datasets for "What-If" mode
│
├── docs/                    # Architecture, Data Sources, API definitions
│
├── src/                     # Core application logic
│   ├── data_ingestion/      # Scripts to pull NSIDC, USNIC, Copernicus data
│   ├── ml_engine/           # Sea-ice & iceberg prediction models
│   ├── risk_engine/         # Dynamic spatial risk cost calculations
│   ├── routing_engine/      # Dijkstra/A* geospatial routing on Polar Stereographic
│   ├── api/                 # FastAPI backend
│   └── frontend/            # React/Next.js mapping UI
│
├── tests/                   # Unit & integration testing
│
└── .env.example             # Configuration templates
```

## 3. Component Details

### A. Data Ingestion Tier
*   **Role:** Nightly/Hourly cron jobs fetching official data.
*   **Technologies:** Python, `requests`, `urllib`, `xarray`, `rasterio`.
*   **Rule:** Never overwrites or modifies `data/raw`.

### B. Future Statistical Correction Layer
*   **Role:** Predicts T+24 to T+168 hours of sea-ice concentration and iceberg trajectories.
*   **Technologies:** PyTorch/TensorFlow, Scikit-learn.
*   **Models:** Spatiotemporal ConvLSTM (Sea Ice) / Kalman + MLP (Icebergs).

### C. Geospatial Risk Engine
*   **Role:** Fuses data layers onto a standardized Antarctic polar stereographic grid.
*   **Technologies:** PostGIS / Spatialite, GeoPandas.
*   **Output:** Dynamic cost map where Cost = $f(\text{ice}, \text{iceberg\_proximity}, \text{vessel\_ice\_class})$.

### D. Routing Engine
*   **Role:** Calculates safest, fastest, and most fuel-efficient routes.
*   **Technologies:** Python `networkx` or custom A* with Haversine/Geodesic distance heuristics.

### E. Backend API
*   **Role:** Serves model outputs and routes to the frontend.
*   **Technologies:** FastAPI, Pydantic, Uvicorn.

### F. Frontend Dashboard
*   **Role:** High-performance web map for scientists and maritime operators.
*   **Technologies:** React, Next.js, Mapbox GL JS / Deck.gl (configured for polar projections if supported, or reprojection handled).

## 4. Security & Deployment
*   No raw data committed to the repo.
*   No secrets/API keys hardcoded.
*   `.env` configured separately for development and production.
