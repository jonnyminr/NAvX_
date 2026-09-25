import pytest
from datetime import datetime, timedelta
from src.models.navigation import VesselSimulator, SpatiotemporalHazardAnalyzer, RouteAlternativeEngine, DataFreshnessChecker
from src.models.risk import haversine_distance

def test_vessel_simulator():
    sim = VesselSimulator(speed_kmh=111.195) # 1 degree per hour approx
    start_time = datetime(2026, 1, 1, 0, 0, 0)
    route = [{"lat": -60.0, "lon": 0.0}, {"lat": -61.0, "lon": 0.0}]
    
    path = sim.interpolate_route(route, start_time, time_step_hours=0.5)
    assert len(path) == 3 # 0h, 0.5h, 1.0h
    
    assert path[0]["lat"] == -60.0
    assert abs(path[1]["lat"] - (-60.5)) < 0.1
    time_diff = abs((path[1]["time"] - (start_time + timedelta(hours=0.5))).total_seconds())
    assert time_diff < 1.0  # within 1 second
    
def test_data_freshness():
    checker = DataFreshnessChecker(stale_threshold_hours=48)
    
    # Fresh (now)
    res1 = checker.check_freshness("Test", datetime.utcnow().isoformat())
    assert res1["is_stale"] is False
    assert "CACHED" in res1["status"]
    
    # Stale (72 hours ago)
    stale_time = (datetime.utcnow() - timedelta(hours=72)).isoformat()
    res2 = checker.check_freshness("Test", stale_time)
    assert res2["is_stale"] is True
    assert "STALE" in res2["status"]

def test_hazard_analyzer_spatiotemporal():
    analyzer = SpatiotemporalHazardAnalyzer(safety_threshold_km=25.0)
    
    # Vessel moves South at 1 degree/hour
    sim = VesselSimulator(speed_kmh=111.195)
    start_time = datetime(2026, 1, 1, 0, 0, 0)
    route = [{"lat": -60.0, "lon": 0.0}, {"lat": -62.0, "lon": 0.0}]
    vessel_path = sim.interpolate_route(route, start_time, time_step_hours=1.0)
    
    # Adversarial Case 1: Iceberg is close initially, but moves away (Safe)
    iceberg1 = {
        "iceberg_id": "IB-001",
        "trajectory": [
            {"forecast_timestamp": (start_time).isoformat(), "latitude": -60.0, "longitude": 0.2, "uncertainty_radius_km": 1.0, "drift_speed_ms": 1.0}, # Roughly 11km away initially
            {"forecast_timestamp": (start_time + timedelta(hours=2)).isoformat(), "latitude": -58.0, "longitude": 0.2, "uncertainty_radius_km": 1.0, "drift_speed_ms": 1.0} # Moving North while vessel moves South
        ]
    }
    # Wait, initial is at -60.0, 0.2 which is ~11km away. Vessel starts at -60.0, 0.0. 
    # If safety threshold is 25km, this is a hazard initially.
    # Let's adjust safety to 10km so initially it's SAFE, but we want to test if it intersects later.
    
    analyzer.safety_threshold_km = 10.0
    
    # Adversarial Case 2: Iceberg is far initially, but moves into path at exactly T=1h
    iceberg2 = {
        "iceberg_id": "IB-002",
        "trajectory": [
            {"forecast_timestamp": (start_time).isoformat(), "latitude": -61.0, "longitude": 1.0, "uncertainty_radius_km": 0.0, "drift_speed_ms": 1.0}, # Very far
            {"forecast_timestamp": (start_time + timedelta(hours=1)).isoformat(), "latitude": -61.0, "longitude": 0.0, "uncertainty_radius_km": 0.0, "drift_speed_ms": 1.0} # Exact hit at T=1
        ]
    }
    
    # Adversarial Case 3: Completely Safe Route
    iceberg3 = {
        "iceberg_id": "IB-003",
        "trajectory": [
            {"forecast_timestamp": start_time.isoformat(), "latitude": -50.0, "longitude": -50.0, "uncertainty_radius_km": 0.0, "drift_speed_ms": 1.0}
        ]
    }

    report = analyzer.analyze_hazards(vessel_path, [iceberg2, iceberg3])
    
    assert report["overall_risk"] == "CRITICAL"
    assert len(report["hazards"]) == 1
    assert report["hazards"][0]["iceberg_id"] == "IB-002"
    assert report["hazards"][0]["closest_approach_distance_km"] < 1.0

def test_route_alternative():
    router = RouteAlternativeEngine()
    route = [{"lat": -60.0, "lon": 0.0}, {"lat": -62.0, "lon": 0.0}]
    hazards = [{"vessel_lat": -61.0, "vessel_lon": 0.0}]
    
    alts = router.generate_alternatives(route, hazards)
    assert len(alts) == 2
    assert "Alternative Route A" in [a["name"] for a in alts]
    assert "Alternative Route B" in [a["name"] for a in alts]
    
    # Original dist = ~222 km. Deviating 1 degree E/W will increase it.
    assert alts[0]["additional_distance_km"] > 0
    assert "Recommended for further operator review" in alts[0]["recommendation"]

from fastapi.testclient import TestClient
from src.api.main import app
client = TestClient(app)

def test_analyze_api():
    payload = {
        "vessel": {"speed_kmh": 20.0},
        "route": [{"lat": -60.0, "lon": 0.0}, {"lat": -60.1, "lon": 0.0}],
        "safety_threshold": 10.0,
        "icebergs": [
            {
                "iceberg_id": "TEST",
                "trajectory": [
                    {
                        "forecast_timestamp": datetime.utcnow().isoformat(),
                        "latitude": -60.05,
                        "longitude": 0.0,
                        "uncertainty_radius_km": 0.0,
                        "drift_speed_ms": 0.1
                    }
                ]
            }
        ]
    }
    
    response = client.post("/api/navigation/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["overall_risk"] == "CRITICAL"
    # Analysis must not invent heuristic detours. Operational alternatives are
    # generated only by the RealOceanSurface-validated optimizer.
    assert data["alternatives"] == []
    assert data["alternative_route_status"] == "NOT_GENERATED_HERE_USE_OCEAN_SAFE_OPTIMIZER"
