"""Time-aware Antarctic marine route optimizer for ANTARCTIC NAV-X.

This module generates transparent, deterministic route candidates over a polar
planning grid. The route cost combines geodesic distance with time-matched
iceberg forecast uncertainty. It is decision-support software, not certified
ECDIS or autonomous-navigation guidance.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from src.models.risk import haversine_distance

ANTARCTIC_NORTH_LIMIT = -45.0


@dataclass(frozen=True)
class HazardPoint:
    lat: float
    lon: float
    uncertainty_km: float
    iceberg_id: str = "UNKNOWN"
    horizon_hours: float = 0.0


def _norm_lon(lon: float) -> float:
    x = float(lon)
    while x > 180:
        x -= 360
    while x < -180:
        x += 360
    return x


def _unwrap_lon(lon: float, reference: float) -> float:
    x = float(lon)
    while x - reference > 180:
        x -= 360
    while x - reference < -180:
        x += 360
    return x


def route_distance_km(route: List[Dict[str, float]]) -> float:
    return sum(
        haversine_distance(route[i]["lat"], route[i]["lon"], route[i + 1]["lat"], route[i + 1]["lon"])
        for i in range(len(route) - 1)
    )


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle initial bearing from point 1 to point 2."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(_norm_lon(lon2 - lon1))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def great_circle_interpolate(a: Dict[str, float], b: Dict[str, float], fraction: float) -> Dict[str, float]:
    """Spherical linear interpolation along the shortest geodesic."""
    f = max(0.0, min(1.0, float(fraction)))
    lat1, lon1 = math.radians(float(a["lat"])), math.radians(float(a["lon"]))
    lat2, lon2 = math.radians(float(b["lat"])), math.radians(float(b["lon"]))
    v1 = (math.cos(lat1) * math.cos(lon1), math.cos(lat1) * math.sin(lon1), math.sin(lat1))
    v2 = (math.cos(lat2) * math.cos(lon2), math.cos(lat2) * math.sin(lon2), math.sin(lat2))
    dot = max(-1.0, min(1.0, sum(x*y for x, y in zip(v1, v2))))
    omega = math.acos(dot)
    if omega < 1e-12:
        return {"lat": float(a["lat"]), "lon": _norm_lon(float(a["lon"]))}
    so = math.sin(omega)
    k1 = math.sin((1.0 - f) * omega) / so
    k2 = math.sin(f * omega) / so
    x = k1 * v1[0] + k2 * v2[0]
    y = k1 * v1[1] + k2 * v2[1]
    z = k1 * v1[2] + k2 * v2[2]
    lat = math.degrees(math.atan2(z, math.hypot(x, y)))
    lon = math.degrees(math.atan2(y, x))
    return {"lat": lat, "lon": _norm_lon(lon)}


def densify_geodesic(route: List[Dict[str, float]], spacing_km: float = 35.0) -> List[Dict[str, float]]:
    """Densify route segments using great-circle interpolation."""
    if len(route) < 2:
        return list(route)
    out = [dict(route[0])]
    for a, b in zip(route, route[1:]):
        dist = haversine_distance(a["lat"], a["lon"], b["lat"], b["lon"])
        n = max(1, int(math.ceil(dist / max(5.0, spacing_km))))
        for i in range(1, n + 1):
            p = great_circle_interpolate(a, b, i / n)
            if i == n:
                p = {"lat": float(b["lat"]), "lon": _norm_lon(float(b["lon"]))}
            out.append({"lat": round(p["lat"], 6), "lon": round(p["lon"], 6)})
    return out


def extract_hazard_points(icebergs: Iterable[Dict[str, Any]]) -> List[HazardPoint]:
    hazards: List[HazardPoint] = []
    for ib in icebergs or []:
        iid = str(ib.get("iceberg_id") or ib.get("id") or "UNKNOWN")
        traj = ib.get("trajectory") or []
        for idx, p in enumerate(traj):
            try:
                h = p.get("horizon_hours")
                if h is None:
                    # V5/V8 trajectories conventionally use [0,6,12,24,48,72].
                    h = [0, 6, 12, 24, 48, 72][idx] if idx < 6 else idx * 12
                hazards.append(
                    HazardPoint(
                        lat=float(p["latitude"]),
                        lon=_norm_lon(float(p["longitude"])),
                        uncertainty_km=max(0.0, float(p.get("uncertainty_radius_km") or p.get("p90_radius_km") or 0.0)),
                        iceberg_id=iid,
                        horizon_hours=max(0.0, float(h)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return hazards


def _tracks(hazards: List[HazardPoint]) -> Dict[str, List[HazardPoint]]:
    out: Dict[str, List[HazardPoint]] = {}
    for h in hazards:
        out.setdefault(h.iceberg_id, []).append(h)
    for seq in out.values():
        seq.sort(key=lambda p: p.horizon_hours)
    return out


def interpolate_hazard_track(track: List[HazardPoint], eta_hours: float) -> HazardPoint:
    if not track:
        raise ValueError("empty hazard track")
    if eta_hours <= track[0].horizon_hours:
        return track[0]
    if eta_hours >= track[-1].horizon_hours:
        return track[-1]
    for a, b in zip(track, track[1:]):
        if a.horizon_hours <= eta_hours <= b.horizon_hours:
            span = max(1e-9, b.horizon_hours - a.horizon_hours)
            f = (eta_hours - a.horizon_hours) / span
            p = great_circle_interpolate({"lat": a.lat, "lon": a.lon}, {"lat": b.lat, "lon": b.lon}, f)
            return HazardPoint(
                lat=p["lat"], lon=p["lon"],
                uncertainty_km=a.uncertainty_km + f * (b.uncertainty_km - a.uncertainty_km),
                iceberg_id=a.iceberg_id, horizon_hours=eta_hours,
            )
    return track[-1]


class PolarAStarRouter:
    """Adaptive A* router with time-matched forecast hazard penalties."""

    PROFILES = {
        "FASTEST":  {"risk_weight": 0.85, "hard_buffer_factor": 0.20, "distance_weight": 1.00, "sea_ice_weight": 0.35},
        "BALANCED": {"risk_weight": 3.25, "hard_buffer_factor": 0.85, "distance_weight": 1.00, "sea_ice_weight": 0.90},
        "SAFEST":   {"risk_weight": 8.00, "hard_buffer_factor": 1.15, "distance_weight": 1.02, "sea_ice_weight": 1.65},
    }

    def __init__(self, max_nodes: int = 56, surface: Any | None = None):
        self.max_nodes = max(26, min(84, int(max_nodes)))
        self.surface = surface
        self.last_fallback = False
        self.last_grid = None
        self.last_surface_samples = 0
        self.last_surface_blocked = 0


    def _point_navigable(self, lat: float, lon: float) -> bool:
        if self.surface is None:
            return True
        self.last_surface_samples += 1
        try:
            ok = bool(self.surface.is_navigable(float(lat), _norm_lon(float(lon))))
        except Exception:
            ok = False
        if not ok:
            self.last_surface_blocked += 1
        return ok

    def _sea_ice_penalty(self, lat: float, lon: float, step_distance_km: float, profile: Dict[str, float]) -> float:
        if self.surface is None:
            return 0.0
        try:
            concentration = self.surface.sea_ice_concentration_percent(float(lat), _norm_lon(float(lon)))
        except Exception:
            concentration = None
        if concentration is None:
            # Missing verified sea-ice data is not equivalent to zero ice.
            # Returning infinity causes the candidate cell to be rejected.
            return float("inf")
        fraction = max(0.0, min(1.0, float(concentration) / 100.0))
        # Real NSIDC concentration is a soft route cost, not a fabricated hard
        # prohibition. This lets ice-capable operators compare options while
        # still strongly preferring lower-concentration corridors.
        return float(step_distance_km) * float(profile.get("sea_ice_weight", 0.0)) * (fraction ** 2.2)

    def _surface_segment_safe(self, a: Dict[str, float], b: Dict[str, float]) -> bool:
        if self.surface is None:
            return True
        dist = haversine_distance(a["lat"], a["lon"], b["lat"], b["lon"])
        n = max(2, int(math.ceil(dist / 20.0)))
        for i in range(1, n + 1):
            p = great_circle_interpolate(a, b, i / n)
            if not self._point_navigable(p["lat"], p["lon"]):
                return False
        return True

    @staticmethod
    def _validate_operational_area(start: Dict[str, float], end: Dict[str, float]) -> None:
        for name, point in (("origin", start), ("destination", end)):
            lat = float(point["lat"])
            if lat > ANTARCTIC_NORTH_LIMIT:
                raise ValueError(f"{name} is north of the Antarctic/Southern Ocean operational limit ({abs(ANTARCTIC_NORTH_LIMIT):.0f}°S).")
            if lat < -90 or not -180 <= float(point["lon"]) <= 180:
                raise ValueError(f"invalid {name} coordinate")

    def _bounds(self, start: Dict[str, float], end: Dict[str, float], hazards: List[HazardPoint]) -> Tuple[float, float, float, float, float]:
        ref_lon = float(start["lon"])
        end_lon = _unwrap_lon(float(end["lon"]), ref_lon)
        base_lats = [float(start["lat"]), float(end["lat"])]
        base_lons = [ref_lon, end_lon]
        corridor_lat_min = min(base_lats) - 10.0
        corridor_lat_max = min(ANTARCTIC_NORTH_LIMIT, max(base_lats) + 10.0)
        for h in hazards:
            if corridor_lat_min <= h.lat <= corridor_lat_max:
                base_lats.append(h.lat)
                base_lons.append(_unwrap_lon(h.lon, ref_lon))
        span_lat = max(3.0, max(base_lats) - min(base_lats))
        span_lon = max(4.0, max(base_lons) - min(base_lons))
        lat_margin = min(11.0, max(2.5, span_lat * 0.32))
        lon_margin = min(20.0, max(4.0, span_lon * 0.32))
        return (
            max(-89.5, min(base_lats) - lat_margin),
            min(ANTARCTIC_NORTH_LIMIT, max(base_lats) + lat_margin),
            min(base_lons) - lon_margin,
            max(base_lons) + lon_margin,
            ref_lon,
        )

    def _grid(self, bounds: Tuple[float, float, float, float, float]):
        min_lat, max_lat, min_lon, max_lon, _ = bounds
        lat_span = max_lat - min_lat
        # Longitude metres shrink toward the pole. Use middle latitude to keep cells closer to square.
        mid_lat = math.radians((min_lat + max_lat) / 2.0)
        lon_equiv = max(0.15, abs(math.cos(mid_lat))) * (max_lon - min_lon)
        aspect = max(0.48, min(2.4, lon_equiv / max(lat_span, 0.1)))
        ny = min(self.max_nodes, max(28, int(self.max_nodes / math.sqrt(aspect))))
        nx = min(self.max_nodes, max(28, int(ny * aspect)))
        lat_step = lat_span / max(ny - 1, 1)
        lon_step = (max_lon - min_lon) / max(nx - 1, 1)
        self.last_grid = {"nx": nx, "ny": ny, "lat_step": lat_step, "lon_step": lon_step}
        return nx, ny, lat_step, lon_step

    @staticmethod
    def _cell_coord(ix: int, iy: int, bounds, lat_step, lon_step):
        min_lat, _, min_lon, _, _ = bounds
        return min_lat + iy * lat_step, min_lon + ix * lon_step

    @staticmethod
    def _nearest_cell(p: Dict[str, float], bounds, nx, ny, lat_step, lon_step):
        min_lat, _, min_lon, _, ref_lon = bounds
        lon = _unwrap_lon(float(p["lon"]), ref_lon)
        ix = int(round((lon - min_lon) / lon_step))
        iy = int(round((float(p["lat"]) - min_lat) / lat_step))
        return max(0, min(nx - 1, ix)), max(0, min(ny - 1, iy))

    def _hazard_penalty(self, lat: float, lon: float, eta_hours: float, tracks: Dict[str, List[HazardPoint]], safety_km: float, profile: Dict[str, float]) -> float:
        if not tracks:
            return 0.0
        penalty = 0.0
        for seq in tracks.values():
            h = interpolate_hazard_track(seq, eta_hours)
            h_lon = _unwrap_lon(h.lon, lon)
            d = haversine_distance(lat, lon, h.lat, h_lon)
            # P90 forecast spread plus requested operator safety buffer.
            envelope = max(3.0, h.uncertainty_km) + safety_km
            hard = envelope * profile["hard_buffer_factor"]
            if d < hard:
                return float("inf")
            # Continuous penalty out to 4× the P90+buffer envelope.
            influence = envelope * 4.0
            if d < influence:
                proximity = max(0.0, 1.0 - d / influence)
                penalty += profile["risk_weight"] * (proximity ** 2.4) * 150.0
        return penalty

    def _segment_safe(self, a: Dict[str, float], b: Dict[str, float], start_distance_km: float, speed_kmh: float, tracks: Dict[str, List[HazardPoint]], safety_km: float, profile: Dict[str, float]) -> bool:
        dist = haversine_distance(a["lat"], a["lon"], b["lat"], b["lon"])
        n = max(2, int(math.ceil(dist / 25.0)))
        for i in range(1, n + 1):
            f = i / n
            p = great_circle_interpolate(a, b, f)
            if not self._point_navigable(p["lat"], p["lon"]):
                return False
            eta = (start_distance_km + dist * f) / max(speed_kmh, 1.0)
            if math.isinf(self._hazard_penalty(p["lat"], p["lon"], eta, tracks, safety_km, profile)):
                return False
        return True

    def route(self, start: Dict[str, float], end: Dict[str, float], hazards: List[HazardPoint], safety_km: float, profile_name: str, speed_kmh: float = 20.0) -> List[Dict[str, float]]:
        self._validate_operational_area(start, end)
        self.last_surface_samples = 0
        self.last_surface_blocked = 0
        if not self._point_navigable(start["lat"], start["lon"]):
            raise ValueError("origin is not on a navigable ocean/sea-ice cell in the loaded CMEMS/NSIDC datasets")
        if not self._point_navigable(end["lat"], end["lon"]):
            raise ValueError("destination is not on a navigable ocean/sea-ice cell in the loaded CMEMS/NSIDC datasets")
        speed_kmh = max(1.0, float(speed_kmh))
        profile_name = profile_name.upper()
        profile = self.PROFILES.get(profile_name, self.PROFILES["BALANCED"])
        bounds = self._bounds(start, end, hazards)
        nx, ny, lat_step, lon_step = self._grid(bounds)
        start_cell = self._nearest_cell(start, bounds, nx, ny, lat_step, lon_step)
        end_cell = self._nearest_cell(end, bounds, nx, ny, lat_step, lon_step)
        tracks = _tracks(hazards)

        def heuristic(cell):
            la, lo = self._cell_coord(cell[0], cell[1], bounds, lat_step, lon_step)
            e_lon = _unwrap_lon(float(end["lon"]), lo)
            return haversine_distance(la, lo, float(end["lat"]), e_lon)

        moves = [(-1,-1), (0,-1), (1,-1), (-1,0), (1,0), (-1,1), (0,1), (1,1)]
        # heap entries: f_cost, total_cost, traveled_distance, cell
        open_heap = [(heuristic(start_cell), 0.0, 0.0, start_cell)]
        came_from: Dict[Tuple[int,int], Tuple[int,int]] = {}
        cost_score = {start_cell: 0.0}
        dist_score = {start_cell: 0.0}
        closed = set()

        while open_heap:
            _, current_cost, current_dist, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            closed.add(cur)
            if cur == end_cell:
                break
            c_lat, c_lon = self._cell_coord(cur[0], cur[1], bounds, lat_step, lon_step)
            for dx, dy in moves:
                nb = (cur[0] + dx, cur[1] + dy)
                if not (0 <= nb[0] < nx and 0 <= nb[1] < ny):
                    continue
                n_lat, n_lon = self._cell_coord(nb[0], nb[1], bounds, lat_step, lon_step)
                if n_lat > ANTARCTIC_NORTH_LIMIT or not self._point_navigable(n_lat, n_lon):
                    continue
                step_dist = haversine_distance(c_lat, c_lon, n_lat, n_lon)
                if not self._surface_segment_safe({"lat": c_lat, "lon": c_lon}, {"lat": n_lat, "lon": n_lon}):
                    continue
                traveled = current_dist + step_dist
                eta = traveled / speed_kmh
                penalty = self._hazard_penalty(n_lat, n_lon, eta, tracks, safety_km, profile)
                if math.isinf(penalty):
                    continue
                sea_ice_penalty = self._sea_ice_penalty(n_lat, n_lon, step_dist, profile)
                if math.isinf(sea_ice_penalty):
                    continue
                step_cost = step_dist * profile["distance_weight"] + penalty + sea_ice_penalty
                tentative = current_cost + step_cost
                if tentative < cost_score.get(nb, float("inf")):
                    cost_score[nb] = tentative
                    dist_score[nb] = traveled
                    came_from[nb] = cur
                    heapq.heappush(open_heap, (tentative + heuristic(nb), tentative, traveled, nb))

        self.last_fallback = False
        if end_cell not in came_from and end_cell != start_cell:
            raise ValueError("no ocean-safe route was found on the loaded CMEMS/NSIDC navigation surface; refusing to return a straight-line fallback through land")

        cells = [end_cell]
        cur = end_cell
        while cur != start_cell:
            cur = came_from[cur]
            cells.append(cur)
        cells.reverse()

        raw = [dict(start)]
        for cell in cells[1:-1]:
            lat, lon = self._cell_coord(cell[0], cell[1], bounds, lat_step, lon_step)
            raw.append({"lat": lat, "lon": _norm_lon(lon)})
        raw.append(dict(end))
        smoothed = self._line_of_sight_smooth(raw, speed_kmh, tracks, safety_km, profile)
        return densify_geodesic(smoothed, spacing_km=35.0)

    def _line_of_sight_smooth(self, route: List[Dict[str, float]], speed_kmh: float, tracks: Dict[str, List[HazardPoint]], safety_km: float, profile: Dict[str, float]) -> List[Dict[str, float]]:
        if len(route) <= 2:
            return route
        out = [route[0]]
        i = 0
        traveled = 0.0
        while i < len(route) - 1:
            chosen = i + 1
            # Find farthest safe node visible from the current node.
            for j in range(len(route) - 1, i, -1):
                if self._segment_safe(route[i], route[j], traveled, speed_kmh, tracks, safety_km, profile):
                    chosen = j
                    break
            traveled += haversine_distance(route[i]["lat"], route[i]["lon"], route[chosen]["lat"], route[chosen]["lon"])
            out.append(route[chosen])
            i = chosen
        return out


def risk_score(risk: str, min_clearance_km: float | None, hazards: int, safety_threshold_km: float) -> int:
    base = {"LOW": 6, "MODERATE": 34, "HIGH": 70, "CRITICAL": 94}.get(str(risk).upper(), 50)
    if min_clearance_km is not None:
        clearance = float(min_clearance_km)
        if clearance <= 0:
            base += 6
        elif clearance < safety_threshold_km:
            base += int(16 * (1 - clearance / max(safety_threshold_km, 1)))
        elif clearance > safety_threshold_km * 2:
            base -= min(8, int((clearance - safety_threshold_km * 2) / max(safety_threshold_km, 1) * 3))
    base += min(10, hazards * 2)
    return max(0, min(100, int(round(base))))
