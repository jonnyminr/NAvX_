import pytest
import xarray as xr
import numpy as np
import os
from src.data_ingestion.era5_loader import process_era5

@pytest.fixture
def mock_era5_netcdf(tmp_path):
    """Creates a tiny dummy xarray dataset representing ERA5 structure to strictly test processing math."""
    times = pd.date_range("2026-08-01", periods=2)
    lats = np.array([-60.0, -61.0])
    lons = np.array([-45.0, -44.0])
    
    # u=3, v=4 -> wind_speed should be 5
    u10 = np.full((2, 2, 2), 3.0)
    v10 = np.full((2, 2, 2), 4.0)
    t2m = np.full((2, 2, 2), 273.15) # 0 Celsius
    msl = np.full((2, 2, 2), 101325.0)
    
    ds = xr.Dataset(
        {
            "u10": (["time", "latitude", "longitude"], u10, {"units": "m/s"}),
            "v10": (["time", "latitude", "longitude"], v10, {"units": "m/s"}),
            "t2m": (["time", "latitude", "longitude"], t2m, {"units": "K"}),
            "msl": (["time", "latitude", "longitude"], msl, {"units": "Pa"}),
        },
        coords={
            "time": times,
            "latitude": lats,
            "longitude": lons,
        },
    )
    
    file_path = tmp_path / "era5_antarctic_mock.nc"
    ds.to_netcdf(file_path)
    return str(file_path)

import pandas as pd

def test_wind_speed_calculation(mock_era5_netcdf):
    """Tests if the math (sqrt(u^2+v^2)) correctly computes wind speed"""
    processed_file = process_era5(mock_era5_netcdf)
    assert processed_file is not None
    assert os.path.exists(processed_file)
    
    ds = xr.open_dataset(processed_file)
    assert "wind_speed" in ds.data_vars
    # u=3, v=4 -> speed=5
    np.testing.assert_array_almost_equal(ds["wind_speed"].values, np.full((2, 2, 2), 5.0))
    assert ds["wind_speed"].attrs["units"] == "m/s"

def test_units_and_coordinates(mock_era5_netcdf):
    ds = xr.open_dataset(mock_era5_netcdf)
    assert ds["t2m"].attrs["units"] == "K"
    assert ds["msl"].attrs["units"] == "Pa"
    
    lats = ds["latitude"].values
    assert (lats <= -50).all() and (lats >= -90).all()

from fastapi.testclient import TestClient
from src.api.main import app
client = TestClient(app)

def test_api_weather_endpoint():
    response = client.get("/api/data/weather")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "Copernicus ERA5"
    if "error" not in data:
        assert "variables" in data
        assert "wind_speed" in data["variables"]
