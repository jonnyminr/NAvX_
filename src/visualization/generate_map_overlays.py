"""
Generates static map overlay assets from the real environmental datasets already
in data/raw/ and data/processed/. This is a one-time (or re-run-when-data-updates)
build step, not something that runs on every server request - overlays don't
change unless the underlying data does.

Nothing in data/ is modified. This script only READS the real datasets and WRITES
derived visualization files into src/api/static/overlays/, which is served
alongside the dashboard.

Outputs:
    src/api/static/overlays/sea_ice.png        - reprojected NSIDC concentration image
    src/api/static/overlays/sea_ice_bounds.json - lat/lon bounds for the image above
    src/api/static/overlays/currents.json       - subsampled real CMEMS current vectors
    src/api/static/overlays/wind.json           - subsampled real ERA5 wind vectors
"""
import os
import json
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import xarray as xr

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
OUT_DIR = os.path.join(BASE_DIR, "src", "api", "static", "overlays")
os.makedirs(OUT_DIR, exist_ok=True)


def render_sea_ice_overlay():
    """
    Reprojects the NSIDC polar-stereographic GeoTIFF into plain lat/lon (EPSG:4326)
    and colors it using NSIDC's OWN embedded color table - we don't invent a
    percentage scale ourselves, we just draw the same colors NSIDC ships with the file.
    """
    src_path = os.path.join(RAW_DIR, "S_20260831_concentration_v4.0.tif")

    with rasterio.open(src_path) as src:
        colormap = src.colormap(1)  # NSIDC's official value -> RGBA lookup

        # Work out what the reprojected grid should look like
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )

        # Reproject with nearest-neighbor so we don't blend real ice values
        # with flag codes (land/coast/missing) at the boundaries
        reprojected = np.zeros((height, width), dtype=src.dtypes[0])
        reproject(
            source=rasterio.band(src, 1),
            destination=reprojected,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )

        # Apply NSIDC's color table to every pixel, transparent where there's no coverage
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        for value, color in colormap.items():
            mask = reprojected == value
            if mask.any():
                rgba[mask] = color
        # Anywhere the reprojection left a gap (outside the original raster extent)
        # stays fully transparent rather than showing a fabricated color
        covered = np.isin(reprojected, list(colormap.keys()))
        rgba[~covered, 3] = 0

        # Compute the lat/lon bounding box of the reprojected image for Leaflet
        left, bottom = transform * (0, height)
        right, top = transform * (width, 0)

    from PIL import Image
    Image.fromarray(rgba, mode="RGBA").save(os.path.join(OUT_DIR, "sea_ice.png"))

    with open(os.path.join(OUT_DIR, "sea_ice_bounds.json"), "w") as f:
        json.dump({
            "south": bottom, "north": top, "west": left, "east": right,
            "source": "NSIDC G02135 Sea Ice Concentration",
            "note": "Rendered using NSIDC's own embedded color table, reprojected to EPSG:4326."
        }, f)

    print(f"Sea ice overlay written: {width}x{height} px, bounds ({bottom:.1f}..{top:.1f} lat, {left:.1f}..{right:.1f} lon)")


def extract_vector_field(nc_path, u_var, v_var, out_name, source_label, target_lat_points=16, target_lon_points=28):
    """
    Pulls a sparse grid of real (u, v) vectors out of a NetCDF file and saves
    them as arrows for the map. We control the arrow COUNT directly (rather
    than a fixed grid step) so the map stays readable no matter how fine the
    source grid is - CMEMS ships a much denser grid than ERA5, for example.
    Roughly target_lat_points x target_lon_points arrows come out the other end.
    """
    ds = xr.open_dataset(nc_path)

    lats = ds["latitude"].values
    lons = ds["longitude"].values
    u = ds[u_var].values
    v = ds[v_var].values

    # Squeeze away any leading time/depth dimensions of size 1
    while u.ndim > 2:
        u = u[0]
        v = v[0]

    lat_step = max(1, len(lats) // target_lat_points)
    lon_step = max(1, len(lons) // target_lon_points)

    vectors = []
    for i in range(0, len(lats), lat_step):
        for j in range(0, len(lons), lon_step):
            uu, vv = float(u[i, j]), float(v[i, j])
            if np.isnan(uu) or np.isnan(vv):
                continue
            vectors.append({
                "lat": float(lats[i]),
                "lon": float(lons[j]),
                "u": uu,
                "v": vv,
            })

    with open(os.path.join(OUT_DIR, out_name), "w") as f:
        json.dump({"source": source_label, "vectors": vectors}, f)

    print(f"{out_name}: {len(vectors)} real vectors written from {source_label} (~{lat_step}x{lon_step} grid step)")


if __name__ == "__main__":
    # NOTE: we deliberately read straight from data/raw/, not data/processed/.
    # The processed/ folder is a regenerable cache (see .gitignore) that gets
    # overwritten by whichever code last ran - including the test suite's
    # mock fixtures. Reading directly from the checksum-verified raw files
    # guarantees this overlay is always built from real, unmodified data.
    render_sea_ice_overlay()
    extract_vector_field(
        os.path.join(RAW_DIR, "ocean_currents_offline.nc"),
        "uo", "vo", "currents.json", "CMEMS Ocean Currents (data/raw)"
    )
    extract_vector_field(
        os.path.join(RAW_DIR, "era5_antarctic_2026-08-27.nc"),
        "u10", "v10", "wind.json", "ERA5 10m Wind (data/raw)"
    )
