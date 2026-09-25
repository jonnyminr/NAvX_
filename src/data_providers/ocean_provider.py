import os
import glob
import xarray as xr
import numpy as np
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
PROJECT_RAW_DIR = RAW_DIR

class OceanDataProvider(ABC):
    @abstractmethod
    def get_data(self):
        """Returns a tuple of (processed_dataset, metadata_dict)"""
        pass

class CMEMSLiveProvider(OceanDataProvider):
    def get_data(self):
        cred_file = os.path.expanduser("~/.copernicusmarine/.copernicusmarine-credentials")
        env_user = (os.getenv("COPERNICUSMARINE_SERVICE_USERNAME") or os.getenv("COPERNICUS_USERNAME") or "").strip()
        env_password = (os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD") or os.getenv("COPERNICUS_PASSWORD") or "").strip()
        if not os.path.exists(cred_file) and not (env_user and env_password):
            raise ValueError("CMEMS Credentials not found. Configure copernicusmarine login or COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD.")

        # The current Copernicus Marine Toolbox reads the official SERVICE_*
        # environment variable names automatically. Mirror legacy NAV-X names
        # into those names for backwards compatibility without exposing secrets.
        if env_user and not os.getenv("COPERNICUSMARINE_SERVICE_USERNAME"):
            os.environ["COPERNICUSMARINE_SERVICE_USERNAME"] = env_user
        if env_password and not os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD"):
            os.environ["COPERNICUSMARINE_SERVICE_PASSWORD"] = env_password

        import copernicusmarine
        date_str = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        file_curr = os.path.join(RAW_DIR, f"ocean_current_live_{date_str}.nc")
        
        if not os.path.exists(file_curr):
            copernicusmarine.subset(
                dataset_id="cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
                variables=["uo", "vo"],
                start_datetime=date_str,
                end_datetime=date_str,
                minimum_longitude=-180,
                maximum_longitude=180,
                minimum_latitude=-80,
                maximum_latitude=-50,
                minimum_depth=0.49402499198913574,
                maximum_depth=0.49402499198913574,
                output_filename=os.path.basename(file_curr),
                output_directory=RAW_DIR,
            )
        
        ds = xr.open_dataset(file_curr)
        return self._process_and_load(ds, "CMEMS LIVE", "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m")
        
    def _process_and_load(self, ds, source_tag, dataset_id, persist=True):
        # Calculate speeds and directions safely
        ocean_speed = np.sqrt(ds['uo']**2 + ds['vo']**2)
        ocean_direction = np.arctan2(ds['vo'], ds['uo'])
        
        processed_ds = xr.Dataset({
            "ocean_u": ds['uo'],
            "ocean_v": ds['vo'],
            "ocean_speed": ocean_speed,
            "ocean_direction": ocean_direction
        })
        
        # Persist only operational project data. Test/ad-hoc datasets should not
        # overwrite the cached file used by the running application.
        if persist:
            out_path = os.path.join(PROCESSED_DIR, "ocean_combined_processed.nc")
            processed_ds.to_netcdf(out_path)
        
        metadata = {
            "source": source_tag,
            "dataset_id": dataset_id,
            "timestamp": str(ds.time.values[0]) if hasattr(ds, 'time') else None,
            "bounds": {
                "min_lat": float(ds.latitude.min()),
                "max_lat": float(ds.latitude.max()),
                "min_lon": float(ds.longitude.min()),
                "max_lon": float(ds.longitude.max())
            },
            "grid": f"{ds.sizes.get('latitude', 0)}x{ds.sizes.get('longitude', 0)}",
            "variables": list(processed_ds.data_vars.keys()),
            "units": {"ocean_u": "m/s", "ocean_v": "m/s", "ocean_speed": "m/s", "ocean_direction": "radians"}
        }
        return processed_ds, metadata

class LocalNetCDFProvider(OceanDataProvider):
    def get_data(self):
        # Look for offline ocean current NetCDF files
        files = glob.glob(os.path.join(RAW_DIR, "ocean*.nc"))
        if not files:
            raise FileNotFoundError("No offline NetCDF files found in cache.")
        
        # Prefer locally cached file
        latest_file = max(files, key=os.path.getmtime)
        ds = xr.open_dataset(latest_file)
        
        if 'uo' not in ds or 'vo' not in ds:
             raise ValueError(f"Required variables 'uo' and 'vo' not found in {latest_file}")
             
        # Strict Data Provenance Validation
        is_cmems = False
        attrs = {k.lower(): str(v).lower() for k, v in ds.attrs.items()}
        
        # Check CMEMS signatures
        if any("copernicus" in v or "cmems" in v for v in attrs.values()) or \
           "cmems" in ds.encoding.get("source", "").lower():
            is_cmems = True
            
        source_tag = "CMEMS DOWNLOADED OFFLINE DATA" if is_cmems else "UNVERIFIED LOCAL DATA"
        dataset_id = ds.attrs.get("title", ds.attrs.get("id", "Unknown Offline Cached Dataset"))
        
        # Reuse processing logic. Only files from the real project raw-data
        # directory may refresh the application's processed cache.
        try:
            is_project_cache = os.path.commonpath([os.path.abspath(latest_file), os.path.abspath(PROJECT_RAW_DIR)]) == os.path.abspath(PROJECT_RAW_DIR)
        except ValueError:
            is_project_cache = False
        live_provider = CMEMSLiveProvider()
        return live_provider._process_and_load(ds, source_tag, dataset_id, persist=is_project_cache)

class OceanDataOrchestrator:
    def __init__(self):
        self.live = CMEMSLiveProvider()
        self.local = LocalNetCDFProvider()
        
    def get_data(self):
        try:
            print("Attempting Live CMEMS Provider...")
            return self.live.get_data()
        except Exception as e:
            print(f"Live provider failed: {e}. Falling back to Local Cache...")
            try:
                return self.local.get_data()
            except Exception as local_e:
                raise RuntimeError(f"Both Live and Local providers failed. Local error: {local_e}")
