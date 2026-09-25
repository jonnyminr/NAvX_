import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from src.models.trajectory import propagate_coordinate
from src.models.risk import haversine_distance

class DataFreshnessChecker:
    def __init__(self, stale_threshold_hours: int = 48):
        self.stale_threshold_hours = stale_threshold_hours
        
    def check_freshness(self, dataset_name: str, data_timestamp_str: str) -> Dict[str, Any]:
        """Checks if a dataset is older than the stale threshold."""
        try:
            # Handle ISO formats and CMEMS specific trailing Z
            data_time = datetime.fromisoformat(data_timestamp_str.replace("Z", "+00:00")).replace(tzinfo=None)
            now = datetime.utcnow()
            age_hours = (now - data_time).total_seconds() / 3600.0
            
            is_stale = age_hours > self.stale_threshold_hours
            status = "⚠ STALE DATA" if is_stale else "CACHED / AVAILABLE"
            
            return {
                "dataset": dataset_name,
                "timestamp": data_timestamp_str,
                "age_hours": round(age_hours, 1),
                "status": status,
                "is_stale": is_stale
            }
        except Exception:
            return {
                "dataset": dataset_name,
                "timestamp": data_timestamp_str,
                "age_hours": 999.0,
                "status": "⚠ UNKNOWN / STALE DATA",
                "is_stale": True
            }

class VesselSimulator:
    """Propagates a vessel along route waypoints using great-circle interpolation."""
    def __init__(self, speed_kmh: float):
        self.speed_kmh = max(1.0, float(speed_kmh))

    @staticmethod
    def _slerp(p1: Dict[str, float], p2: Dict[str, float], fraction: float) -> Dict[str, float]:
        f = max(0.0, min(1.0, float(fraction)))
        lat1, lon1 = math.radians(float(p1["lat"])), math.radians(float(p1["lon"]))
        lat2, lon2 = math.radians(float(p2["lat"])), math.radians(float(p2["lon"]))
        v1 = (math.cos(lat1)*math.cos(lon1), math.cos(lat1)*math.sin(lon1), math.sin(lat1))
        v2 = (math.cos(lat2)*math.cos(lon2), math.cos(lat2)*math.sin(lon2), math.sin(lat2))
        dot = max(-1.0, min(1.0, sum(a*b for a,b in zip(v1,v2))))
        omega = math.acos(dot)
        if omega < 1e-12:
            return {"lat": float(p1["lat"]), "lon": float(p1["lon"])}
        so = math.sin(omega)
        a = math.sin((1.0-f)*omega)/so
        b = math.sin(f*omega)/so
        x = a*v1[0]+b*v2[0]; y = a*v1[1]+b*v2[1]; z = a*v1[2]+b*v2[2]
        lon = math.degrees(math.atan2(y,x))
        while lon > 180: lon -= 360
        while lon < -180: lon += 360
        return {"lat": math.degrees(math.atan2(z, math.hypot(x,y))), "lon": lon}

    def interpolate_route(self, waypoints: List[Dict[str, float]], start_time: datetime, time_step_hours: float = 0.5) -> List[Dict[str, Any]]:
        if not waypoints:
            return []
        current_time = start_time
        simulated_path = [{"lat": float(waypoints[0]["lat"]), "lon": float(waypoints[0]["lon"]), "time": current_time}]
        for p1, p2 in zip(waypoints, waypoints[1:]):
            dist_leg = haversine_distance(float(p1["lat"]), float(p1["lon"]), float(p2["lat"]), float(p2["lon"]))
            if dist_leg <= 0:
                continue
            time_leg_hours = dist_leg / self.speed_kmh
            step_hours = max(0.1, time_step_hours)
            ratio = time_leg_hours / step_hours
            nearest = round(ratio)
            # Avoid an extra sample caused only by Earth-radius/degree rounding
            # when the leg duration is effectively an integer number of steps.
            steps = max(1, int(nearest if nearest >= 1 and abs(ratio - nearest) < 0.02 else math.ceil(ratio)))
            dt = timedelta(hours=time_leg_hours / steps)
            for s in range(1, steps + 1):
                current_time += dt
                pos = self._slerp(p1, p2, s / steps)
                simulated_path.append({"lat": pos["lat"], "lon": pos["lon"], "time": current_time})
        return simulated_path


