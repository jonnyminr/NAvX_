# Navigation Intelligence & Hazard Analysis

## 1. Overview
The SIH 2026 Navigation Intelligence module transforms raw physical drift predictions into operational spatiotemporal analysis for vessel routing.

## 2. Spatiotemporal Collision Risk
Unlike static distance checks, the `SpatiotemporalHazardAnalyzer` calculates the Time-to-Closest-Approach (TCA) by interpolating both the vessel trajectory and the iceberg drift trajectory simultaneously.

1. **Vessel Propagation:** The planned route is broken down into time-stamped nodes based on the `speed_kmh`.
2. **Iceberg Interpolation:** For every vessel node, the corresponding iceberg position is linearly interpolated from its forecast horizons (e.g., between `+6h` and `+12h`).
3. **Effective Clearance:** The distance between the vessel and the iceberg is computed via Haversine, and the time-dependent `uncertainty_radius_km(t)` is subtracted to create the worst-case boundary.

## 3. Data Freshness
The `DataFreshnessChecker` validates the age of all environmental and observation data against the current UTC time. If any data exceeds the configurable `stale_threshold_hours` (default 48h), it triggers a `⚠ STALE DATA` warning, ensuring the decision support system never silently operates on outdated intelligence.

## 4. Limitations & Safety Disclaimer
This prototype is a research and decision-support system. It is not a certified maritime navigation system and does not replace qualified human judgment, official navigation products, or maritime safety procedures.
