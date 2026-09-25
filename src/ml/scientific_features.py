from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

EARTH_KM = 6371.0088
WINDAGE = 0.018


def parse_usnic_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc, hour=12)
        except ValueError:
            continue
    return None


def _float(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def read_usnic_snapshot(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            iid = str(row.get("Iceberg") or row.get("id") or "").strip().upper()
            lat = _float(row.get("Latitude", row.get("lat")))
            lon = _float(row.get("Longitude", row.get("lon")))
            date = parse_usnic_date(row.get("Last Update") or row.get("date_observed"))
            if not iid or lat is None or lon is None or date is None:
                continue
            length_nm = _float(row.get("Length (NM)", row.get("length_nm")))
            width_nm = _float(row.get("Width (NM)", row.get("width_nm")))
            area_sqkm = _float(row.get("Area (sqKM)", row.get("area_sqkm")))
            out[iid] = {
                "iceberg_id": iid,
                "lat": lat,
                "lon": lon,
                "timestamp": date,
                "length_nm": length_nm,
                "width_nm": width_nm,
                "area_sqkm": area_sqkm,
                "source_file": Path(path).name,
            }
    return out


def enu_velocity(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float, float]:
    dt = (b["timestamp"] - a["timestamp"]).total_seconds()
    if dt <= 0:
        raise ValueError("Observation interval must be positive")
    mean_lat = math.radians((float(a["lat"]) + float(b["lat"])) / 2.0)
    dlat = math.radians(float(b["lat"]) - float(a["lat"]))
    dlon_deg = ((float(b["lon"]) - float(a["lon"]) + 180.0) % 360.0) - 180.0
    dlon = math.radians(dlon_deg)
    north_m = dlat * EARTH_KM * 1000.0
    east_m = dlon * math.cos(mean_lat) * EARTH_KM * 1000.0
    return east_m / dt, north_m / dt, dt / 3600.0


def destination_from_velocity(lat: float, lon: float, u_ms: float, v_ms: float, dt_hours: float) -> tuple[float, float]:
    dt_s = float(dt_hours) * 3600.0
    north_km = float(v_ms) * dt_s / 1000.0
    east_km = float(u_ms) * dt_s / 1000.0
    lat2 = float(lat) + math.degrees(north_km / EARTH_KM)
    coslat = max(0.05, abs(math.cos(math.radians((float(lat) + lat2) / 2.0))))
    lon2 = float(lon) + math.degrees(east_km / (EARTH_KM * coslat))
    lon2 = ((lon2 + 180.0) % 360.0) - 180.0
    return lat2, lon2


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    h = math.sin(dlat/2.0)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2.0)**2
    return 2.0 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


class CachedScientificSampler:
    """Nearest-neighbour samples from the real cached CMEMS and ERA5 files.

    Uses h5py directly so model training does not depend on xarray's optional
    NetCDF engine selection.  No interpolation or synthetic replacement is
    performed when the source cell is missing.
    """

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self.ocean_path = self.data_root / "raw" / "ocean_currents_offline.nc"
        era_candidates = sorted((self.data_root / "raw").glob("era5_antarctic_*.nc"))
        self.era_path = era_candidates[-1] if era_candidates else None
        self._ocean = None
        self._era = None

    @staticmethod
    def _nearest(arr: np.ndarray, value: float) -> int:
        return int(np.nanargmin(np.abs(np.asarray(arr, dtype=float) - float(value))))

    def _load_ocean(self):
        if self._ocean is not None:
            return self._ocean
        if not self.ocean_path.exists():
            raise FileNotFoundError(f"CMEMS cached file missing: {self.ocean_path}")
        import h5py
        with h5py.File(self.ocean_path, "r") as h:
            self._ocean = {
                "lat": np.asarray(h["latitude"][...], dtype=float),
                "lon": np.asarray(h["longitude"][...], dtype=float),
                "u": np.asarray(h["uo"][...], dtype=float).squeeze(),
                "v": np.asarray(h["vo"][...], dtype=float).squeeze(),
            }
        return self._ocean

    def _load_era(self):
        if self._era is not None:
            return self._era
        if self.era_path is None or not self.era_path.exists():
            raise FileNotFoundError("ERA5 cached file missing")
        import h5py
        with h5py.File(self.era_path, "r") as h:
            self._era = {
                "lat": np.asarray(h["latitude"][...], dtype=float),
                "lon": np.asarray(h["longitude"][...], dtype=float),
                # The bundled file has multiple valid times/expver records.
                # Nanmedian keeps only values genuinely present in the file.
                "u": np.asarray(h["u10"][...], dtype=float),
                "v": np.asarray(h["v10"][...], dtype=float),
            }
        return self._era

    def sample(self, lat: float, lon: float) -> dict[str, float]:
        o = self._load_ocean()
        e = self._load_era()
        oy, ox = self._nearest(o["lat"], lat), self._nearest(o["lon"], lon)
        ey, ex = self._nearest(e["lat"], lat), self._nearest(e["lon"], lon)
        ou = float(np.asarray(o["u"])[oy, ox])
        ov = float(np.asarray(o["v"])[oy, ox])
        eu = np.asarray(e["u"])[..., ey, ex].reshape(-1)
        ev = np.asarray(e["v"])[..., ey, ex].reshape(-1)
        wu = float(np.nanmedian(eu))
        wv = float(np.nanmedian(ev))
        vals = (ou, ov, wu, wv)
        if not all(math.isfinite(x) for x in vals):
            raise ValueError("Scientific forcing contains no-data at this observation")
        return {"ocean_u": ou, "ocean_v": ov, "wind_u": wu, "wind_v": wv}


def feature_vector(lat: float, lon: float, length_nm: float | None, width_nm: float | None,
                   area_sqkm: float | None, forcing: dict[str, float]) -> list[float]:
    rlon = math.radians(float(lon))
    return [
        float(lat) / 90.0,
        math.sin(rlon),
        math.cos(rlon),
        float(length_nm or 0.0) / 100.0,
        float(width_nm or 0.0) / 100.0,
        math.log1p(max(0.0, float(area_sqkm or 0.0))) / 10.0,
        float(forcing["ocean_u"]),
        float(forcing["ocean_v"]),
        float(forcing["wind_u"]) / 20.0,
        float(forcing["wind_v"]) / 20.0,
    ]


FEATURE_NAMES = [
    "latitude_scaled", "longitude_sin", "longitude_cos", "length_nm_scaled",
    "width_nm_scaled", "log_area_sqkm_scaled", "ocean_u_ms", "ocean_v_ms",
    "wind_u_scaled", "wind_v_scaled",
]


def build_real_transition_dataset(data_root: Path) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Build samples only from consecutive distinct official USNIC snapshots."""
    data_root = Path(data_root)
    snapshots = []
    for path in sorted((data_root / "raw").glob("usnic_icebergs_*.csv")):
        rows = read_usnic_snapshot(path)
        if rows:
            snapshots.append((path, rows))
    if len(snapshots) < 2:
        return np.empty((0, len(FEATURE_NAMES))), np.empty((0, 2)), []

    sampler = CachedScientificSampler(data_root)
    X: list[list[float]] = []
    Y: list[list[float]] = []
    meta: list[dict[str, Any]] = []
    # Build every chronological consecutive transition for each iceberg.  This
    # automatically scales when future official snapshots are archived.
    by_id: dict[str, list[dict[str, Any]]] = {}
    for _, snap in snapshots:
        for iid, row in snap.items():
            by_id.setdefault(iid, []).append(row)
    for iid, rows in by_id.items():
        # Deduplicate exact dated fixes because multiple archive filenames can
        # contain the same official observation date.
        dedup: dict[tuple[str, float, float], dict[str, Any]] = {}
        for row in rows:
            key = (row["timestamp"].date().isoformat(), round(row["lat"], 6), round(row["lon"], 6))
            dedup[key] = row
        obs = sorted(dedup.values(), key=lambda r: r["timestamp"])
        for a, b in zip(obs[:-1], obs[1:]):
            dt_days = (b["timestamp"] - a["timestamp"]).total_seconds() / 86400.0
            if not (0.25 <= dt_days <= 35.0):
                continue
            try:
                u_obs, v_obs, dt_h = enu_velocity(a, b)
                if math.hypot(u_obs, v_obs) > 2.0:
                    continue
                forcing = sampler.sample(a["lat"], a["lon"])
                u_phys = forcing["ocean_u"] + WINDAGE * forcing["wind_u"]
                v_phys = forcing["ocean_v"] + WINDAGE * forcing["wind_v"]
                X.append(feature_vector(a["lat"], a["lon"], a.get("length_nm"), a.get("width_nm"), a.get("area_sqkm"), forcing))
                Y.append([u_obs - u_phys, v_obs - v_phys])
                meta.append({
                    "iceberg_id": iid,
                    "start_lat": a["lat"], "start_lon": a["lon"],
                    "end_lat": b["lat"], "end_lon": b["lon"],
                    "start_time": a["timestamp"].isoformat(), "end_time": b["timestamp"].isoformat(),
                    "dt_hours": dt_h,
                    "observed_u_ms": u_obs, "observed_v_ms": v_obs,
                    "physics_u_ms": u_phys, "physics_v_ms": v_phys,
                    "forcing": forcing,
                    "source_files": [a["source_file"], b["source_file"]],
                })
            except Exception:
                # Missing/no-data forcing is excluded rather than synthesized.
                continue
    return np.asarray(X, dtype=float), np.asarray(Y, dtype=float), meta
