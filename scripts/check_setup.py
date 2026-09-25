from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.db.database import database_status, init_database
from src.services.ingestion_service import cds_credentials_configured, cmems_credentials_configured, iceberg_history_summary
from src.ml.ais_anomaly import AISAnomalyML


def yn(value):
    return "YES" if value else "NO"


if __name__ == "__main__":
    init_database()
    db = database_status()
    checks = {
        "Database reachable": db.get("reachable", False),
        "AIS provider credential configured": bool(
            (os.getenv("AISSTREAM_API_KEY") or "").strip()
            or (os.getenv("AISHUB_USERNAME") or "").strip()
            or (os.getenv("DATALASTIC_API_KEY") or "").strip()
        ),
        "Copernicus Marine credentials configured": cmems_credentials_configured(),
        "CDS/ERA5 credentials configured": cds_credentials_configured(),
        "Sentinel-1 OAuth client configured": bool((os.getenv("SENTINEL_CLIENT_ID") or "").strip() and (os.getenv("SENTINEL_CLIENT_SECRET") or "").strip()),
        "NASA Earthdata token configured (optional; no generic NASA dataset is fetched)": bool((os.getenv("EARTHDATA_TOKEN") or "").strip()),
        "NOAA NDBC HTTPS requires API key": False,
        "NSIDC HTTPS requires API key": False,
        "USNIC current CSV requires API key": False,
    }
    print("ANTARCTIC NAV-X setup check")
    print("----------------------------")
    for label, value in checks.items():
        if label.endswith("requires API key"):
            print(f"{label}: {yn(value)} (expected NO)")
        else:
            print(f"{label}: {yn(value)}")
    try:
        hist = iceberg_history_summary(limit=1)
        print(f"Historical iceberg designations stored: {hist.get('unique_icebergs', 0)}")
        print(f"Historical iceberg positions stored: {hist.get('historical_rows', 0)}")
    except Exception as exc:
        print(f"Historical iceberg database check: ERROR ({exc})")
    try:
        ais_status = AISAnomalyML(ROOT).public_status()
        print(f"AIS anomaly ML status: {ais_status.get('status')}")
        print(f"AIS valid training samples: {ais_status.get('valid_training_samples', 0)}/{ais_status.get('minimum_required', 30)}")
        print(f"AIS total stored positions: {ais_status.get('real_database_samples', 0)}")
    except Exception as exc:
        print(f"AIS anomaly ML check: ERROR ({exc})")
    print("\nSecrets are not printed by this script.")
