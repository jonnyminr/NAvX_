from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from .scientific_features import FEATURE_NAMES, feature_vector


class IcebergResidualML:
    """Physics-informed residual ML correction for iceberg drift.

    The model predicts east/north *residual velocity* relative to the physical
    baseline (ocean current + windage).  It never predicts or invents an
    observation.  Runtime use is gated by the model card generated from
    held-out official-USNIC transitions.
    """

    def __init__(self, project_root: Path | None = None):
        root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        self.model_path = root / "models" / "ml" / "iceberg_residual_rf.joblib"
        self.card_path = root / "models" / "ml" / "iceberg_residual_model_card.json"
        self.model = None
        self.card: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.card_path.exists():
                self.card = json.loads(self.card_path.read_text(encoding="utf-8"))
            if self.model_path.exists():
                self.model = joblib.load(self.model_path)
        except Exception as exc:
            self.model = None
            self.card = {"status": "LOAD_ERROR", "error": str(exc)}

    @property
    def available(self) -> bool:
        return self.model is not None

    @property
    def runtime_enabled(self) -> bool:
        return bool(self.available and self.card.get("runtime_enabled"))

    def public_status(self) -> dict[str, Any]:
        metrics = self.card.get("validation") or {}
        return {
            "name": "NAVX-DRIFT-ML",
            "type": "RandomForest residual regression + physics baseline",
            "status": "ACTIVE" if self.runtime_enabled else ("TRAINED_VALIDATION_GATE_HOLD" if self.available else "NOT_TRAINED"),
            "trained": self.available,
            "runtime_enabled": self.runtime_enabled,
            "training_samples": self.card.get("training_samples", 0),
            "official_sources": self.card.get("official_sources", []),
            "features": self.card.get("feature_names", FEATURE_NAMES),
            "validation": metrics,
            "trained_at": self.card.get("trained_at"),
            "model_version": self.card.get("model_version", "NAVX-DRIFT-ML-untrained"),
            "note": self.card.get("note", "Train with python -m src.ml.train_all. Runtime activation requires held-out improvement over the physics baseline."),
        }

    def predict_residual(self, *, lat: float, lon: float, length_nm: float | None,
                         width_nm: float | None, area_sqkm: float | None,
                         ocean_u: float, ocean_v: float, wind_u: float, wind_v: float) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "applied": False, "reason": "ML model is not trained."}
        forcing = {"ocean_u": ocean_u, "ocean_v": ocean_v, "wind_u": wind_u, "wind_v": wind_v}
        x = np.asarray([feature_vector(lat, lon, length_nm, width_nm, area_sqkm, forcing)], dtype=float)
        pred = np.asarray(self.model.predict(x), dtype=float).reshape(-1)
        u, v = float(pred[0]), float(pred[1])
        # Guard against an out-of-distribution model producing an extreme prior.
        speed = math.hypot(u, v)
        if speed > 0.75:
            scale = 0.75 / speed
            u *= scale; v *= scale
        return {
            "available": True,
            "applied": self.runtime_enabled,
            "residual_u_ms": u,
            "residual_v_ms": v,
            "residual_speed_ms": math.hypot(u, v),
            "model_version": self.card.get("model_version", "NAVX-DRIFT-ML"),
            "validation_gate": "PASS" if self.runtime_enabled else "HOLD",
            "trained_at": self.card.get("trained_at"),
        }
