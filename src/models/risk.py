import math
from typing import Dict, Any, List

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.01
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

class NavigationRiskEngine:
    """
    Transparent rule-based risk engine for Antarctic Navigation.
    Assesses intersection of predicted iceberg uncertainty cones with vessel routes.
    """
    def __init__(self, critical_threshold_km: float = 10.0, high_threshold_km: float = 25.0, moderate_threshold_km: float = 50.0):
        self.critical_threshold_km = critical_threshold_km
        self.high_threshold_km = high_threshold_km
        self.moderate_threshold_km = moderate_threshold_km
        
    def assess_risk(self, vessel_route: List[Dict[str, float]], iceberg_trajectory: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculates minimum distance between vessel route and predicted iceberg trajectory.
        Outputs deterministic Risk Level (LOW, MODERATE, HIGH, CRITICAL) and actionable deviation.
        """
        min_distance = float('inf')
        risk_point = None
        iceberg_point = None
        
        for v_point in vessel_route:
            for t_point in iceberg_trajectory:
                dist = haversine_distance(v_point['lat'], v_point['lon'], t_point['latitude'], t_point['longitude'])
                # Factor in the uncertainty cone
                effective_dist = max(0, dist - t_point['uncertainty_radius_km'])
                
                if effective_dist < min_distance:
                    min_distance = effective_dist
                    risk_point = v_point
                    iceberg_point = t_point
                    
        # Classify Risk
        if min_distance <= self.critical_threshold_km:
            risk_level = "CRITICAL"
            reason = f"Predicted iceberg corridor intersects route within critical safety threshold ({min_distance:.1f} km). Imminent collision risk."
            deviation = f"Deviation required: Route must shift at least {self.critical_threshold_km - min_distance + 5:.1f} km away from intersection."
        elif min_distance <= self.high_threshold_km:
            risk_level = "HIGH"
            reason = f"Predicted iceberg corridor intersects route within high safety threshold ({min_distance:.1f} km)."
            deviation = f"Deviation recommended: Shift route {self.high_threshold_km - min_distance + 2:.1f} km."
        elif min_distance <= self.moderate_threshold_km:
            risk_level = "MODERATE"
            reason = f"Predicted iceberg corridor approaches route ({min_distance:.1f} km). Heightened monitoring advised."
            deviation = "Maintain current route. Increase radar monitoring."
        else:
            risk_level = "LOW"
            reason = f"Iceberg corridor remains safely distant ({min_distance:.1f} km)."
            deviation = "No deviation required."
            
        return {
            "risk_level": risk_level,
            "min_effective_distance_km": min_distance,
            "reason": reason,
            "recommendation": deviation,
            "intersection_point": risk_point,
            "iceberg_forecast_point": iceberg_point
        }
