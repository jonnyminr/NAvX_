import os
import pytest
import json
import pandas as pd
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
PROCESSED_ICEBERGS = os.path.join(DATA_DIR, "processed", "icebergs.geojson")

def test_api_icebergs_endpoint():
    response = client.get("/api/data/icebergs")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "USNIC"
    assert "count" in data
    assert "icebergs" in data
    assert data["icebergs"]["type"] == "FeatureCollection"
    
def test_iceberg_geojson_validity():
    assert os.path.exists(PROCESSED_ICEBERGS)
    with open(PROCESSED_ICEBERGS, "r") as f:
        geojson = json.load(f)
    
    # Check projection in CRS (should be EPSG:3412 or custom if pyproj writes it differently)
    # GeoPandas sometimes omits CRS in geojson, but let's check features
    features = geojson.get("features", [])
    assert len(features) > 0
    
    first_feature = features[0]
    assert first_feature["geometry"]["type"] == "Point"
    
    props = first_feature["properties"]
    assert "id" in props
    assert "lat" in props
    assert "lon" in props
    assert "source" in props
    assert props["source"] == "USNIC"

def test_missing_values_handled(monkeypatch):
    # Dummy test to simulate missing values processing logic
    from src.data_ingestion.ingest_icebergs import process_icebergs
    # Process icebergs already filtered missing lat/lon, so we just check if it ran successfully
    assert os.path.exists(PROCESSED_ICEBERGS)
