from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.data_providers.realtime_provider import AISProviderManager, USNICLiveCache
from src.db.database import init_database
from src.services.ingestion_service import (
    sync_byu_current_icebergs,
    sync_ais,
    sync_cmems,
    sync_era5,
    sync_iceberg_history,
    sync_ndbc,
    sync_nsidc,
    sync_sentinel1,
    sync_usnic,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one NAV-X real-data ingestion job now")
    parser.add_argument("source", choices=["usnic","iceberg_history", "byu_current","ais", "nsidc", "ndbc", "sentinel1", "cmems", "era5"])
    args = parser.parse_args()

    init_database()
    data_dir = ROOT / "data"
    usnic = USNICLiveCache(data_dir)
    ais = AISProviderManager(data_root=data_dir)
    jobs = {
        "usnic": lambda: sync_usnic(usnic),
        "iceberg_history":
        lambda:
            sync_iceberg_history(True),
            "byu_current":
    sync_byu_current_icebergs,
        "ais": lambda: sync_ais(ais),
        "nsidc": sync_nsidc,
        "ndbc": sync_ndbc,
        "sentinel1": sync_sentinel1,
        "cmems": sync_cmems,
        "era5": sync_era5,
    }
    print(json.dumps(jobs[args.source](), indent=2, default=str))
