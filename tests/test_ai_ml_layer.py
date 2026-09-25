from fastapi.testclient import TestClient

from src.api.main import app, iceberg_ml, _attach_ml_prior
from src.ai.decision_engine import build_decision_report


def test_trained_iceberg_ml_model_is_available_and_gated():
    status = iceberg_ml.public_status()
    assert status["trained"] is True
    assert status["training_samples"] >= 20
    assert status["validation"]["hybrid_endpoint_mae_km"] < status["validation"]["physics_endpoint_mae_km"]
    assert status["runtime_enabled"] is True


def test_ml_prior_attaches_to_physics_motion_without_fabricating_observation():
    motion, meta = _attach_ml_prior(
        {"available": False, "history_points": 1},
        "A76C", -53.29, -26.88,
        {"ocean_u": 0.1, "ocean_v": -0.03, "wind_u": 4.0, "wind_v": 1.0},
    )
    assert meta["available"] is True
    assert meta["applied"] is True
    assert motion["ml_prior_applied"] is True
    assert motion["available"] is False  # still no fabricated observed motion


def test_ai_status_endpoint_exposes_structured_decision_layer():
    client = TestClient(app)
    data = client.get("/api/ai/status").json()
    assert data["iceberg_drift"]["trained"] is True
    assert data["decision_layer"]["generative_llm"] is False
    assert data["decision_layer"]["chat_interface"] is False
    assert "No supervised risk ML" in data["risk_engine"]["ml_claim"]


def test_decision_layer_refuses_recommendation_without_route_evidence():
    out = build_decision_report({}, {"iceberg_drift": {}, "ais_anomaly": {}})
    assert out["generative_llm"] is False
    assert out["readiness"] == "NO_ROUTE_EVIDENCE"
    assert out["recommendation"] is None


def test_decision_layer_uses_only_supplied_route_metrics():
    context = {
        "route_result": {
            "recommended_profile": "SAFEST",
            "routes": [
                {"profile": "FASTEST", "available": True, "distance_km": 100, "eta_hours": 5, "risk": "HIGH", "risk_score": 70, "min_clearance_km": 12, "minimum_cpa_km": 10, "hazards": [{"id": 1}], "sea_ice": {"maximum_concentration_percent": 44}},
                {"profile": "BALANCED", "available": True, "distance_km": 108, "eta_hours": 5.5, "risk": "MODERATE", "risk_score": 42, "min_clearance_km": 25, "minimum_cpa_km": 21, "hazards": [], "sea_ice": {"maximum_concentration_percent": 31}},
                {"profile": "SAFEST", "available": True, "distance_km": 116, "eta_hours": 6, "risk": "LOW", "risk_score": 20, "min_clearance_km": 39, "minimum_cpa_km": 34, "hazards": [], "sea_ice": {"maximum_concentration_percent": 18}},
            ],
        }
    }
    out = build_decision_report(context, {"iceberg_drift": {"runtime_enabled": True}, "ais_anomaly": {}})
    assert out["readiness"] == "READY"
    assert out["recommendation"]["profile"] == "SAFEST"
    assert out["recommendation"]["risk_score"] == 20
    assert any("Lowest available backend risk score" in reason for reason in out["reasons"])
    assert any("ETA trade-off" in tradeoff for tradeoff in out["tradeoffs"])


def test_decision_support_api_returns_structured_report():
    client = TestClient(app)
    response = client.post("/api/ai/decision-support", json={"context": {}})
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "STRUCTURED_EXPLAINABLE_DECISION_SUPPORT"
    assert data["recommendation"] is None
