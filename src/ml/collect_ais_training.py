from __future__ import annotations

import argparse
import csv
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "live" / "ais_ml_training.csv"
FIELDS = ["mmsi", "name", "sog_knots", "cog_deg", "heading_deg", "lat", "lon", "last_seen_utc", "source"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Append genuine currently received AIS positions to the NAV-X ML training CSV.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/data/vessels?max_age_minutes=360&limit=500")
    args = parser.parse_args()
    response = httpx.get(args.url, timeout=20.0)
    response.raise_for_status()
    payload = response.json()
    vessels = payload.get("vessels", []) if isinstance(payload, dict) else []
    if not vessels:
        print("No genuine AIS positions are currently available. Nothing was written.")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    exists = OUT.exists()
    seen = set()
    if exists:
        try:
            with OUT.open("r", encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    seen.add((str(r.get("mmsi")), str(r.get("last_seen_utc"))))
        except Exception:
            seen = set()
    added = 0
    with OUT.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if not exists or OUT.stat().st_size == 0:
            writer.writeheader()
        for v in vessels:
            key = (str(v.get("mmsi")), str(v.get("last_seen_utc")))
            if key in seen:
                continue
            writer.writerow({k: v.get(k) for k in FIELDS})
            seen.add(key); added += 1
    print(f"Appended {added} genuine AIS observations to {OUT}")
    print("No synthetic vessel positions were generated.")


if __name__ == "__main__":
    main()
