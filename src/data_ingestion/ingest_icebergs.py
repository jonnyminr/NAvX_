"""Manual USNIC Antarctic iceberg refresh utility.

The API uses the same parser automatically in the background; this script is
kept for reproducible/manual refreshes and writes WGS84 GeoJSON so map geometry
and the source latitude/longitude remain consistent.
"""

import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import json

from src.data_providers.realtime_provider import USNIC_CURRENT_CSV, parse_usnic_csv

SOURCE_URL = USNIC_CURRENT_CSV
ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = ROOT / "data" / "raw"
PROCESSED_DATA_DIR = ROOT / "data" / "processed"
METADATA_DIR = ROOT / "data" / "metadata"


def download_usnic_data():
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    raw_path = RAW_DATA_DIR / f"usnic_icebergs_{timestamp}.csv"
    print(f"Downloading official USNIC iceberg CSV from {SOURCE_URL} ...")
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "ANTARCTIC-NAV-X/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read()
        raw_path.write_bytes(data)
        print(f"Downloaded raw CSV to {raw_path}")
        return str(raw_path), data
    except Exception as exc:
        print(f"Download failed: {exc}")
        return None, None


def process_icebergs(raw_path):
    raw_path = Path(raw_path)
    try:
        payload = parse_usnic_csv(raw_path.read_bytes())
    except Exception as exc:
        print(f"Failed to parse official CSV: {exc}")
        return None

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = PROCESSED_DATA_DIR / "icebergs.geojson"
    # Standard GeoJSON is WGS84.  Keeping it in WGS84 avoids projected geometry
    # being mistaken for longitude/latitude by downstream mapping clients.
    payload["metadata"]["crs"] = "EPSG:4326"
    payload["metadata"]["position_semantics"] = "Official USNIC observation; periodic/weekly, not continuous GPS telemetry"
    processed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    meta_path = METADATA_DIR / "usnic_icebergs.meta.txt"
    meta_path.write_text(
        "\n".join([
            f"Source URL: {SOURCE_URL}",
            f"Downloaded At: {datetime.now(timezone.utc).isoformat()}",
            "Provider: U.S. National Ice Center (USNIC)",
            f"Valid Records: {len(payload.get('features', []))}",
            "CRS: EPSG:4326",
            "Cadence: Official periodic/weekly iceberg table; not continuous real-time GPS",
        ]) + "\n",
        encoding="utf-8",
    )
    print(f"Processed {len(payload.get('features', []))} official iceberg records -> {processed_path}")
    return str(processed_path)


def main():
    raw_path, _ = download_usnic_data()
    if raw_path:
        process_icebergs(raw_path)


if __name__ == "__main__":
    main()
