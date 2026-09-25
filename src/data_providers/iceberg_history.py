"""Historical USNIC iceberg position utilities for trajectory assimilation.

The public USNIC iceberg table is periodic/weekly, so NAV-X never treats the
source position as continuous GPS telemetry.  This module reconstructs a small
observation history from archived CSV snapshots already present in the project
and from live snapshots saved by the USNIC refresh task.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

R_EARTH_KM = 6371.0088


def _parse_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            # USNIC table exposes a date, not an observation time.  Midday UTC
            # minimizes the maximum timing error to roughly +/-12 hours.
            d = datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            return d.replace(hour=12)
        except ValueError:
            continue
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class IcebergObservation:
    iceberg_id: str
    timestamp: datetime
    lat: float
    lon: float
    source_file: str


def _enu_velocity(a: IcebergObservation, b: IcebergObservation) -> tuple[float, float]:
    """Approximate east/north velocity in m/s over one observed segment."""
    dt = (b.timestamp - a.timestamp).total_seconds()
    if dt <= 0:
        return 0.0, 0.0
    mean_lat = math.radians((a.lat + b.lat) / 2.0)
    dlat = math.radians(b.lat - a.lat)
    dlon_deg = ((b.lon - a.lon + 180.0) % 360.0) - 180.0
    dlon = math.radians(dlon_deg)
    north_m = dlat * R_EARTH_KM * 1000.0
    east_m = dlon * math.cos(mean_lat) * R_EARTH_KM * 1000.0
    return east_m / dt, north_m / dt


def load_history(data_root: Path, iceberg_id: str) -> List[IcebergObservation]:
    """Load distinct dated positions from archived official CSV snapshots."""
    data_root = Path(data_root)
    files = list((data_root / "raw").glob("usnic_icebergs_*.csv"))
    live = data_root / "live" / "usnic_current.csv"
    if live.exists():
        files.append(live)

    points: dict[tuple[str, float, float], IcebergObservation] = {}
    target = str(iceberg_id).strip().upper()
    for path in files:
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh):
                    rid = str(row.get("Iceberg") or row.get("id") or "").strip().upper()
                    if rid != target:
                        continue
                    lat = _to_float(row.get("Latitude", row.get("lat")))
                    lon = _to_float(row.get("Longitude", row.get("lon")))
                    ts = _parse_date(row.get("Last Update") or row.get("date_observed"))
                    if lat is None or lon is None or ts is None:
                        continue
                    obs = IcebergObservation(target, ts, lat, lon, path.name)
                    points[(ts.date().isoformat(), round(lat, 6), round(lon, 6))] = obs
        except Exception:
            continue

    return sorted(points.values(), key=lambda p: p.timestamp)


def estimate_recent_motion(data_root: Path, iceberg_id: str, max_segment_days: float = 28.0) -> dict:
    """Estimate recent observed drift using robust median segment velocity.

    The result is only used as a short-range residual correction.  It is not
    advertised as measured instantaneous iceberg velocity.
    """
    obs = load_history(data_root, iceberg_id)
    if len(obs) < 2:
        return {
            "available": False,
            "history_points": len(obs),
            "note": "At least two distinct dated USNIC snapshots are required for motion assimilation.",
        }

    segments = []
    for a, b in zip(obs[:-1], obs[1:]):
        days = (b.timestamp - a.timestamp).total_seconds() / 86400.0
        if 0 < days <= max_segment_days:
            u, v = _enu_velocity(a, b)
            speed = math.hypot(u, v)
            # Filter implausible gross parsing jumps; large Antarctic tabular
            # icebergs generally drift well below this speed.
            if speed <= 2.0:
                segments.append((u, v, a, b))

    if not segments:
        return {
            "available": False,
            "history_points": len(obs),
            "note": "No recent valid USNIC motion segment was available.",
        }

    # Use up to the three most recent segments and component-wise median to
    # reduce sensitivity to one anomalous weekly fix.
    recent = segments[-3:]
    us = sorted(s[0] for s in recent)
    vs = sorted(s[1] for s in recent)
    mid = len(recent) // 2
    if len(recent) % 2:
        u = us[mid]
        v = vs[mid]
    else:
        u = 0.5 * (us[mid - 1] + us[mid])
        v = 0.5 * (vs[mid - 1] + vs[mid])
    speed = math.hypot(u, v)
    bearing = (math.degrees(math.atan2(u, v)) + 360.0) % 360.0 if speed else 0.0
    # Robust segment-to-segment spread. This is not a formal measurement error;
    # it is used only to widen the perturbation ensemble when the observed
    # weekly motion itself has been inconsistent.
    component_residuals = [math.hypot(seg[0]-u, seg[1]-v) for seg in recent]
    motion_scatter = sorted(component_residuals)[len(component_residuals)//2] if component_residuals else 0.0
    last = recent[-1]
    return {
        "available": True,
        "history_points": len(obs),
        "segments_used": len(recent),
        "u_ms": u,
        "v_ms": v,
        "speed_ms": speed,
        "bearing_deg": bearing,
        "motion_scatter_ms": motion_scatter,
        "segment_start": last[2].timestamp.isoformat(),
        "segment_end": last[3].timestamp.isoformat(),
        "last_observation_timestamp": obs[-1].timestamp.isoformat(),
        "note": "Derived from distinct dated USNIC table positions; used only as a decaying residual correction. Segment scatter widens model spread when recent motion is inconsistent.",
    }
