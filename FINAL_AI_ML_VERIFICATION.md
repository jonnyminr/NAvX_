# ANTARCTIC NAV-X — AI/ML Build Verification

## Implemented

- Physics-informed Random Forest residual model for iceberg drift.
- Training dataset constructed only from archived official USNIC position transitions.
- Real cached CMEMS ocean-current and ECMWF/ERA5 wind features used for training.
- Runtime validation gate: ML correction is applied only when held-out endpoint error improves over the physics-only baseline and enough real samples exist.
- Existing +6h / +12h / +24h / +48h / +72h trajectory pipeline now carries explicit ML-correction metadata.
- Structured NAV-X AI Decision Layer for route recommendation, risk, CPA/TCA and evidence comparison.
- AIS Isolation Forest training/inference pipeline; training deliberately stays unavailable until genuine AIS samples are collected.
- New **AI Decision Center** frontend page with model evidence, route recommendation, trade-offs, comparison matrix and AIS anomaly monitor.
- No database added.

## Included real-data iceberg training result

The included model was trained from 32 valid official transition samples derived from the bundled USNIC archives.

Held-out validation recorded in the model card:

- Physics-only endpoint MAE: **106.339 km**
- Physics + ML endpoint MAE: **56.721 km**
- Relative reduction in this small held-out evaluation: **46.66%**
- Certified navigation accuracy: **No**

These figures are research/prototype results for the available archived sample set and must not be presented as universal accuracy.

## Integrity behavior

- Official observations are never replaced by model output.
- Missing scientific inputs remain unavailable.
- No synthetic iceberg or AIS observations are generated for training.
- AIS anomaly training is skipped when genuine sample count is insufficient.
- The decision layer refuses to issue a preferred route when route evidence is absent or insufficient.

## Verification

- Python syntax compilation: PASS
- Frontend JavaScript syntax check: PASS
- FastAPI `/app/` smoke test: HTTP 200
- FastAPI `/api/ai/status` smoke test: HTTP 200
- FastAPI `/api/ai/decision-support` smoke test: HTTP 200
- Legacy free-form AI question endpoint is absent from this build.
- Automated test suite: **70 passed**
