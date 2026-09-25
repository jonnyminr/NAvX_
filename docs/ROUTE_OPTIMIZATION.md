# Route Optimization V9

## Objective

Generate three transparent Antarctic/Southern Ocean route profiles — **Fastest**, **Balanced**, and **Safest** — while accounting for the forecast location of nearby icebergs at the time the vessel is expected to reach each part of the route.

## Operational boundary

Routing is restricted to coordinates at or south of **45°S**. Browser GPS positions outside that boundary are displayed to the user but are not accepted as route origins.

## Geometry

- Geographic distance uses haversine great-circle distance.
- Candidate route segments are smoothed only when the straight geodesic segment remains outside the hard iceberg safety envelope.
- Final route segments are densified using spherical great-circle interpolation before vessel travel-time and CPA/TCA assessment.

## Time-aware iceberg cost

For each A* planning cell:

1. accumulated route distance is converted to vessel ETA using the configured vessel speed;
2. each nearby iceberg trajectory is interpolated to that same ETA;
3. the iceberg's forecast P90 uncertainty radius is combined with the operator safety buffer;
4. cells inside the profile hard buffer are blocked;
5. cells near the uncertainty envelope receive a smooth risk penalty.

This avoids treating all +6 h to +72 h forecast points as if they existed at the same time.

## Route profiles

- **Fastest**: distance-biased, lower risk penalty, still assessed after generation.
- **Balanced**: stronger forecast-risk penalty with moderate detour tolerance.
- **Safest**: largest hard buffer and strongest risk penalty.

## Recommendation

The recommendation is safety-tier-first: LOW-risk routes are preferred over MODERATE, HIGH, and CRITICAL routes. Within the safest available tier, the system compares modeled risk score, extra distance, and effective iceberg clearance.

## Limits

This is research and decision-support routing, not certified ECDIS, hydrographic route clearance, or autonomous marine navigation. It does not model every legal, bathymetric, meteorological, sea-ice, vessel-performance, traffic-separation, or charted restriction required for professional voyage planning.
