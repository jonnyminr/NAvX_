import os
import xarray as xr
from datetime import datetime, timedelta

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")

def download_era5_subset(date_str: str = None):
    """
    Downloads an Antarctic subset of ERA5 data for a specific date.
    Requires CDS API credentials.
    """
    if date_str is None:
        # ERA5 availability can lag real time; use five days ago as the operational default.
        date_str = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        
    year, month, day = date_str.split('-')
    
    file_path = os.path.join(RAW_DIR, f"era5_antarctic_{date_str}.nc")
    if os.path.exists(file_path):
        print(f"File {file_path} already exists. Skipping download.")
        return file_path

    print(f"Attempting to download ERA5 data for {date_str} via CDS API...")
    
    try:
        import cdsapi
        c = cdsapi.Client()
        c.retrieve(
            'reanalysis-era5-single-levels',
            {
                'product_type': 'reanalysis',
                'data_format': 'netcdf',
                'variable': [
                    '10m_u_component_of_wind', 
                    '10m_v_component_of_wind', 
                    '2m_temperature', 
                    'mean_sea_level_pressure'
                ],
                'year': year,
                'month': month,
                'day': day,
                'time': [
                    '00:00', '06:00', '12:00', '18:00',
                ],
                'area': [
                    -50, -180, -90, 180, # North, West, South, East (Antarctic bounding box)
                ],
            },
            file_path)
        print(f"Download complete: {file_path}")
        return file_path
    except Exception as e:
        print("\n==================================================")
        print("SOURCE: Copernicus Climate Change Service (ERA5)")
        print(f"ERROR: {e}")
        print("REASON: Missing or invalid CDS API credentials, or API is down.")
        print("REQUIRED USER ACTION: Register at https://cds.climate.copernicus.eu/, retrieve API token, and create ~/.cdsapirc file.")
        print("==================================================\n")
        return None

def process_era5(raw_file_path):
    """
    Processes the raw NetCDF to calculate wind speed and output processed subset.
    """
    if not os.path.exists(raw_file_path):
        return None
        
    print(f"Processing ERA5 data from {raw_file_path}...")
    try:
        ds = xr.open_dataset(raw_file_path)
        
        # Calculate wind speed
        # sqrt(u^2 + v^2)
        wind_speed = (ds['u10']**2 + ds['v10']**2)**0.5
        wind_speed.attrs['units'] = 'm/s'
        wind_speed.attrs['long_name'] = '10 metre wind speed'
        ds['wind_speed'] = wind_speed
        
        # Generate data quality stats
        print(f"Data Variables: {list(ds.data_vars)}")
        print(f"Spatial Grid: {ds.sizes['latitude']}x{ds.sizes['longitude']}")
        time_dim = 'time' if 'time' in ds.sizes else 'valid_time'
        print(f"Time steps: {ds.sizes.get(time_dim, 0)}")
        
        # Check for missing values in temperature
        missing_t2m = ds['t2m'].isnull().sum().item()
        print(f"Missing temperature values: {missing_t2m}")
        
        # Save processed dataset. Production files under data/raw are written to
        # data/processed; ad-hoc/test files are written beside their input so
        # they cannot pollute the application's cached operational dataset.
        raw_abs = os.path.abspath(raw_file_path)
        try:
            is_project_raw = os.path.commonpath([raw_abs, os.path.abspath(RAW_DIR)]) == os.path.abspath(RAW_DIR)
        except ValueError:
            is_project_raw = False
        output_dir = PROCESSED_DIR if is_project_raw else os.path.dirname(raw_abs)
        processed_path = os.path.join(output_dir, os.path.basename(raw_file_path).replace(".nc", "_processed.nc"))
        ds.to_netcdf(processed_path)
        print(f"Processed file saved to {processed_path}")
        return processed_path
    except Exception as e:
        print(f"Processing failed: {e}")
        return None

def run_weather_pipeline():
    print("Starting Phase 3: ERA5 Weather Ingestion")
    raw_path = download_era5_subset()
    if raw_path:
        process_era5(raw_path)

if __name__ == "__main__":
    run_weather_pipeline()
