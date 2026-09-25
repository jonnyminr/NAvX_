# ANTARCTIC NAV-X V5 — Precision Trajectory Upgrade

## What changed

The earlier UI could imply more positional accuracy than the source/model supported. V5 changes both the trajectory engine and the way results are displayed.

### Antarctic iceberg trajectory

1. **Official observation origin** — the latest USNIC position remains the only observed start point. USNIC publishes named Antarctic iceberg positions weekly; the public table provides a date but not an observation time.
2. **Date-aware nowcast** — NAV-X now propagates the official fix from its reported date to the present instead of treating an older weekly fix as if it were a live GPS position. For computation, a date-only USNIC fix is placed at 12:00 UTC and the ±12 h timing ambiguity is propagated through the model ensemble.
3. **Fresh, time-varying forcing** — online mode uses Open-Meteo marine current guidance and ECMWF wind guidance, with the local CMEMS/ERA5 cache as a clearly labelled fallback.
4. **Two-pass spatial refinement** — a provisional drift path is generated first. Current/wind guidance is then sampled at control points along that path and the forecast is re-integrated.
5. **Smooth forcing interpolation** — forcing is interpolated in time and blended between adjacent path-control points. This removes discontinuities caused by nearest-neighbour switching.
6. **Observed-motion assimilation** — if two or more distinct archived USNIC fixes exist for the selected iceberg, NAV-X estimates recent observed mean drift and uses it only as a decaying residual correction. Segment-to-segment variability widens the model spread.
7. **1-hour Heun predictor/corrector integration** — the forecast uses start/end forcing each step instead of a single constant vector for 72 hours.
8. **48-member sensitivity ensemble** — the ensemble perturbs source-coordinate quantization, ±12 h observation-time ambiguity, current scaling, windage and the observed-motion residual. The UI reports P50/P90 radial spread plus along-track and cross-track P90 spread.
9. **No false decimal precision** — model coordinates are displayed at 0.01° and always alongside model spread. The official observation is displayed using the precision actually printed by USNIC.
10. **Official-fix history** — when archived official USNIC snapshots are available, the UI shows the previous fix and draws the real historical fix path separately from the model nowcast and forecast.

## Accuracy statement

This is a materially better numerical and data-assimilation architecture than the old constant-vector baseline, but it is **not a certified iceberg forecast and the P90 spread is not a statistically calibrated probability interval**. A scientifically defensible claim of absolute trajectory accuracy would require validation against a sufficiently large set of withheld historical iceberg tracks.

Open-Meteo's marine current guidance is approximately 0.08° (~8 km) and explicitly warns that coastal accuracy is limited. NAV-X therefore does not display sub-kilometre forecast certainty.

## API additions

- `GET /api/data/icebergs/{iceberg_id}/history`
- `GET /api/environmental/precision-sample`
- upgraded `POST /api/prediction/trajectory`

The trajectory response now includes `nowcast`, `motion_assimilation`, `precision_budget`, `forcing`, `quality`, `spread_p50_km`, `spread_p90_km`, `along_track_p90_km`, and `cross_track_p90_km`.