class SpatiotemporalHazardAnalyzer:
    """
    Analyzes collision risk dynamically across time, considering both vessel motion, 
    iceberg drift, and expanding uncertainty envelopes.
    """
    def __init__(self, safety_threshold_km: float = 10.0):
        self.safety_threshold_km = safety_threshold_km
        
    def interpolate_iceberg(self, trajectory: List[Dict[str, Any]], target_time: datetime) -> Dict[str, Any]:
        """Interpolates iceberg position at a specific time."""
        # Simple nearest-time or linear interp
        if not trajectory:
            return None
            
        times = [datetime.fromisoformat(pt["forecast_timestamp"].replace("Z", "+00:00")).replace(tzinfo=None) for pt in trajectory]
        
        if target_time <= times[0]:
            return trajectory[0]
        if target_time >= times[-1]:
            return trajectory[-1]
            
        for i in range(len(times) - 1):
            if times[i] <= target_time <= times[i+1]:
                # Linear interpolate
                dt = (times[i+1] - times[i]).total_seconds()
                w = (target_time - times[i]).total_seconds() / dt
                pt1, pt2 = trajectory[i], trajectory[i+1]
                
                return {
                    "latitude": pt1["latitude"] + w * (pt2["latitude"] - pt1["latitude"]),
                    "longitude": pt1["longitude"] + w * (pt2["longitude"] - pt1["longitude"]),
                    "uncertainty_radius_km": pt1["uncertainty_radius_km"] + w * (pt2["uncertainty_radius_km"] - pt1["uncertainty_radius_km"]),
                    "drift_speed_ms": pt1["drift_speed_ms"]
                }
        return trajectory[-1]

    def analyze_hazards(self, vessel_path: List[Dict[str, Any]], icebergs: List[Dict[str, Any]]) -> Dict[str, Any]:
        hazards = []
        overall_min_clearance = float('inf')
        overall_min_cpa = float('inf')
        overall_tca = None
        overall_tca_iceberg = None
        
        for ib in icebergs:
            ice_id = ib.get("iceberg_id", "UNKNOWN")
            traj = ib.get("trajectory", [])
            if not traj:
                continue
                
            min_dist_tca = float('inf')
            tca_point_vessel = None
            tca_point_ice = None
            
            for v_pt in vessel_path:
                i_pt = self.interpolate_iceberg(traj, v_pt["time"])
                if i_pt is None:
                    continue
                    
                dist = haversine_distance(v_pt["lat"], v_pt["lon"], i_pt["latitude"], i_pt["longitude"])
                effective_clearance = dist - i_pt["uncertainty_radius_km"]

                if dist < overall_min_cpa:
                    overall_min_cpa = dist
                    overall_tca = v_pt["time"]
                    overall_tca_iceberg = ice_id
                
                if effective_clearance < min_dist_tca:
                    min_dist_tca = effective_clearance
                    tca_point_vessel = v_pt
                    tca_point_ice = i_pt
            
            if min_dist_tca <= self.safety_threshold_km:
                hazards.append({
                    "iceberg_id": ice_id,
                    "closest_approach_time": tca_point_vessel["time"].isoformat(),
                    "closest_approach_distance_km": round(min_dist_tca, 2),
                    "uncertainty_radius_km": round(tca_point_ice["uncertainty_radius_km"], 2),
                    "iceberg_speed_ms": round(tca_point_ice["drift_speed_ms"], 2),
                    "vessel_lat": tca_point_vessel["lat"],
                    "vessel_lon": tca_point_vessel["lon"],
                    "iceberg_lat": tca_point_ice["latitude"],
                    "iceberg_lon": tca_point_ice["longitude"]
                })
            
            if min_dist_tca < overall_min_clearance:
                overall_min_clearance = min_dist_tca

        # Backend-calculated route comparison series.  The frontend renders
        # these values but does not recompute CPA/hazard geometry.  Each sample
        # is the nearest real/modelled iceberg trajectory at the vessel ETA.
        clearance_series = []
        if vessel_path and icebergs:
            t0 = vessel_path[0]["time"]
            for v_pt in vessel_path:
                nearest = None
                for ib in icebergs:
                    traj = ib.get("trajectory", [])
                    if not traj:
                        continue
                    i_pt = self.interpolate_iceberg(traj, v_pt["time"])
                    if i_pt is None:
                        continue
                    raw_dist = haversine_distance(v_pt["lat"], v_pt["lon"], i_pt["latitude"], i_pt["longitude"])
                    uncertainty = float(i_pt.get("uncertainty_radius_km") or 0.0)
                    effective = raw_dist - uncertainty
                    candidate = {
                        "iceberg_id": ib.get("iceberg_id", "UNKNOWN"),
                        "cpa_km": raw_dist,
                        "effective_clearance_km": effective,
                        "uncertainty_radius_km": uncertainty,
                    }
                    if nearest is None or candidate["effective_clearance_km"] < nearest["effective_clearance_km"]:
                        nearest = candidate
                if nearest is not None:
                    clearance_series.append({
                        "elapsed_hours": round((v_pt["time"] - t0).total_seconds() / 3600.0, 3),
                        "timestamp_utc": v_pt["time"].isoformat(),
                        "vessel_lat": round(float(v_pt["lat"]), 6),
                        "vessel_lon": round(float(v_pt["lon"]), 6),
                        "nearest_iceberg_id": nearest["iceberg_id"],
                        "cpa_km": round(float(nearest["cpa_km"]), 2),
                        "effective_clearance_km": round(float(nearest["effective_clearance_km"]), 2),
                        "uncertainty_radius_km": round(float(nearest["uncertainty_radius_km"]), 2),
                    })
                
        # Prototype decision-support thresholds
        if overall_min_clearance <= 10.0:
            risk = "CRITICAL"
        elif overall_min_clearance <= 25.0:
            risk = "HIGH"
        elif overall_min_clearance <= 50.0:
            risk = "MODERATE"
        else:
            risk = "LOW"
            
        return {
            "overall_risk": risk,
            "min_effective_clearance_km": round(overall_min_clearance, 2) if overall_min_clearance != float('inf') else None,
            "minimum_cpa_km": round(overall_min_cpa, 2) if overall_min_cpa != float('inf') else None,
            "tca_utc": overall_tca.isoformat() if overall_tca is not None else None,
            "closest_iceberg_id": overall_tca_iceberg,
            "clearance_series": clearance_series,
            "hazards": hazards
        }


