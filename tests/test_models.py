import pytest
from datetime import datetime
import math
from src.models.trajectory import PhysicsTrajectoryModel, propagate_coordinate
from src.models.risk import NavigationRiskEngine, haversine_distance

def test_haversine_distance():
    # Example: Sydney to Melbourne roughly
    lat1, lon1 = -33.8688, 151.2093
    lat2, lon2 = -37.8136, 144.9631
    dist = haversine_distance(lat1, lon1, lat2, lon2)
    assert 700 < dist < 720  # km

def test_propagate_coordinate_dateline():
    lat1, lon1 = 0.0, 179.9
    # Move East roughly 111.19 km (1 degree)
    # Bearing East = pi/2
    lat2, lon2 = propagate_coordinate(lat1, lon1, distance_km=111.195, bearing_rad=math.pi/2)
    assert abs(lat2 - 0.0) < 0.1
    assert abs(lon2 - (-179.1)) < 0.2  # Crossed dateline

def test_propagate_coordinate_polar():
    lat1, lon1 = -89.5, 0.0
    # Move South 111.19 km -> Should cross pole and start moving North, lon flips to 180
    lat2, lon2 = propagate_coordinate(lat1, lon1, distance_km=111.195, bearing_rad=math.pi)
    assert lat2 > -90.0  # Actually -89.5 approximately on the other side
    assert abs(abs(lon2) - 180.0) < 0.1

def test_physics_model_direction_and_zero():
    model = PhysicsTrajectoryModel(alpha=1.0, beta=0.0)
    start_time = datetime(2026, 1, 1)
    
    # 1. Zero velocity
    res_zero = model.predict_trajectory("A1", -60.0, 0.0, start_time, {"ocean_u": 0.0, "ocean_v": 0.0}, [1])
    assert res_zero['trajectory'][0]['displacement_km'] == 0.0
    
    # 2. Eastward (u > 0, v = 0)
    res_e = model.predict_trajectory("A1", -60.0, 0.0, start_time, {"ocean_u": 1.0, "ocean_v": 0.0}, [1])
    traj_e = res_e['trajectory'][0]
    assert math.isclose(traj_e['math_angle_rad'], 0.0, abs_tol=1e-5)
    assert math.isclose(traj_e['compass_bearing_rad'], math.pi/2, abs_tol=1e-5)
    
    # 3. Northward (u = 0, v > 0)
    res_n = model.predict_trajectory("A1", -60.0, 0.0, start_time, {"ocean_u": 0.0, "ocean_v": 1.0}, [1])
    traj_n = res_n['trajectory'][0]
    assert math.isclose(traj_n['math_angle_rad'], math.pi/2, abs_tol=1e-5)
    assert math.isclose(traj_n['compass_bearing_rad'], 0.0, abs_tol=1e-5)
    
    # 4. Westward (u < 0, v = 0)
    res_w = model.predict_trajectory("A1", -60.0, 0.0, start_time, {"ocean_u": -1.0, "ocean_v": 0.0}, [1])
    traj_w = res_w['trajectory'][0]
    assert math.isclose(abs(traj_w['math_angle_rad']), math.pi, abs_tol=1e-5)
    assert math.isclose(traj_w['compass_bearing_rad'], 3*math.pi/2, abs_tol=1e-5)
    
    # 5. Southward (u = 0, v < 0)
    res_s = model.predict_trajectory("A1", -60.0, 0.0, start_time, {"ocean_u": 0.0, "ocean_v": -1.0}, [1])
    traj_s = res_s['trajectory'][0]
    assert math.isclose(traj_s['math_angle_rad'], -math.pi/2, abs_tol=1e-5)
    assert math.isclose(traj_s['compass_bearing_rad'], math.pi, abs_tol=1e-5)
    
    # Check uncertainty envelope
    assert traj_s['uncertainty_type'] == "heuristic/modelled uncertainty envelope"
    expected_uncert = 1.0 + 0.05 * traj_s['displacement_km']
    assert math.isclose(traj_s['uncertainty_radius_km'], expected_uncert, abs_tol=1e-5)

def test_risk_engine():
    engine = NavigationRiskEngine(critical_threshold_km=10.0, high_threshold_km=25.0, moderate_threshold_km=50.0)
    vessel_route = [{"lat": -61.0, "lon": 0.0}]
    
    # 1. Just inside critical boundary (e.g. 9.99 km): -> CRITICAL
    dist_needed = 9.99
    lat_diff = dist_needed / 111.195
    trajectory_crit = [{"latitude": -61.0 + lat_diff, "longitude": 0.0, "uncertainty_radius_km": 0.0}]
    risk_crit = engine.assess_risk(vessel_route, trajectory_crit)
    assert risk_crit["risk_level"] == "CRITICAL"
    
    # 2. Just inside high boundary (e.g. 24.99 km): -> HIGH
    dist_needed = 24.99
    lat_diff = dist_needed / 111.195
    trajectory_high = [{"latitude": -61.0 + lat_diff, "longitude": 0.0, "uncertainty_radius_km": 0.0}]
    risk_high = engine.assess_risk(vessel_route, trajectory_high)
    assert risk_high["risk_level"] == "HIGH"
    
    # 3. Barely outside moderate boundary: effective distance = 50.001 -> LOW
    dist_needed = 50.01
    lat_diff = dist_needed / 111.195
    trajectory_low = [{"latitude": -61.0 + lat_diff, "longitude": 0.0, "uncertainty_radius_km": 0.0}]
    risk_low = engine.assess_risk(vessel_route, trajectory_low)
    assert risk_low["risk_level"] == "LOW"

from fastapi.testclient import TestClient
from src.api.main import app
client = TestClient(app)

def test_trajectory_api():
    response = client.post("/api/prediction/trajectory?iceberg_id=A1&lat=-60&lon=0&ocean_u=0.5&ocean_v=-0.5")
    assert response.status_code == 200
    data = response.json()
    assert data["iceberg_id"] == "A1"
    assert len(data["trajectory"]) == 5 # 6, 12, 24, 48, 72

def test_risk_api():
    pred = {
        "trajectory": [
            {"latitude": -60.0, "longitude": 0.0, "uncertainty_radius_km": 5.0}
        ]
    }
    route = [{"lat": -60.05, "lon": 0.0}]
    
    response = client.post("/api/navigation/risk", json={"prediction_data": pred, "vessel_route": route})
    assert response.status_code == 200
    assert response.json()["risk_level"] in ["CRITICAL", "HIGH"]
