import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

# Earth radius in kilometers
R_EARTH = 6371.01

def propagate_coordinate(lat: float, lon: float, distance_km: float, bearing_rad: float) -> Tuple[float, float]:
    """
    Propagate a coordinate forward using spherical kinematics (Haversine-based destination point).
    Assumes bearing_rad is clockwise from geographic North.
    """
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    
    d_over_r = distance_km / R_EARTH
    
    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(d_over_r) +
        math.cos(lat_rad) * math.sin(d_over_r) * math.cos(bearing_rad)
    )
    
    new_lon_rad = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(d_over_r) * math.cos(lat_rad),
        math.cos(d_over_r) - math.sin(lat_rad) * math.sin(new_lat_rad)
    )
    
    new_lon_deg = (math.degrees(new_lon_rad) + 540.0) % 360.0 - 180.0
    return math.degrees(new_lat_rad), new_lon_deg


class TrajectoryModel(ABC):
    """Base class for iceberg trajectory forecasting models."""
    @abstractmethod
    def predict_trajectory(self, iceberg_id: str, start_lat: float, start_lon: float, start_time: datetime, env_data: Dict[str, Any], horizons_hours: List[int]) -> Dict[str, Any]:
        pass


class PhysicsTrajectoryModel(TrajectoryModel):
    """
    Physics-informed kinematic drift model.
    Uses configurable environmental coupling coefficients (these are NOT measured physical constants).
    Assumptions:
      - Iceberg velocity = (alpha * Ocean_Velocity) + (beta * Wind_Velocity)
      - alpha = 1.0 (configurable model parameter / initial assumption)
      - beta = 0.02 (configurable model parameter / initial assumption)
    """
    def __init__(self, alpha: float = 1.0, beta: float = 0.02):
        self.alpha = alpha
        self.beta = beta
        self.version = "1.0-PhysicsKinematic"
        
    def predict_trajectory(self, iceberg_id: str, start_lat: float, start_lon: float, start_time: datetime, env_data: Dict[str, Any], horizons_hours: List[int]) -> Dict[str, Any]:
        # Extract environmental forcing (defaults to 0 if missing/masked)
        uo = env_data.get('ocean_u', 0.0)
        vo = env_data.get('ocean_v', 0.0)
        wu = env_data.get('wind_u', 0.0)
        wv = env_data.get('wind_v', 0.0)
        
        # Calculate iceberg drift velocity components
        ice_u = (self.alpha * uo) + (self.beta * wu)
        ice_v = (self.alpha * vo) + (self.beta * wv)
        
        # Calculate drift speed
        drift_speed_ms = math.sqrt(ice_u**2 + ice_v**2)
        
        # Separate mathematical angle (CCW from East) and compass bearing (CW from North)
        math_angle_rad = math.atan2(ice_v, ice_u)
        compass_bearing_rad = (math.pi / 2.0) - math_angle_rad
        if compass_bearing_rad < 0:
            compass_bearing_rad += 2 * math.pi
        
        trajectory = []
        current_lat = start_lat
        current_lon = start_lon
        
        for h in horizons_hours:
            # Displacement = speed * time
            distance_km = drift_speed_ms * (h * 3600) / 1000.0
            
            # Heuristic/modelled uncertainty envelope
            uncertainty_radius_km = 1.0 + (0.05 * distance_km)
            
            new_lat, new_lon = propagate_coordinate(current_lat, current_lon, distance_km, compass_bearing_rad)
            
            trajectory.append({
                "horizon_hours": h,
                "forecast_timestamp": (start_time + timedelta(hours=h)).isoformat(),
                "latitude": new_lat,
                "longitude": new_lon,
                "displacement_km": distance_km,
                "drift_speed_ms": drift_speed_ms,
                "math_angle_rad": math_angle_rad,
                "compass_bearing_rad": compass_bearing_rad,
                "uncertainty_radius_km": uncertainty_radius_km,
                "uncertainty_type": "heuristic/modelled uncertainty envelope"
            })
            
        return {
            "iceberg_id": iceberg_id,
            "initial_latitude": start_lat,
            "initial_longitude": start_lon,
            "model_version": self.version,
            "coefficients_note": "Configurable model parameters, NOT universal constants",
            "coefficients": {"alpha_ocean": self.alpha, "beta_wind": self.beta},
            "ocean_contribution_ms": math.sqrt((self.alpha*uo)**2 + (self.alpha*vo)**2),
            "wind_contribution_ms": math.sqrt((self.beta*wu)**2 + (self.beta*wv)**2),
            "trajectory": trajectory
        }
