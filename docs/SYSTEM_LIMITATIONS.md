# System Limitations & Scientific Scope

To ensure absolute scientific integrity, Antarctic NAV-X acknowledges the following limitations:

1. **Not Certified:** This is not a certified maritime navigation product. It provides decision-support intelligence.
2. **Kinematic vs Dynamic:** The physics baseline is a kinematic interpolation model, not a fully coupled dynamical force-balance model.
3. **Statistical correction status:** The residual correction layer is architecturally complete but practically blocked pending the ingestion of the BYU historical database. The active system relies on the physics baseline.
4. **Heuristic Uncertainty:** Uncertainty is currently modelled geometrically (1km + 5% distance) rather than probabilistically calibrated against unseen historical residuals.
5. **Route Finding:** The alternative routing engine shifts waypoints laterally. It does not yet perform A* mesh optimization over bathymetry constraints.
6. **Data Freshness:** Environmental forcing relies on the timestamps of the cached `data/raw/` NetCDF files. Prolonged offline states will trigger `⚠ STALE DATA` warnings.
