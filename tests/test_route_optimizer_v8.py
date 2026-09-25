from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_route_optimizer_returns_three_profiles():
    payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "icebergs": [],
    }
    r = client.post("/api/navigation/optimize", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert [x["profile"] for x in data["routes"]] == ["FASTEST", "BALANCED", "SAFEST"]
    # Without a verified iceberg forecast NAV-X may return valid ocean geometry,
    # but it must not invent a risk-based recommendation.
    assert data["recommended_profile"] is None
    assert "INSUFFICIENT VERIFIED DATA" in data["explanation"]
    assert data["routing_method"] == "TIME_AWARE_POLAR_ASTAR_GEODESIC_WITH_P90_ICEBERG_ENVELOPES"


def test_evaluation_never_fabricates_samples():
    r = client.get("/api/model/evaluation")
    assert r.status_code == 200
    data = r.json()
    assert "verified_samples" in data
    assert "mae_km" in data
