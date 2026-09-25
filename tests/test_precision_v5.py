from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.api.main import app
from src.models.precision_trajectory import PrecisionIcebergTrajectoryModel
from src.data_providers.forecast_forcing import fallback_constant_series

client = TestClient(app)


def test_precision_model_nowcast_and_ensemble_spread():
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    obs = now - timedelta(hours=12)
    model = PrecisionIcebergTrajectoryModel(windage=0.0)
    controls = [obs]
    series = fallback_constant_series(
        {"ocean_u": 0.2, "ocean_v": 0.0, "wind_u": 0.0, "wind_v": 0.0},
        [(-60.0, 0.0)],
    )
    result = model.build_result(
        iceberg_id="TEST",
        start_lat=-60.0,
        start_lon=0.0,
        observation_time=obs,
        now=now,
        horizons_hours=[6, 12],
        control_times=controls,
        control_series=series,
        observed_motion={"available": False},
        forcing_metadata={"online": False, "source": "TEST", "current_resolution_note": "test"},
        ensemble_members=12,
        source_position_resolution_km=1.0,
    )
    assert result["nowcast"]["longitude"] > 0.0
    assert result["nowcast"]["spread_p90_km"] is not None
    assert result["trajectory"][0]["spread_p90_km"] is not None
    assert result["precision_budget"]["observation_time_ambiguity_hours"] == 12.0
    assert result["quality"]["validated_navigation_accuracy"] is False


def test_precision_trajectory_manual_api_reports_quality():
    r = client.post(
        "/api/prediction/trajectory?iceberg_id=A76C&lat=-53.73&lon=-29.5&"
        "observation_date=09/05/2026&ocean_u=0.1&ocean_v=0.05&wind_u=2&wind_v=1"
    )
    assert r.status_code == 200
    data = r.json()
    assert data["model_version"].startswith("5.1")
    assert data["nowcast"]["status"] == "MODEL_NOWCAST_FROM_LATEST_USNIC_FIX"
    assert len(data["trajectory"]) == 5
    assert "precision_budget" in data


def test_iceberg_history_endpoint_never_invents_points():
    r = client.get("/api/data/icebergs/A76C/history")
    assert r.status_code == 200
    data = r.json()
    assert data["iceberg_id"] == "A76C"
    assert data["count"] == len(data["observations"])
    for p in data["observations"]:
        assert p["position_type"] == "OFFICIAL_USNIC_TABLE_FIX"

