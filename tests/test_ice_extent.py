import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

def test_api_ice_extent_trends():
    response = client.get("/api/data/ice-extent-trends")
    assert response.status_code == 200
    data = response.json()
    
    # 1. Check Source and Provenance
    assert data["source"] == "U.S. National Ice Center (USNIC)"
    assert "https://usicecenter.gov/Products/AntarcTrendGraph" in data["reference"]
    assert "100% genuine USNIC records" in data["scientific_integrity"]
    
    # 2. Check Years data
    years = data["years"]
    assert "2026" in years
    assert "2025" in years
    assert "2024" in years
    assert len(years["2026"]) > 0
    assert len(years["2025"]) >= 364
    assert len(years["2024"]) >= 365
    
    # Check data fields for records
    first_record = years["2025"][0]
    assert "date" in first_record
    assert "extent_sqkm" in first_record
    assert "extent_millions_sqkm" in first_record
    # Antarctic ice extent is between 1.5M and 22.0M sq km
    assert 1.5 <= first_record["extent_millions_sqkm"] <= 22.0
    
    # 3. Check 10-year Climatology
    climo = data["climo_10yr"]
    assert len(climo) == 365
    assert 1.5 <= climo[0]["extent_millions_sqkm"] <= 22.0
    
    # 4. Check Annual Stats
    stats = data["stats"]
    assert "2025" in stats
    assert stats["2025"]["maximum"]["extent_millions_sqkm"] > stats["2025"]["minimum"]["extent_millions_sqkm"]
    assert stats["2025"]["daily_average"] > 0
    
    # 5. Check Navigability Phase Context
    assert "navigability_context" in data
    assert "phase" in data["navigability_context"]
    assert "navigability_window" in data["navigability_context"]
