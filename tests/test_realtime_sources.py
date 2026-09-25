from src.data_providers.realtime_provider import parse_usnic_csv, AISStreamTracker


def test_usnic_parser_preserves_official_rows_and_source_precision():
    raw = b"Iceberg,Length (NM),Width (NM),Latitude,Longitude,Area (sqNM),Area (sqKM),Last Update\nA99,12,5,-65.25,-44.50,55.2,189.3,09/01/2026\n"
    data = parse_usnic_csv(raw)
    assert len(data["features"]) == 1
    p = data["features"][0]["properties"]
    assert p["id"] == "A99"
    assert p["lat"] == -65.25
    assert p["lon"] == -44.5
    assert p["source_lat_text"] == "-65.25"
    assert p["source_lon_text"] == "-44.50"
    assert p["area_sqnm"] == 55.2
    assert p["position_type"] == "OFFICIAL_OBSERVATION"


def test_ais_tracker_sanitizes_position_message():
    tracker = AISStreamTracker("test-key")
    tracker._consume({
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": 123456789,
            "ShipName": "RESEARCH VESSEL",
            "Latitude": -64.1234,
            "Longitude": -55.4321,
        },
        "Message": {
            "PositionReport": {
                "Sog": 8.5,
                "Cog": 220.0,
                "TrueHeading": 219,
                "PositionAccuracy": True,
            }
        },
    })
    snap = tracker.snapshot(max_age_minutes=5)
    assert snap["enabled"] is True
    assert snap["count"] == 1
    vessel = snap["vessels"][0]
    assert vessel["mmsi"] == "123456789"
    assert vessel["name"] == "RESEARCH VESSEL"
    assert vessel["lat"] == -64.1234
    assert vessel["position_accuracy"] is True


def test_ais_tracker_builds_real_position_trail_and_freshness():
    tracker = AISStreamTracker("test-key")
    for lat, lon in [(-61.0, 20.0), (-61.01, 20.02)]:
        tracker._consume({
            "MessageType": "PositionReport",
            "MetaData": {"MMSI": 987654321, "ShipName": "POLAR TEST", "Latitude": lat, "Longitude": lon},
            "Message": {"PositionReport": {"Sog": 7.2, "Cog": 123.4, "TrueHeading": 124, "PositionAccuracy": True}},
        })
    snap = tracker.snapshot(max_age_minutes=5)
    vessel = snap["vessels"][0]
    assert vessel["freshness"] == "LIVE"
    assert vessel["zone"] == "ANTARCTIC"
    assert len(vessel["trail"]) >= 2
    assert vessel["trail"][-1]["lat"] == -61.01


def test_ais_tracker_does_not_create_position_from_static_message_only():
    tracker = AISStreamTracker("test-key")
    tracker._consume({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 111222333, "ShipName": "STATIC ONLY"},
        "Message": {"ShipStaticData": {"CallSign": "TEST", "Destination": "ANTARCTICA"}},
    })
    assert tracker.snapshot(max_age_minutes=5)["count"] == 0


def test_aisstream_snapshot_accepts_manager_area_kwargs_without_error():
    tracker = AISStreamTracker("test-key")
    snap = tracker.snapshot(max_age_minutes=5, limit=10, lat=-65.0, lon=20.0, radius_nm=50.0)
    assert snap["provider"] == "AISStream.io"
    assert snap["enabled"] is True
    assert "vessels" in snap
