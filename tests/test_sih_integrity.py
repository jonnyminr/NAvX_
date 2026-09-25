from pathlib import Path
import time

from fastapi.testclient import TestClient

from src.api.main import app
from src.data_providers.realtime_provider import AISStreamTracker

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "api" / "static" / "index.html").read_text(encoding="utf-8")


def test_map_config_is_keyless_and_never_returns_provider_secret():
    r = client.get("/api/config/map")
    assert r.status_code == 200
    data = r.json()
    assert "api_key" not in data
    assert "key" not in data
    assert data["enabled"] is True
    assert data["requires_api_key"] is False
    assert data["credential_exposure"] == "NONE"
    assert data["mode"] == "KEYLESS_WITH_FALLBACK"
    assert data["style_url"].startswith("https://tiles.openfreemap.org/")
    assert data["fallback_style_url"] == "/api/map/style"


def test_frontend_uses_keyless_map_styles_not_api_keys():
    assert "state.mapConfig.style_url" in HTML
    assert "state.mapConfig.fallback_style_url" in HTML
    assert "state.mapConfig.api_key" not in HTML
    assert "MAPTILER_API_KEY=" not in HTML
    assert "MAPTILER_BROWSER_KEY=" not in HTML
    assert "AISSTREAM_API_KEY=" not in HTML
    assert "OpenFreeMap" in HTML
    assert "OpenStreetMap fallback" in HTML


def test_location_selector_and_map_pick_contract_present():
    assert 'id="startPreset"' in HTML
    assert 'id="destinationPreset"' in HTML
    assert "beginMapPick('origin')" in HTML
    assert "beginMapPick('destination')" in HTML
    assert "/api/navigation/surface-check" in HTML


def test_gps_is_user_controlled_and_handles_secure_context():
    assert "navigator.geolocation.getCurrentPosition" in HTML
    assert "navigator.geolocation.watchPosition" in HTML
    assert "navigator.geolocation.clearWatch" in HTML
    assert "enableHighAccuracy:true" in HTML
    assert "GPS requires HTTPS or localhost" in HTML
    # Live tracking must not start automatically during boot.
    boot = HTML.split("async function boot()", 1)[1].split("window.addEventListener('hashchange'", 1)[0]
    assert "startGpsTracking()" not in boot
    assert "useGpsOnce()" not in boot


def test_surface_check_rejects_known_station_land_reference():
    # Maitri is intentionally retained as an authoritative reference coordinate,
    # but it is inland and therefore cannot be a ship route endpoint.
    r = client.get("/api/navigation/surface-check", params={"lat": -70.764444, "lon": 11.734167})
    assert r.status_code == 200
    data = r.json()
    assert data["navigable"] is False
    assert "INVALID" in data["message"]


def test_surface_check_accepts_verified_open_ocean_cell():
    r = client.get("/api/navigation/surface-check", params={"lat": -60.0, "lon": -56.0})
    assert r.status_code == 200
    data = r.json()
    assert data["navigable"] is True
    assert data["source"] == "CMEMS + NSIDC RealOceanSurface"


def test_optimizer_returns_backend_comparison_metrics_only_for_real_routes():
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
    assert len(data["comparison_metrics"]) == 3
    assert all(m["profile"] in {"FASTEST", "BALANCED", "SAFEST"} for m in data["comparison_metrics"])
    assert all(m["distance_km"] is not None for m in data["comparison_metrics"] if m["available"])
    assert all(route["fallback_direct"] is False for route in data["routes"] if route.get("available"))


def test_invalid_navigation_endpoint_never_returns_synthetic_route():
    payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        # This point resolves to a non-ocean CMEMS cell in the bundled real grid.
        "destination": {"lat": -62.0, "lon": -58.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "icebergs": [],
    }
    r = client.post("/api/navigation/optimize", json=payload)
    assert r.status_code == 422
    data = r.json()
    assert data["routes"]
    assert all(route.get("available") is False for route in data["routes"])
    assert all(route.get("route") == [] for route in data["routes"])


