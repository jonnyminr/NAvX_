# Antarctic Navigation Risk Engine

## 1. Overview
The Risk Engine (`NavigationRiskEngine`) evaluates spatial intersections between a planned vessel route and the predicted uncertainty corridors of drifting icebergs.

## 2. Risk Classification
We reject opaque "probability" metrics in favor of transparent, deterministic distance thresholds:
- **CRITICAL (🔴):** <= 10.0 km clearance (Iceberg uncertainty cone directly intersects or is critically close to the route). Imminent collision risk.
- **HIGH (🟠):** <= 25.0 km clearance.
- **MODERATE (🟡):** <= 50.0 km clearance. Heightened monitoring advised.
- **LOW (🟢):** > 50.0 km clearance. Safe passage.

## 3. Calculation Methodology
1. Takes an array of route coordinates `[ {lat, lon}, ... ]`.
2. Iterates over the predicted iceberg trajectory points for various forecast horizons.
3. Computes the Haversine distance between each route node and trajectory node.
4. Subtracts the iceberg's `uncertainty_radius_km` from the raw distance to yield the **Effective Clearance Distance**.
5. The minimum effective clearance distance determines the global risk level for that route segment.
