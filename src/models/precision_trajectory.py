"""Observation-aware Antarctic iceberg trajectory model.

Version 5.1 improves the earlier constant-vector baseline without pretending to
be a certified iceberg forecast.  It:
  * starts from the actual USNIC observation date (date-only -> noon UTC),
  * nowcasts from that observation to the present,
  * uses time-varying ocean-current and wind guidance,
  * smoothly blends forcing between spatial control points along the track,
  * assimilates recent observed USNIC displacement as a decaying residual,
  * uses a 1-hour Heun predictor/corrector integration,
  * propagates date/printed-coordinate ambiguity through a perturbation
    ensemble, and
  * reports P50/P90 spread plus along/cross-track P90 spread.

The spread is an engineering sensitivity ensemble, NOT a calibrated confidence
interval and NOT certified navigation guidance.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import List, Sequence

from src.models.trajectory import propagate_coordinate
from src.data_providers.forecast_forcing import sample_control_series


def _bearing_from_uv(u: float, v: float) -> float:
    if abs(u) < 1e-12 and abs(v) < 1e-12:
        return 0.0
    return math.atan2(u, v) % (2.0 * math.pi)


def _step(lat: float, lon: float, u: float, v: float, dt_seconds: float) -> tuple[float, float]:
    speed = math.hypot(u, v)
    if speed <= 0:
        return lat, lon
    return propagate_coordinate(lat, lon, speed * dt_seconds / 1000.0, _bearing_from_uv(u, v))


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(((lon2 - lon1 + 180) % 360) - 180)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1.0, math.sqrt(a)))


def _enu_delta_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """Small-angle east/north displacement from (lat0,lon0) in kilometres."""
    r = 6371.0088
    dlat = math.radians(lat - lat0)
    dlon = math.radians(((lon - lon0 + 180.0) % 360.0) - 180.0)
    mean_lat = math.radians((lat + lat0) * 0.5)
    return dlon * math.cos(mean_lat) * r, dlat * r


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    idx = min(len(xs)-1, max(0, int(round(q * (len(xs)-1)))))
    return xs[idx]


def _normal_position(rng: random.Random, lat: float, lon: float, sigma_km: float) -> tuple[float, float]:
    x = rng.gauss(0.0, sigma_km)
    y = rng.gauss(0.0, sigma_km)
    dist = math.hypot(x, y)
    if dist == 0:
        return lat, lon
    bearing = math.atan2(x, y) % (2*math.pi)
    return propagate_coordinate(lat, lon, dist, bearing)


def _blend_dict(a: dict, b: dict, w: float) -> dict:
    """Blend numeric forcing fields; preserve whichever non-numeric value exists."""
    out = {}
    for key in set(a) | set(b):
        av, bv = a.get(key), b.get(key)
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            out[key] = float(av) + (float(bv) - float(av)) * w
        elif av is None:
            out[key] = bv
        elif bv is None:
            out[key] = av
        else:
            out[key] = av if w < 0.5 else bv
    return out


class PrecisionIcebergTrajectoryModel:
    def __init__(self, windage: float = 0.018, residual_decay_hours: float = 36.0, step_hours: float = 1.0):
        self.windage = float(windage)
        self.residual_decay_hours = float(residual_decay_hours)
        self.step_hours = float(step_hours)
        self.version = "5.1-AssimilatedTimeVaryingSpatialBlend"

    @staticmethod
    def _forcing_at(control_times: Sequence[datetime], control_series: Sequence[dict], when: datetime) -> dict:
        """Time-aware spatial forcing interpolation along provisional track.

        control_times correspond to positions sampled along the provisional
        trajectory. At times between two control points, sample both complete
        model time series at the same timestamp and linearly blend their vector
        components. This avoids discontinuities when the nearest spatial
        control point changes every six hours.
        """
        if not control_series:
            return {"ocean_u": 0.0, "ocean_v": 0.0, "wind_u": 0.0, "wind_v": 0.0}
        if len(control_series) == 1 or len(control_times) <= 1:
            return sample_control_series(control_series[0], when)

        pairs = sorted(zip(control_times, control_series), key=lambda x: x[0])
        if when <= pairs[0][0]:
            return sample_control_series(pairs[0][1], when)
        if when >= pairs[-1][0]:
            return sample_control_series(pairs[-1][1], when)
        for i in range(1, len(pairs)):
            t1, s1 = pairs[i]
            if when <= t1:
                t0, s0 = pairs[i-1]
                span = (t1 - t0).total_seconds()
                w = 0.0 if span <= 0 else (when - t0).total_seconds() / span
                return _blend_dict(sample_control_series(s0, when), sample_control_series(s1, when), max(0.0, min(1.0, w)))
        return sample_control_series(pairs[-1][1], when)

    def _velocity(self, forcing: dict, elapsed_from_obs_h: float, observed_motion: dict | None,
                  current_scale: float = 1.0, windage: float | None = None,
                  residual_scale: float = 1.0) -> tuple[float, float]:
        beta = self.windage if windage is None else windage
        ou = float(forcing.get("ocean_u") or 0.0) * current_scale
        ov = float(forcing.get("ocean_v") or 0.0) * current_scale
        wu = float(forcing.get("wind_u") or 0.0)
        wv = float(forcing.get("wind_v") or 0.0)
        u = ou + beta * wu
        v = ov + beta * wv
        if observed_motion and observed_motion.get("available"):
            decay = math.exp(-max(0.0, elapsed_from_obs_h) / self.residual_decay_hours)
            u += float(observed_motion.get("residual_u_ms") or 0.0) * decay * residual_scale
            v += float(observed_motion.get("residual_v_ms") or 0.0) * decay * residual_scale

        # Optional machine-learning residual prior.  The ML model is trained on
        # real official USNIC position transitions and real cached CMEMS/ERA5
        # forcing.  It corrects the physics residual; it never replaces the
        # official observation.  Direct observed-motion assimilation retains
        # priority through a conservative lower ML weight when history exists.
        if observed_motion and observed_motion.get("ml_prior_applied"):
            ml_decay_h = float(observed_motion.get("ml_decay_hours") or 72.0)
            ml_decay = math.exp(-max(0.0, elapsed_from_obs_h) / max(12.0, ml_decay_h))
            ml_weight = float(observed_motion.get("ml_prior_weight") or 0.25)
            u += float(observed_motion.get("ml_residual_u_ms") or 0.0) * ml_weight * ml_decay
            v += float(observed_motion.get("ml_residual_v_ms") or 0.0) * ml_weight * ml_decay
        # Sanity guard only; this is not a physical speed limit.
        speed = math.hypot(u, v)
        if speed > 2.5:
            scale = 2.5 / speed
            u *= scale
            v *= scale
        return u, v

    def integrate(self, start_lat: float, start_lon: float, start_time: datetime, end_time: datetime,
                  control_times: Sequence[datetime], control_series: Sequence[dict], observed_motion: dict | None,
                  current_scale: float = 1.0, windage: float | None = None,
                  residual_scale: float = 1.0) -> List[dict]:
        start_time = start_time.astimezone(timezone.utc)
        end_time = end_time.astimezone(timezone.utc)
        lat, lon = start_lat, start_lon
        t = start_time
        out = [{"time": t, "lat": lat, "lon": lon, "u": 0.0, "v": 0.0, "forcing": {}}]
        dt_nom = self.step_hours * 3600.0
        while t < end_time:
            dt_s = min(dt_nom, (end_time - t).total_seconds())
            forcing = self._forcing_at(control_times, control_series, t)
            elapsed_h = (t - start_time).total_seconds() / 3600.0
            u1, v1 = self._velocity(forcing, elapsed_h, observed_motion, current_scale, windage, residual_scale)

            t2 = t + timedelta(seconds=dt_s)
            forcing2 = self._forcing_at(control_times, control_series, t2)
            u2, v2 = self._velocity(forcing2, elapsed_h + dt_s/3600.0, observed_motion, current_scale, windage, residual_scale)
            u = 0.5 * (u1 + u2)
            v = 0.5 * (v1 + v2)
            lat, lon = _step(lat, lon, u, v, dt_s)
            t = t2
            out.append({"time": t, "lat": lat, "lon": lon, "u": u, "v": v, "forcing": forcing2})
        return out

    @staticmethod
    def _nearest_state(track: Sequence[dict], when: datetime) -> dict:
        return min(track, key=lambda p: abs((p["time"] - when).total_seconds()))

    @staticmethod
    def _spread(central_state: dict, members: Sequence[tuple[float, float]]) -> dict:
        radial = [_haversine_km(central_state["lat"], central_state["lon"], la, lo) for la, lo in members]
        bearing = _bearing_from_uv(float(central_state.get("u") or 0.0), float(central_state.get("v") or 0.0))
        # unit vector in EN coordinates for the central drift bearing
        along_e, along_n = math.sin(bearing), math.cos(bearing)
        along_abs, cross_abs = [], []
        for la, lo in members:
            e, n = _enu_delta_km(central_state["lat"], central_state["lon"], la, lo)
            along = e*along_e + n*along_n
            cross = e*along_n - n*along_e
            along_abs.append(abs(along)); cross_abs.append(abs(cross))
        return {
            "p50_km": _percentile(radial, 0.50),
            "p90_km": _percentile(radial, 0.90),
            "along_track_p90_km": _percentile(along_abs, 0.90),
            "cross_track_p90_km": _percentile(cross_abs, 0.90),
        }

    def build_result(self, iceberg_id: str, start_lat: float, start_lon: float,
                     observation_time: datetime, now: datetime, horizons_hours: Sequence[int],
                     control_times: Sequence[datetime], control_series: Sequence[dict],
                     observed_motion: dict | None, forcing_metadata: dict,
                     ensemble_members: int = 48,
                     source_position_resolution_km: float = 1.5,
                     observation_time_uncertainty_hours: float = 12.0) -> dict:
        max_h = max(horizons_hours)
        end = now + timedelta(hours=max_h)
        central = self.integrate(start_lat, start_lon, observation_time, end, control_times, control_series, observed_motion)
        now_state = self._nearest_state(central, now)
        target_times = [now + timedelta(hours=h) for h in horizons_hours]
        central_nodes = [self._nearest_state(central, tt) for tt in target_times]

        # Deterministic engineering perturbation ensemble. Printed-coordinate
        # resolution and date-only timestamp ambiguity are explicitly included.
        rng = random.Random(f"{iceberg_id}:{observation_time.date().isoformat()}:v5.1")
        now_members: list[tuple[float, float]] = []
        member_positions = [[] for _ in horizons_hours]
        source_sigma = max(0.25, min(5.0, float(source_position_resolution_km) / 2.0))
        has_motion = bool(observed_motion and observed_motion.get("available"))
        motion_scatter = float((observed_motion or {}).get("motion_scatter_ms") or 0.0)
        current_sigma = 0.10 if has_motion else 0.16
        residual_sigma = min(0.60, 0.18 + motion_scatter / 0.35) if has_motion else 0.0

        for _ in range(max(0, int(ensemble_members))):
            ilat, ilon = _normal_position(rng, start_lat, start_lon, sigma_km=source_sigma)
            shift_h = rng.uniform(-observation_time_uncertainty_hours, observation_time_uncertainty_hours)
            member_start = observation_time + timedelta(hours=shift_h)
            # An observation cannot physically occur after the nowcast target.
            member_start = min(member_start, now)
            member = self.integrate(
                ilat, ilon, member_start, end, control_times, control_series, observed_motion,
                current_scale=max(0.55, rng.gauss(1.0, current_sigma)),
                windage=max(0.004, min(0.040, rng.gauss(self.windage, 0.0045))),
                residual_scale=max(0.0, rng.gauss(1.0, residual_sigma)) if has_motion else 0.0,
            )
            s_now = self._nearest_state(member, now)
            now_members.append((s_now["lat"], s_now["lon"]))
            for i, tt in enumerate(target_times):
                s = self._nearest_state(member, tt)
                member_positions[i].append((s["lat"], s["lon"]))

        now_spread = self._spread(now_state, now_members)
        trajectory = []
        for i, (h, state) in enumerate(zip(horizons_hours, central_nodes)):
            spread = self._spread(state, member_positions[i])
            trajectory.append({
                "horizon_hours": int(h),
                "forecast_timestamp": state["time"].isoformat(),
                "latitude": state["lat"],
                "longitude": state["lon"],
                "drift_speed_ms": math.hypot(state["u"], state["v"]),
                "drift_bearing_deg": (math.degrees(math.atan2(state["u"], state["v"])) + 360.0) % 360.0 if (state["u"] or state["v"]) else 0.0,
                "uncertainty_radius_km": spread["p90_km"],
                "spread_p50_km": spread["p50_km"],
                "spread_p90_km": spread["p90_km"],
                "along_track_p90_km": spread["along_track_p90_km"],
                "cross_track_p90_km": spread["cross_track_p90_km"],
                "uncertainty_type": "uncalibrated perturbation-ensemble sensitivity spread (P90), not a certified probability bound",
            })

        age_h = max(0.0, (now - observation_time).total_seconds()/3600.0)
        quality = "HIGHER" if forcing_metadata.get("online") and has_motion and age_h <= 96 else (
            "MODERATE" if forcing_metadata.get("online") and age_h <= 168 else "LIMITED"
        )
        return {
            "iceberg_id": iceberg_id,
            "model_version": self.version,
            "model_name": "Observation-assimilated time-varying drift model",
            "initial_latitude": start_lat,
            "initial_longitude": start_lon,
            "observation_timestamp_assumed": observation_time.isoformat(),
            "observation_time_note": "USNIC table supplies a date but not an observation time; NAV-X assumes 12:00 UTC and propagates ±12 h timing ambiguity in the ensemble.",
            "observation_age_hours": round(age_h, 1),
            "nowcast": {
                "timestamp": now_state["time"].isoformat(),
                "latitude": now_state["lat"],
                "longitude": now_state["lon"],
                "status": "MODEL_NOWCAST_FROM_LATEST_USNIC_FIX",
                "spread_p50_km": now_spread["p50_km"],
                "spread_p90_km": now_spread["p90_km"],
                "along_track_p90_km": now_spread["along_track_p90_km"],
                "cross_track_p90_km": now_spread["cross_track_p90_km"],
            },
            "trajectory": trajectory,
            "motion_assimilation": observed_motion or {"available": False},
            "forcing": forcing_metadata,
            "precision_budget": {
                "source_coordinate_resolution_km": round(float(source_position_resolution_km), 2),
                "observation_time_ambiguity_hours": float(observation_time_uncertainty_hours),
                "forcing_grid_note": forcing_metadata.get("current_resolution_note") or "Forcing resolution depends on active source.",
                "reported_position_decimals": 2,
                "note": "Displayed model coordinates are rounded to 0.01° to avoid implying sub-kilometre accuracy that the source/model does not support.",
            },
            "quality": {
                "level": quality,
                "validated_navigation_accuracy": False,
                "note": "Improved numerical precision and data assimilation versus the constant-vector baseline, but not statistically validated/certified for navigation. Use official ice/hydrographic products for operations.",
            },
        }