def test_ais_freshness_transitions_to_stale_without_fabricating_position():
    tracker = AISStreamTracker("test-key")
    tracker._consume({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 123123123, "ShipName": "VERIFIED AIS TEST", "Latitude": -61.0, "Longitude": 20.0},
        "Message": {"PositionReport": {"Sog": 5.0, "Cog": 90.0, "TrueHeading": 90, "PositionAccuracy": True}},
    })
    vessel_state = tracker.vessels["123123123"]
    vessel_state.last_seen_epoch = time.time() - 20 * 60
    snap = tracker.snapshot(max_age_minutes=30)
    assert snap["count"] == 1
    vessel = snap["vessels"][0]
    assert vessel["freshness"] == "STALE"
    assert vessel["lat"] == -61.0
    assert vessel["lon"] == 20.0


def test_route_selection_and_graph_render_from_backend_fields():
    assert "function selectProfile" in HTML
    assert "state.routeResult?.comparison_metrics" in HTML
    assert "minimum_cpa_km" in HTML
    assert "NO VERIFIED ROUTE DATA AVAILABLE" in HTML
    assert "renderAllRoutes" in HTML
    assert "fitAllRoutes" in HTML


def test_sea_ice_graph_uses_official_endpoint():
    assert "/api/data/ice-extent-trends" in HTML
    assert "2026 YTD" in HTML
    assert "climo_10yr" in HTML


def test_config_and_status_endpoints_never_echo_environment_secrets(monkeypatch):
    ais_secret = "TEST_AIS_SECRET_DO_NOT_ECHO"
    mappls_secret = "TEST_MAPPLS_SECRET_DO_NOT_ECHO"
    monkeypatch.setenv("AISSTREAM_API_KEY", ais_secret)
    monkeypatch.setenv("MAPPLS_STATIC_KEY", mappls_secret)
    for path in ("/api/config/map", "/api/map/style", "/api/system/health", "/api/system/provenance"):
        r = client.get(path)
        assert r.status_code == 200
        text = r.text
        assert ais_secret not in text
        assert mappls_secret not in text


def test_planning_input_changes_invalidate_old_route_analysis():
    assert "function invalidateRoute" in HTML
    assert "Recalculate routes before using route metrics" in HTML
    assert "Scientific data refreshed" in HTML
    for field_id in ("vesselType", "shipSpeed", "departureTime", "searchRadius", "safetyBuffer"):
        assert f"'{field_id}'" in HTML


def test_keyless_map_works_without_any_map_credentials(monkeypatch):
    for name in ("MAPPLS_STATIC_KEY",):
        monkeypatch.delenv(name, raising=False)
    r = client.get("/api/config/map")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True
    assert data["requires_api_key"] is False
    assert data["mode"] == "KEYLESS_WITH_FALLBACK"
    assert data["credential_exposure"] == "NONE"


def test_keyless_fallback_style_uses_official_osm_tile_endpoint():
    r = client.get("/api/map/style")
    assert r.status_code == 200
    data = r.json()
    src = data["sources"]["osm"]
    assert src["tiles"] == ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]
    assert "OpenStreetMap contributors" in src["attribution"]
    assert data["layers"][0]["source"] == "osm"


def test_legacy_map_tile_proxy_is_retired_explicitly():
    r = client.get("/api/map/tiles/1/1/1")
    assert r.status_code == 410
    assert "retired" in r.json()["detail"].lower()


def test_optimizer_rejects_invalid_speed_instead_of_clamping():
    payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 0,
        "safety_threshold_km": 25.0,
        "icebergs": [],
    }
    r = client.post("/api/navigation/optimize", json=payload)
    assert r.status_code == 400
    assert "between 1 and 70" in r.json()["error"]


def test_optimizer_rejects_invalid_departure_timestamp():
    payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "departure_utc": "not-a-date",
        "icebergs": [],
    }
    r = client.post("/api/navigation/optimize", json=payload)
    assert r.status_code == 400
    assert "ISO-8601" in r.json()["error"]


def test_optimizer_never_wraps_or_swaps_invalid_longitude():
    payload = {
        "origin": {"lat": -58.0, "lon": 248.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "icebergs": [],
    }
    r = client.post("/api/navigation/optimize", json=payload)
    assert r.status_code == 400
    assert "not auto-swapped" in r.json()["error"]


def test_route_comparison_contains_bearing_arrival_and_clearance_fields():
    payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "icebergs": [],
    }
    r = client.post("/api/navigation/optimize", json=payload)
    assert r.status_code == 200
    for row in r.json()["comparison_metrics"]:
        assert "initial_bearing_deg" in row
        assert "arrival_utc" in row
        assert "min_effective_clearance_km" in row


