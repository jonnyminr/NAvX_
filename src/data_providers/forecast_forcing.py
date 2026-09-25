"""Fresh model-guidance forcing for trajectory forecasts.

Online mode uses:
- Open-Meteo Marine API for time-varying ocean-current speed/direction.
- Open-Meteo ECMWF API for time-varying 10 m wind.

No API key is required.  These are model fields, not direct observations.  The
provider degrades to the project's cached CMEMS/ERA5 sample when internet data
are unavailable.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
ECMWF_URL = "https://api.open-meteo.com/v1/ecmwf"


def _iso_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _nearest_index(times: Sequence[datetime], target: datetime) -> int:
    if not times:
        return 0
    target = target.astimezone(timezone.utc)
    xs = [t.timestamp() for t in times]
    x = target.timestamp()
    i = bisect.bisect_left(xs, x)
    if i <= 0:
        return 0
    if i >= len(xs):
        return len(xs) - 1
    return i if abs(xs[i] - x) < abs(xs[i - 1] - x) else i - 1


def _interp_value(times: Sequence[datetime], values: Sequence, target: datetime):
    """Linearly interpolate a scalar time-series at *target*.

    External model fields are generally hourly. Interpolation avoids the
    artificial one-hour jumps produced by nearest-neighbour sampling while
    preserving exact model values at model timestamps. Missing values fall
    back to the nearest valid endpoint.
    """
    if not times or not values:
        return None
    n = min(len(times), len(values))
    times = list(times[:n])
    values = list(values[:n])
    x = target.astimezone(timezone.utc).timestamp()
    xs = [t.timestamp() for t in times]
    i = bisect.bisect_left(xs, x)
    if i <= 0:
        return values[0]
    if i >= n:
        return values[-1]
    a, b = values[i-1], values[i]
    if a is None:
        return b
    if b is None:
        return a
    try:
        span = xs[i] - xs[i-1]
        w = 0.0 if span <= 0 else (x - xs[i-1]) / span
        return float(a) + (float(b) - float(a)) * max(0.0, min(1.0, w))
    except (TypeError, ValueError):
        return a if abs(x-xs[i-1]) <= abs(xs[i]-x) else b


def _marine_components(speed_ms: float | None, direction_deg: float | None) -> tuple[float, float]:
    if speed_ms is None or direction_deg is None:
        return 0.0, 0.0
    # Marine API direction is where the current is heading: 0=N, 90=E.
    r = math.radians(float(direction_deg))
    s = float(speed_ms)
    return s * math.sin(r), s * math.cos(r)


def _wind_components(speed_ms: float | None, direction_from_deg: float | None) -> tuple[float, float]:
    if speed_ms is None or direction_from_deg is None:
        return 0.0, 0.0
    # Meteorological wind direction is FROM. Convert to velocity TOWARD.
    r = math.radians(float(direction_from_deg))
    s = float(speed_ms)
    return -s * math.sin(r), -s * math.cos(r)


class OpenMeteoForcingProvider:
    def __init__(self, timeout_seconds: float = 12.0):
        self.timeout = timeout_seconds

    def _fetch(self, url: str, params: dict):
        headers = {"User-Agent": "ANTARCTIC-NAV-X/5.0 (educational decision-support prototype)"}
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    @staticmethod
    def _as_list(payload):
        return payload if isinstance(payload, list) else [payload]

    def fetch_multi(self, positions: Sequence[tuple[float, float]], start: datetime, end: datetime) -> List[dict]:
        """Fetch time series for multiple spatial control points in two calls."""
        if not positions:
            return []
        lats = ",".join(f"{lat:.5f}" for lat, _ in positions)
        lons = ",".join(f"{lon:.5f}" for _, lon in positions)
        start_date = start.astimezone(timezone.utc).date().isoformat()
        end_date = end.astimezone(timezone.utc).date().isoformat()

        marine = self._fetch(MARINE_URL, {
            "latitude": lats,
            "longitude": lons,
            "hourly": "ocean_current_velocity,ocean_current_direction,sea_surface_temperature",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "cell_selection": "sea",
            "start_date": start_date,
            "end_date": end_date,
        })
        wind = self._fetch(ECMWF_URL, {
            "latitude": lats,
            "longitude": lons,
            "hourly": "wind_speed_10m,wind_direction_10m,pressure_msl",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "start_date": start_date,
            "end_date": end_date,
        })

        mlist = self._as_list(marine)
        wlist = self._as_list(wind)
        out = []
        for idx, pos in enumerate(positions):
            mp = mlist[min(idx, len(mlist) - 1)]
            wp = wlist[min(idx, len(wlist) - 1)]
            mh = mp.get("hourly") or {}
            wh = wp.get("hourly") or {}
            mt = [_iso_dt(t) for t in (mh.get("time") or [])]
            wt = [_iso_dt(t) for t in (wh.get("time") or [])]
            out.append({
                "lat": pos[0], "lon": pos[1],
                "marine_times": mt,
                "current_speed": mh.get("ocean_current_velocity") or [],
                "current_dir": mh.get("ocean_current_direction") or [],
                "sst": mh.get("sea_surface_temperature") or [],
                "wind_times": wt,
                "wind_speed": wh.get("wind_speed_10m") or [],
                "wind_dir": wh.get("wind_direction_10m") or [],
                "pressure_msl": wh.get("pressure_msl") or [],
            })
        return out

    @staticmethod
    def sample(series: dict, when: datetime) -> Dict[str, float | None]:
        mt = series.get("marine_times") or []
        wt = series.get("wind_times") or []
        # Interpolate vector components, not direction angles. This avoids the
        # 359° -> 1° wrap-around problem and produces smooth forcing.
        cs = series.get("current_speed") or []
        cd = series.get("current_dir") or []
        ws = series.get("wind_speed") or []
        wd = series.get("wind_dir") or []

        # Build endpoint components then interpolate u/v directly.
        marine_u, marine_v = [], []
        for speed, direction in zip(cs, cd):
            u, v = _marine_components(speed, direction)
            marine_u.append(u); marine_v.append(v)
        wind_u, wind_v = [], []
        for speed, direction in zip(ws, wd):
            u, v = _wind_components(speed, direction)
            wind_u.append(u); wind_v.append(v)

        c_u = _interp_value(mt, marine_u, when) or 0.0
        c_v = _interp_value(mt, marine_v, when) or 0.0
        w_u = _interp_value(wt, wind_u, when) or 0.0
        w_v = _interp_value(wt, wind_v, when) or 0.0
        sst_val = _interp_value(mt, series.get("sst") or [], when)
        pmsl_val = _interp_value(wt, series.get("pressure_msl") or [], when)
        return {
            "ocean_u": float(c_u),
            "ocean_v": float(c_v),
            "wind_u": float(w_u),
            "wind_v": float(w_v),
            "sea_surface_temperature_c": sst_val,
            "pressure_msl_hpa": (float(pmsl_val) / 100.0) if pmsl_val is not None else None,
        }


def fallback_constant_series(sample: dict, positions: Sequence[tuple[float, float]]) -> List[dict]:
    """Compatibility object for offline integration using one local sample."""
    return [{"lat": lat, "lon": lon, "constant": dict(sample)} for lat, lon in positions]


def sample_control_series(series: dict, when: datetime) -> dict:
    if "constant" in series:
        return dict(series["constant"])
    return OpenMeteoForcingProvider.sample(series, when)
