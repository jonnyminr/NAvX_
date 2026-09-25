# Navigation Decision Support System

## 1. Objective
To convert abstract scientific predictions into actionable intelligence for vessel captains and SIH evaluators.

## 2. API Endpoints
- **`POST /api/prediction/trajectory`**
  Input: Current iceberg position and local environmental forcing (ocean_u, ocean_v, wind_u, wind_v).
  Output: 6h-72h trajectory nodes, velocities, and uncertainty radius.
- **`POST /api/navigation/risk`**
  Input: Planned vessel route array and iceberg trajectory prediction.
  Output: Risk classification, exact clearance distance, and explainable recommendation string.

## 3. Explainable Recommendations
The engine does not just flag danger; it advises action.
- If **CRITICAL/HIGH**, the system outputs an exact deviation radius (e.g., `"Deviation recommended: Shift route 15.2 km away from intersection"`).
- If **MODERATE/LOW**, it advises radar vigilance or confirms route safety.

## 4. Visual Dashboard Integration (Phase 5.8 Prototype Support)
The API JSON payloads are structured to directly feed frontend mapping libraries (e.g., Leaflet or Deck.gl).
- **Iceberg Tracks:** Rendered as PolyLines.
- **Uncertainty Corridors:** Rendered as buffered Polygons or scaled Circles around future nodes.
- **Risk Zones:** Heatmap or colored routing lines based on the threshold intersection.