def test_frontend_map_click_defaults_to_destination_and_follow_gps_is_real_state():
    assert "const kind=state.pickMode||'destination'" in HTML
    assert "function toggleFollowGps" in HTML
    assert "Follow GPS: ${state.followGps?'On':'Off'}" in HTML
    assert "mode==='SINGLE'||state.followGps" in HTML
    assert "state.suppressNextMapClick=true" in HTML


def test_frontend_rejects_invalid_operator_inputs_instead_of_silent_fallbacks():
    assert "Vessel speed must be a number between 1 and 70 km/h." in HTML
    assert "Departure date/time is required." in HTML
    assert "Departure date/time is invalid." in HTML
    assert "lon:Number(q(kind==='origin'?'originLon':'destinationLon').value)" in HTML


def test_bundled_scientific_overlay_assets_are_served():
    for path in (
        "/app/overlays/currents.json",
        "/app/overlays/wind.json",
        "/app/overlays/sea_ice_bounds.json",
        "/app/overlays/sea_ice.png",
    ):
        r = client.get(path)
        assert r.status_code == 200
        assert r.content


def test_navigation_routes_alias_uses_same_verified_optimizer_contract():
    payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "icebergs": [],
    }
    r = client.post("/api/navigation/routes", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert len(data["routes"]) == 3
    assert all(route.get("fallback_direct") is False for route in data["routes"] if route.get("available"))


def test_frontend_has_maplibre_secondary_cdn_fallback_and_keyless_basemap_fallback():
    assert "cdn.jsdelivr.net/npm/maplibre-gl@6.7.0/dist/maplibre-gl.mjs" in HTML
    assert "Map library could not be loaded" in HTML
    assert "switchToFallbackMap" in HTML
    r = client.get("/api/config/map")
    assert r.status_code == 200
    data = r.json()
    assert data["provider"].startswith("OpenFreeMap")
    assert data["fallback_style_url"] == "/api/map/style"


def test_bundled_official_usnic_forecast_to_ocean_safe_route_chain():
    """End-to-end real-data chain: official observation -> cached forcing forecast -> verified route metrics."""
    ice = client.get("/api/data/icebergs")
    assert ice.status_code == 200
    payload = ice.json()
    assert payload.get("source") == "USNIC"
    feature = next((f for f in payload["icebergs"]["features"] if f.get("properties", {}).get("id") == "A81"), None)
    assert feature is not None
    lon, lat = feature["geometry"]["coordinates"]
    observed = feature["properties"].get("date_observed") or ""

    forecast = client.post(
        "/api/prediction/trajectory",
        params={"iceberg_id": "A81", "lat": lat, "lon": lon, "observation_date": observed},
    )
    assert forecast.status_code == 200
    fj = forecast.json()
    assert len(fj.get("trajectory") or []) >= 5
    assert str((fj.get("forcing") or {}).get("source", "")).startswith("REAL ")
    assert fj.get("quality", {}).get("validated_navigation_accuracy") is False

    route_payload = {
        "origin": {"lat": -58.0, "lon": -48.0},
        "destination": {"lat": -62.0, "lon": -56.0},
        "speed_kmh": 20.0,
        "safety_threshold_km": 25.0,
        "departure_utc": "2026-09-07T15:00:00Z",
        "icebergs": [{
            "iceberg_id": "A81",
            "trajectory": fj["trajectory"],
            "meta": fj,
            "observed": {"id": "A81", "lat": lat, "lon": lon, "observed": observed},
        }],
    }
    routes = client.post("/api/navigation/optimize", json=route_payload)
    assert routes.status_code == 200
    rj = routes.json()
    assert rj.get("verified_iceberg_forecast_count") == 1
    assert len(rj.get("routes") or []) == 3
    for route in rj["routes"]:
        if route.get("available"):
            assert route.get("fallback_direct") is False
            assert route.get("route_geometry") == "OCEAN_MASKED_POLAR_ASTAR_GEODESIC"
            assert route.get("risk") != "INSUFFICIENT_VERIFIED_DATA"
            assert route.get("sea_ice", {}).get("source") == "NSIDC/NOAA G02135"