class RouteAlternativeEngine:
    """Generates and ranks route deviations when hazards are detected."""
    def __init__(self, safety_buffer_km: float = 15.0):
        self.safety_buffer_km = safety_buffer_km
        
    def generate_alternatives(self, original_route: List[Dict[str, float]], hazards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not hazards or len(original_route) < 2:
            return []
            
        start = original_route[0]
        end = original_route[-1]
        orig_dist = sum(haversine_distance(original_route[i]["lat"], original_route[i]["lon"], original_route[i+1]["lat"], original_route[i+1]["lon"]) for i in range(len(original_route)-1))
        
        alternatives = []
        for hazard in hazards:
            # Shift perpendicular to the hazard
            # Simple heuristic: shift longitude left and right
            lat = hazard["vessel_lat"]
            lon = hazard["vessel_lon"]
            
            # Alternative A: Shift 1 degree East
            alt_a = [{"lat": start["lat"], "lon": start["lon"]}, {"lat": lat, "lon": lon + 1.0}, {"lat": end["lat"], "lon": end["lon"]}]
            dist_a = haversine_distance(start["lat"], start["lon"], lat, lon+1.0) + haversine_distance(lat, lon+1.0, end["lat"], end["lon"])
            
            alternatives.append({
                "name": "Alternative Route A",
                "route": alt_a,
                "total_distance_km": round(dist_a, 2),
                "additional_distance_km": round(dist_a - orig_dist, 2),
                "reason": "Shifts route east to bypass the predicted uncertainty corridor.",
                "recommendation": "Recommended for further operator review"
            })
            
            # Alternative B: Shift 1 degree West
            alt_b = [{"lat": start["lat"], "lon": start["lon"]}, {"lat": lat, "lon": lon - 1.0}, {"lat": end["lat"], "lon": end["lon"]}]
            dist_b = haversine_distance(start["lat"], start["lon"], lat, lon-1.0) + haversine_distance(lat, lon-1.0, end["lat"], end["lon"])
            
            alternatives.append({
                "name": "Alternative Route B",
                "route": alt_b,
                "total_distance_km": round(dist_b, 2),
                "additional_distance_km": round(dist_b - orig_dist, 2),
                "reason": "Shifts route west to bypass the predicted uncertainty corridor.",
                "recommendation": "Recommended for further operator review"
            })
            
            break # Just generate from first major hazard for simplicity
            
        # Rank by shortest additional distance
        alternatives.sort(key=lambda x: x["additional_distance_km"])
        return alternatives
