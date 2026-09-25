from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np

AIS_FEATURES = ["sog_knots", "sin_cog", "cos_cog", "sin_heading", "cos_heading", "abs_turn_proxy"]


def vessel_feature(v: dict[str, Any]) -> list[float] | None:
    try:
        sog = float(v.get("sog_knots"))
        cog = float(v.get("cog_deg")) if v.get("cog_deg") is not None else float(v.get("heading_deg"))
        hdg = float(v.get("heading_deg")) if v.get("heading_deg") is not None else cog
        if not all(math.isfinite(x) for x in (sog, cog, hdg)):
            return None
        # Standard AIS unavailable / invalid ranges are rejected instead of being
        # interpreted as genuine vessel behaviour.
        if sog < 0 or sog > 102.2 or cog < 0 or cog > 360 or hdg < 0 or hdg > 360:
            return None
        cr, hr = math.radians(cog), math.radians(hdg)
        turn_proxy = abs(((cog - hdg + 180.0) % 360.0) - 180.0) / 180.0
        return [sog / 30.0, math.sin(cr), math.cos(cr), math.sin(hr), math.cos(hr), turn_proxy]
    except (TypeError, ValueError):
        return None


class AISAnomalyML:
    """Runtime wrapper for the real-AIS Isolation Forest.

    The model is never trained from synthetic vessels. The object watches the
    on-disk model files so a model trained automatically by the scheduler becomes
    active without restarting FastAPI.
    """

    def __init__(self, project_root: Path | None = None):
        self.root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        self.model_path = self.root / "models" / "ml" / "ais_isolation_forest.joblib"
        self.card_path = self.root / "models" / "ml" / "ais_anomaly_model_card.json"
        self.model = None
        self.card: dict[str, Any] = {}
        self._model_mtime: float | None = None
        self._card_mtime: float | None = None
        self._reload(force=True)

    def _reload(self, force: bool = False) -> None:
        try:
            model_mtime = self.model_path.stat().st_mtime if self.model_path.exists() else None
            card_mtime = self.card_path.stat().st_mtime if self.card_path.exists() else None
            changed = force or model_mtime != self._model_mtime or card_mtime != self._card_mtime
            if not changed:
                return
            self.card = {}
            if self.card_path.exists():
                self.card = json.loads(self.card_path.read_text(encoding="utf-8"))
            self.model = joblib.load(self.model_path) if self.model_path.exists() else None
            self._model_mtime = model_mtime
            self._card_mtime = card_mtime
        except Exception as exc:
            self.model = None
            self.card = {"status": "LOAD_ERROR", "error": str(exc)}

    def _real_data_counts(self) -> tuple[int, int, int]:
        try:
            from sqlalchemy import func, select
            from src.db.database import SessionLocal
            from src.db.models import VesselPosition

            with SessionLocal() as db:
                raw_rows = int(db.scalar(select(func.count()).select_from(VesselPosition)) or 0)
                sample_rows = list(db.scalars(select(VesselPosition).order_by(VesselPosition.received_at.desc()).limit(5000)).all())
            valid = 0
            vessels = set()
            for r in sample_rows:
                payload = {
                    "mmsi": r.mmsi,
                    "sog_knots": r.sog_knots,
                    "cog_deg": r.cog_deg,
                    "heading_deg": r.heading_deg,
                }
                if vessel_feature(payload) is not None:
                    valid += 1
                    vessels.add(str(r.mmsi))
            return raw_rows, valid, len(vessels)
        except Exception:
            return 0, 0, 0

    @property
    def available(self) -> bool:
        self._reload()
        return self.model is not None

    def public_status(self) -> dict[str, Any]:
        self._reload()
        raw_rows, valid_rows, vessels = self._real_data_counts()
        minimum = max(20, int(os.getenv("AIS_ANOMALY_MIN_SAMPLES", "30")))
        trained = self.model is not None
        if trained:
            status = "ACTIVE_REAL_AIS_MODEL"
        elif valid_rows >= minimum:
            status = "READY_FOR_AUTOMATIC_TRAINING"
        else:
            status = "COLLECTING_REAL_AIS_DATA"
        return {
            "name": "NAVX-AIS-ANOMALY",
            "type": "Isolation Forest",
            "status": status,
            "trained": trained,
            "training_samples": self.card.get("training_samples", 0),
            "real_database_samples": raw_rows,
            "valid_training_samples": valid_rows,
            "unique_vessels": vessels,
            "minimum_required": minimum,
            "trained_at": self.card.get("trained_at"),
            "model_version": self.card.get("model_version", "NAVX-AIS-ML-untrained"),
            "features": AIS_FEATURES,
            "note": self.card.get(
                "note",
                f"NAV-X is collecting genuine AIS observations automatically ({valid_rows}/{minimum} valid training samples; {raw_rows} total stored AIS positions). No synthetic vessel samples are used.",
            ),
        }

    def score_many(self, vessels: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        self._reload()
        vessels = list(vessels)
        if self.model is None:
            return []
        rows, src = [], []
        for v in vessels:
            f = vessel_feature(v)
            if f is not None:
                rows.append(f)
                src.append(v)
        if not rows:
            return []
        X = np.asarray(rows, dtype=float)
        labels = self.model.predict(X)
        scores = self.model.decision_function(X)
        out = []
        for v, label, score in zip(src, labels, scores):
            out.append({
                "mmsi": v.get("mmsi"),
                "name": v.get("name"),
                "anomaly": bool(int(label) == -1),
                "anomaly_score": round(float(-score), 5),
                "label": "UNUSUAL_MOVEMENT_PATTERN" if int(label) == -1 else "WITHIN_TRAINED_PATTERN",
                "source": v.get("source", "AIS"),
                "last_seen_utc": v.get("last_seen_utc"),
                "interpretation": "Statistical movement-pattern anomaly only; not a declaration of danger or intent.",
            })
        return out
