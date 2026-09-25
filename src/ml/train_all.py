from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.model_selection import KFold, cross_val_predict

from .ais_anomaly import AIS_FEATURES, vessel_feature
from .scientific_features import (
    FEATURE_NAMES, WINDAGE, build_real_transition_dataset,
    destination_from_velocity, haversine_km,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MODEL_DIR = ROOT / "models" / "ml"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def _mean(values):
    return float(np.mean(values)) if values else None


def train_iceberg() -> dict:
    X, y, meta = build_real_transition_dataset(DATA)
    if len(X) < 12:
        result = {
            "status": "SKIPPED_INSUFFICIENT_REAL_DATA",
            "training_samples": int(len(X)),
            "minimum_required": 12,
            "note": "At least 12 valid official USNIC transitions with real forcing are required. No synthetic samples are generated.",
        }
        print(json.dumps(result, indent=2)); return result

    base = RandomForestRegressor(
        n_estimators=350, max_depth=6, min_samples_leaf=2,
        max_features=0.85, random_state=42, n_jobs=-1,
    )
    folds = min(5, max(3, len(X)//6))
    cv = KFold(n_splits=folds, shuffle=True, random_state=42)
    pred = cross_val_predict(base, X, y, cv=cv, n_jobs=-1)

    physics_errors, hybrid_errors = [], []
    for row, residual in zip(meta, pred):
        dt_h = float(row["dt_hours"])
        p_lat, p_lon = destination_from_velocity(
            row["start_lat"], row["start_lon"], row["physics_u_ms"], row["physics_v_ms"], dt_h,
        )
        h_lat, h_lon = destination_from_velocity(
            row["start_lat"], row["start_lon"],
            row["physics_u_ms"] + float(residual[0]),
            row["physics_v_ms"] + float(residual[1]), dt_h,
        )
        physics_errors.append(haversine_km(p_lat, p_lon, row["end_lat"], row["end_lon"]))
        hybrid_errors.append(haversine_km(h_lat, h_lon, row["end_lat"], row["end_lon"]))

    physics_mae = _mean(physics_errors)
    hybrid_mae = _mean(hybrid_errors)
    runtime_enabled = bool(hybrid_mae is not None and physics_mae is not None and hybrid_mae < physics_mae and len(X) >= 20)

    base.fit(X, y)
    model_path = MODEL_DIR / "iceberg_residual_rf.joblib"
    joblib.dump(base, model_path)

    sources = sorted({f for row in meta for f in row.get("source_files", [])})
    card = {
        "status": "TRAINED",
        "model_version": "NAVX-DRIFT-ML-v1.0",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "RandomForestRegressor multi-output residual velocity",
        "scikit_learn_version": sklearn.__version__,
        "training_samples": int(len(X)),
        "feature_names": FEATURE_NAMES,
        "official_sources": sources,
        "forcing_sources": ["cached CMEMS ocean currents", "cached ECMWF ERA5 10 m wind"],
        "target": "observed USNIC drift velocity minus physics baseline velocity",
        "validation": {
            "method": f"{folds}-fold shuffled held-out cross-validation over official transitions",
            "physics_endpoint_mae_km": round(float(physics_mae), 3),
            "hybrid_endpoint_mae_km": round(float(hybrid_mae), 3),
            "improvement_percent": round((physics_mae-hybrid_mae)/physics_mae*100.0, 2) if physics_mae else None,
            "sample_count": int(len(X)),
            "certified_navigation_accuracy": False,
        },
        "runtime_enabled": runtime_enabled,
        "activation_rule": "Only activate when held-out hybrid endpoint MAE beats the physics baseline and >=20 real transitions exist.",
        "note": "Exploratory SIH research model trained only on archived official USNIC fixes and cached scientific forcing. Small datasets limit generalization; this is not certified navigation accuracy.",
    }
    (MODEL_DIR / "iceberg_residual_model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print("Iceberg ML model trained")
    print(json.dumps(card, indent=2))
    return card


def _load_real_ais_training() -> list[dict]:
    """Load genuine AIS samples from both the persistent DB and legacy CSV cache."""
    rows: list[dict] = []
    seen = set()

    # Primary source: persistent live AIS observations collected by the scheduler.
    try:
        from sqlalchemy import select
        from src.db.database import SessionLocal
        from src.db.models import VesselPosition

        with SessionLocal() as db:
            db_rows = list(db.scalars(select(VesselPosition).order_by(VesselPosition.received_at)).all())
        for r in db_rows:
            key = (str(r.provider), str(r.mmsi), r.received_at.isoformat() if r.received_at else "")
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "mmsi": r.mmsi,
                "name": r.name,
                "sog_knots": r.sog_knots,
                "cog_deg": r.cog_deg,
                "heading_deg": r.heading_deg,
                "lat": r.latitude,
                "lon": r.longitude,
                "last_seen_utc": r.received_at.isoformat() if r.received_at else None,
                "source": r.provider,
            })
    except Exception:
        pass

    # Backward-compatible genuine AIS CSVs, if the operator previously collected them.
    candidates = [DATA / "live" / "ais_ml_training.csv", DATA / "live" / "ais_training.csv"]
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                key = (str(r.get("source") or "AIS"), str(r.get("mmsi") or ""), str(r.get("last_seen_utc") or ""))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(dict(r))
    return rows


def train_ais(force: bool = True) -> dict:
    raw = _load_real_ais_training()
    valid = []
    vessel_ids = set()
    for r in raw:
        f = vessel_feature(r)
        if f is None:
            continue
        valid.append(f)
        if r.get("mmsi"):
            vessel_ids.add(str(r.get("mmsi")))
    X = np.asarray(valid, dtype=float)
    minimum = max(20, int(__import__("os").getenv("AIS_ANOMALY_MIN_SAMPLES", "30")))
    min_vessels = max(1, int(__import__("os").getenv("AIS_ANOMALY_MIN_VESSELS", "2")))
    if len(X) < minimum or len(vessel_ids) < min_vessels:
        result = {
            "status": "COLLECTING_REAL_AIS_DATA",
            "training_samples": int(len(X)),
            "minimum_required": minimum,
            "unique_vessels": int(len(vessel_ids)),
            "minimum_vessels": min_vessels,
            "note": "NAV-X is collecting genuine AIS positions automatically. No simulated vessels are created for ML training.",
        }
        print(json.dumps(result, indent=2)); return result

    card_path = MODEL_DIR / "ais_anomaly_model_card.json"
    model_path = MODEL_DIR / "ais_isolation_forest.joblib"
    if not force and card_path.exists() and model_path.exists():
        try:
            old = json.loads(card_path.read_text(encoding="utf-8"))
            old_n = int(old.get("training_samples") or 0)
            growth_needed = max(10, int(max(old_n, 1) * 0.10))
            if len(X) < old_n + growth_needed:
                return {
                    "status": "ACTIVE_REAL_AIS_MODEL",
                    "trained": False,
                    "training_samples": old_n,
                    "available_real_samples": int(len(X)),
                    "note": "Existing real-AIS model retained until enough new genuine observations accumulate.",
                }
        except Exception:
            pass

    model = IsolationForest(n_estimators=300, contamination="auto", random_state=42, n_jobs=-1)
    model.fit(X)
    joblib.dump(model, model_path)
    card = {
        "status": "TRAINED",
        "model_version": "NAVX-AIS-ML-v1.1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "IsolationForest",
        "scikit_learn_version": sklearn.__version__,
        "training_samples": int(len(X)),
        "unique_vessels": int(len(vessel_ids)),
        "features": AIS_FEATURES,
        "training_source": "Persistent real AIS database + genuine AIS CSV cache only",
        "note": "Unsupervised statistical anomaly detector trained only on genuine received AIS samples. An anomaly is not a danger/intent classification.",
    }
    card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    print("AIS anomaly model trained")
    print(json.dumps(card, indent=2))
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NAV-X ML components from real archived/provider data only.")
    parser.add_argument("--only", choices=["iceberg", "ais", "all"], default="all")
    args = parser.parse_args()
    summary = {}
    if args.only in ("iceberg", "all"): summary["iceberg"] = train_iceberg()
    if args.only in ("ais", "all"): summary["ais"] = train_ais()
    (MODEL_DIR / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
