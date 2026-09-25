# ANTARCTIC NAV-X — AI / ML Setup and Training

This build adds AI/ML **without a database**. It keeps the existing real-data rules: official observations remain observations, future points remain model outputs, and missing data is never filled with invented vessels, icebergs, currents, wind, or accuracy values.

## What is implemented

1. **NAVX-DRIFT-ML-v1.0** — a physics-informed Random Forest residual model. The physical baseline is `ocean current + windage × wind`; ML learns only the residual velocity from archived official USNIC transitions. Runtime activation is gated by held-out validation against the physics-only baseline.
2. **Physics + ML iceberg forecast integration** — the ML residual prior is added conservatively to the existing observation-assimilated trajectory model. Direct observed USNIC motion gets higher priority when it exists.
3. **Structured NAV-X AI Decision Layer** — converts current route, CPA/TCA, iceberg-risk and model evidence into a deterministic recommendation report. It uses no external LLM and never fills missing measurements.
4. **AIS anomaly ML pipeline** — an Isolation Forest trainer/inference layer. It deliberately remains untrained until enough genuine AIS observations have been collected. No synthetic AIS training data is generated.
5. **AI Decision Center frontend page** — shows model version, real training-sample count, held-out endpoint MAE, validation gate, route recommendation evidence, quantified trade-offs, route comparison, and AIS anomaly status.

## Included iceberg model

The ZIP includes a trained `models/ml/iceberg_residual_rf.joblib` generated only from the archived USNIC snapshots already bundled in this project plus cached CMEMS/ERA5 forcing.

The model card is stored at:

`models/ml/iceberg_residual_model_card.json`

The card contains the exact training files, sample count, validation method, physics baseline endpoint MAE, hybrid endpoint MAE, and whether the runtime validation gate passed.

**Important:** these are research/prototype metrics on the available archived transitions, not certified maritime-navigation accuracy.

## Train / retrain the iceberg model

From the project root with the virtual environment activated:

```powershell
python -m src.ml.train_all --only iceberg
```

The trainer automatically reads every archived official file matching:

`data/raw/usnic_icebergs_*.csv`

It then samples the cached real scientific forcing from:

- `data/raw/ocean_currents_offline.nc` — CMEMS ocean-current cache
- `data/raw/era5_antarctic_*.nc` — ECMWF ERA5 wind cache

No synthetic samples are added. As you archive more official USNIC snapshots, retraining automatically creates more real transition samples.

## Train everything available

```powershell
python -m src.ml.train_all
```

This trains the iceberg model and attempts the AIS anomaly model. If genuine AIS training data is insufficient, AIS training is **skipped**, not fabricated.

## Collect genuine AIS samples for anomaly training

1. Configure your real AIS provider in `.env` and run NAV-X.
2. While the server is receiving genuine AIS messages, open a second terminal with the same venv activated.
3. Run:

```powershell
python -m src.ml.collect_ais_training
```

This reads only the vessels currently returned by your local NAV-X AIS API and appends them to:

`data/live/ais_ml_training.csv`

Run the collector at different times so the file contains many genuine observations. When at least 100 valid samples exist, train with:

```powershell
python -m src.ml.train_all --only ais
```

The model will be written to:

`models/ml/ais_isolation_forest.joblib`

An AIS anomaly means only that the feature pattern is statistically unusual compared with the genuine training set. It is **not** a claim that a vessel is dangerous or acting maliciously.

## Run NAV-X

```powershell
python -m src.api.main
```

Open:

`http://localhost:8000/app/`

Then choose **AI Decision Center** from the sidebar.

## Useful API checks

- `http://localhost:8000/api/ai/status`
- `http://localhost:8000/api/system/health`
- `http://localhost:8000/api/model/evaluation`

## SIH explanation

A concise technical explanation for judges:

> NAV-X uses a hybrid physics-informed ML model. Ocean current and wind produce the physical iceberg-drift baseline. A Random Forest learns the residual error using only archived official USNIC position transitions and real cached CMEMS/ERA5 forcing. The ML correction is activated only if held-out validation improves on the physics-only baseline. Forecasts then feed the time-aware Polar A* hazard costs, while the structured explainability layer compares actual route metrics and exposes the recommendation, evidence and trade-offs without generating unsupported claims.
