"""Automatic NSIDC G02135 Antarctic sea-ice concentration ingestion.

The downloader discovers the newest available Southern Hemisphere daily GeoTIFF
instead of being pinned to a hard-coded month. It keeps the original source file
and returns provenance metadata for the database layer.
"""

from __future__ import annotations

import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import rasterio

ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = ROOT / "data" / "raw"
METADATA_DIR = ROOT / "data" / "metadata"
BASE_ROOT = "https://noaadata.apps.nsidc.org/NOAA/G02135/south/daily/geotiff"
USER_AGENT = "ANTARCTIC-NAV-X/4.0 (+educational decision-support prototype)"


def _month_candidates(count: int = 4):
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    for _ in range(count):
        dt = datetime(year, month, 1, tzinfo=timezone.utc)
        yield dt.year, dt.month, dt.strftime("%b")
        month -= 1
        if month == 0:
            year -= 1
            month = 12


def _fetch_bytes(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def discover_latest_geotiff() -> tuple[str, str] | tuple[None, None]:
    for year, month, month_abbr in _month_candidates():
        month_dir = f"{month:02d}_{month_abbr}"
        base_url = f"{BASE_ROOT}/{year}/{month_dir}/"
        try:
            html = _fetch_bytes(base_url).decode("utf-8", errors="replace")
        except Exception:
            continue
        files = sorted(set(re.findall(r'href=["\']([^"\']*concentration[^"\']*\.tif)["\']', html, flags=re.I)))
        if files:
            latest = files[-1]
            return base_url + latest, latest
    return None, None


def _observed_from_filename(filename: str):
    match = re.search(r"S_(\d{8})_concentration", filename)
    if not match:
        return None
    try:
        dt = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def run_ingestion(quiet: bool = False):
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    if not quiet:
        print("Starting NSIDC G02135 Antarctic sea-ice ingestion")

    file_url, latest_file = discover_latest_geotiff()
    if not file_url or not latest_file:
        message = "No recent NSIDC concentration GeoTIFF could be discovered"
        if not quiet:
            print(message)
        return {"ok": False, "message": message}

    output_path = RAW_DATA_DIR / latest_file
    downloaded = False
    if not output_path.exists():
        try:
            output_path.write_bytes(_fetch_bytes(file_url, timeout=60))
            downloaded = True
        except Exception as exc:
            message = f"NSIDC download failed: {type(exc).__name__}: {exc}"
            if not quiet:
                print(message)
            return {"ok": False, "message": message, "source_url": file_url}

    try:
        with rasterio.open(output_path) as dataset:
            band1 = dataset.read(1)
            # G02135 V4 concentration data uses scaled values; keep only the
            # broad scientifically meaningful range here as a file-integrity check.
            valid_count = int((band1 <= 1000).sum())
            metadata = {
                "driver": dataset.driver,
                "crs": str(dataset.crs),
                "bounds": [float(v) for v in dataset.bounds],
                "width": int(dataset.width),
                "height": int(dataset.height),
                "bands": int(dataset.count),
                "dtypes": list(dataset.dtypes),
                "valid_sea_ice_pixels": valid_count,
            }
    except Exception as exc:
        message = f"Downloaded NSIDC file failed Rasterio validation: {type(exc).__name__}: {exc}"
        if not quiet:
            print(message)
        return {"ok": False, "message": message, "path": str(output_path), "source_url": file_url}

    retrieved_at = datetime.now(timezone.utc).isoformat()
    observed_at = _observed_from_filename(latest_file)
    meta_path = METADATA_DIR / f"{latest_file}.meta.txt"
    meta_path.write_text(
        "\n".join([
            f"Source URL: {file_url}",
            f"Downloaded At: {retrieved_at}",
            f"Observed At: {observed_at or 'UNKNOWN'}",
            "Provider: NSIDC (G02135 Version 4)",
            "Variables: Sea Ice Concentration",
            f"CRS: {metadata['crs']}",
        ]) + "\n",
        encoding="utf-8",
    )

    result = {
        "ok": True,
        "provider": "NSIDC",
        "dataset_id": "G02135-v4",
        "source_url": file_url,
        "path": str(output_path),
        "filename": latest_file,
        "downloaded": downloaded,
        "retrieved_at": retrieved_at,
        "observed_at": observed_at,
        "metadata": metadata,
        "message": f"Using latest discovered NSIDC file {latest_file}",
    }
    if not quiet:
        print(result["message"])
        print(f"Validated CRS: {metadata['crs']}; valid pixels: {metadata['valid_sea_ice_pixels']}")
    return result


if __name__ == "__main__":
    result = run_ingestion()
    raise SystemExit(0 if result.get("ok") else 1)
