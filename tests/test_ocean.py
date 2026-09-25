import pytest
import xarray as xr
import numpy as np
import os
import glob
from src.data_providers.ocean_provider import OceanDataOrchestrator, LocalNetCDFProvider, CMEMSLiveProvider, RAW_DIR

@pytest.fixture
def mock_offline_ocean_data(tmp_path, monkeypatch):
    # Create a temporary raw directory for the test
    temp_raw = tmp_path / "raw"
    temp_raw.mkdir()
    
    # Mock RAW_DIR globally
    monkeypatch.setattr("src.data_providers.ocean_provider.RAW_DIR", str(temp_raw))
    
    # Create a fake netcdf
    times = [np.datetime64("2026-08-01")]
    lats = np.array([-60.0, -61.0])
    lons = np.array([-45.0, -44.0])
    
    uo = np.full((1, 2, 2), 3.0)
    vo = np.full((1, 2, 2), 4.0)
    ds = xr.Dataset(
        {
            "uo": (["time", "latitude", "longitude"], uo), 
            "vo": (["time", "latitude", "longitude"], vo)
        }, 
        coords={"time": times, "latitude": lats, "longitude": lons}
    )
    
    f1 = temp_raw / "ocean_mock_2026.nc"
    ds.to_netcdf(f1)
    return str(f1)

def test_offline_provider(mock_offline_ocean_data):
    provider = LocalNetCDFProvider()
    ds, metadata = provider.get_data()
    
    # Check variables
    assert "ocean_speed" in ds
    assert "ocean_direction" in ds
    
    # Speed = sqrt(3^2 + 4^2) = 5
    np.testing.assert_array_almost_equal(ds["ocean_speed"].values, np.full((1, 2, 2), 5.0))
    # Direction atan2(4, 3)
    np.testing.assert_array_almost_equal(ds["ocean_direction"].values, np.full((1, 2, 2), np.arctan2(4.0, 3.0)))
    
    # Bounds check
    assert metadata["bounds"]["min_lat"] == -61.0
    assert metadata["bounds"]["max_lat"] == -60.0
    
    # Check source tag (Mock has no CMEMS attributes, so it should be downgraded to UNVERIFIED)
    assert metadata["source"] == "UNVERIFIED LOCAL DATA"

def test_live_provider_auth_failure(monkeypatch):
    # Ensure no credentials file is found
    orig_exists = os.path.exists
    monkeypatch.setattr("os.path.exists", lambda x: False if "copernicusmarine-credentials" in str(x) else orig_exists(x))
    
    provider = CMEMSLiveProvider()
    with pytest.raises(ValueError, match="CMEMS Credentials not found."):
        provider.get_data()

def test_orchestrator_fallback(mock_offline_ocean_data, monkeypatch):
    # Force Live provider to fail (auth missing)
    monkeypatch.setattr("os.path.exists", lambda x: False if "copernicusmarine-credentials" in str(x) else True)
    # Mock RAW_DIR again for orchestrator inner scope
    monkeypatch.setattr("src.data_providers.ocean_provider.RAW_DIR", os.path.dirname(mock_offline_ocean_data))
    monkeypatch.setattr("glob.glob", lambda x: [mock_offline_ocean_data] if "ocean" in x else [])
    
    orchestrator = OceanDataOrchestrator()
    ds, metadata = orchestrator.get_data()
    
    # Should fall back to offline but flag as UNVERIFIED due to missing CMEMS metadata
    assert metadata["source"] == "UNVERIFIED LOCAL DATA"
    assert "ocean_speed" in ds
    
from fastapi.testclient import TestClient
from src.api.main import app
client = TestClient(app)

def test_api_ocean_endpoint(mock_offline_ocean_data, monkeypatch):
    # Mock orchestrator behavior for the API test
    monkeypatch.setattr("src.data_providers.ocean_provider.RAW_DIR", os.path.dirname(mock_offline_ocean_data))
    monkeypatch.setattr("os.path.exists", lambda x: False if "copernicusmarine-credentials" in str(x) else True)
    monkeypatch.setattr("glob.glob", lambda x: [mock_offline_ocean_data] if "ocean" in x else [])

    response = client.get("/api/data/ocean")
    assert response.status_code == 200
    data = response.json()
    assert "source" in data
    assert data["source"] == "UNVERIFIED LOCAL DATA"
