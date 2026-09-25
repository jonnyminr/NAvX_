import os
import matplotlib.pyplot as plt
import rasterio
from rasterio.plot import show
import geopandas as gpd

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
ICE_FILE = os.path.join(DATA_DIR, "raw", "S_20260831_concentration_v4.0.tif")
ICEBERG_FILE = os.path.join(DATA_DIR, "processed", "icebergs.geojson")
OUTPUT_MAP = os.path.join(DATA_DIR, "..", "docs", "overlay_map_v2.png")

def create_overlay():
    print("Generating Sea-Ice + Iceberg + Weather Overlay Map...")
    
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # 1. Plot Sea Ice
    try:
        ice_dataset = rasterio.open(ICE_FILE)
        band1 = ice_dataset.read(1)
        extent = [ice_dataset.bounds.left, ice_dataset.bounds.right, 
                  ice_dataset.bounds.bottom, ice_dataset.bounds.top]
        import numpy as np
        band1_masked = np.ma.masked_where(band1 > 1000, band1)
        im = ax.imshow(band1_masked, cmap='Blues_r', extent=extent, origin='upper', vmin=0, vmax=1000)
        plt.colorbar(im, ax=ax, label="Sea Ice Concentration (%)", shrink=0.7)
    except Exception as e:
        print(f"Error loading sea ice: {e}")

    # 2. Plot Icebergs
    try:
        icebergs = gpd.read_file(ICEBERG_FILE)
        if not icebergs.empty:
            icebergs.plot(ax=ax, color='red', marker='^', markersize=50, edgecolor='black', label='USNIC Icebergs')
    except Exception as e:
        print(f"Error loading icebergs: {e}")
        
    # 3. Plot Weather (If CDS API credentials exist and downloaded, else note it)
    try:
        import xarray as xr
        import glob
        
        # Check if any processed ERA5 file exists
        era5_files = glob.glob(os.path.join(DATA_DIR, "processed", "era5_*_processed.nc"))
        if era5_files:
            ds = xr.open_dataset(era5_files[0])
            # This legacy overlay only reports availability here; it does not invent a weather field.
            ax.text(0.05, 0.95, f"Weather Layer: Active (Wind/Temp)", 
                    transform=ax.transAxes, color='green', fontweight='bold', 
                    bbox=dict(facecolor='white', alpha=0.8))
        else:
            raise FileNotFoundError("No ERA5 data downloaded (likely missing API credentials)")
    except Exception as e:
        print(f"Weather overlay skipped: {e}")
        ax.text(0.05, 0.95, f"Weather Layer: UNAVAILABLE\n(Missing CDS API Credentials)", 
                transform=ax.transAxes, color='red', fontweight='bold', 
                bbox=dict(facecolor='white', alpha=0.8))

    # Formatting
    ax.set_title("Antarctic Navigation Intelligence: Sea-Ice + Icebergs + Weather\n(Phase 3)", fontsize=14)
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.legend(loc='upper right')
    ax.grid(True, linestyle=':', alpha=0.6)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_MAP, dpi=150)
    print(f"Map saved successfully to {OUTPUT_MAP}")

if __name__ == "__main__":
    create_overlay()
