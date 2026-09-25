"""NOAA NDBC latest-observation client using the public HTTPS file."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

NDBC_LATEST_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"


def _number(value):
    if value in (None, "", "MM"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_latest_observations(data_root: Path, min_lat: float | None = None) -> dict:
    if min_lat is None:
        min_lat = float(os.getenv("NDBC_MIN_LAT", "-45"))
    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": "ANTARCTIC-NAV-X/4.0"}) as client:
        response = client.get(NDBC_LATEST_URL)
        response.raise_for_status()
        text = response.text

    live_dir = Path(data_root) / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    raw_path = live_dir / "ndbc_latest_obs.txt"
    raw_path.write_text(text, encoding="utf-8")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = None
    observations = []
    for line in lines:
        if line.startswith("#STN"):
            header = line.lstrip("#").split()
            continue
        if line.startswith("#") or header is None:
            continue
        values = line.split()
        if len(values) < len(header):
            values += ["MM"] * (len(header) - len(values))
        row = dict(zip(header, values))
        lat = _number(row.get("LAT"))
        lon = _number(row.get("LON"))
        if lat is None or lon is None or lat > float(min_lat):
            continue
        try:
            observed = datetime(
                int(row.get("YY")), int(row.get("MM")), int(row.get("DD")),
                int(row.get("hh")), int(row.get("mm")), tzinfo=timezone.utc,
            )
        except (TypeError, ValueError):
            continue
        observations.append({
            "station_id": row.get("STN"),
            "lat": lat,
            "lon": lon,
            "observed_at": observed.isoformat(),
            "wind_direction_deg": _number(row.get("WDIR")),
            "wind_speed_mps": _number(row.get("WSPD")),
            "gust_mps": _number(row.get("GST")),
            "wave_height_m": _number(row.get("WVHT")),
            "pressure_hpa": _number(row.get("PRES")),
            "air_temperature_c": _number(row.get("ATMP")),
            "water_temperature_c": _number(row.get("WTMP")),
            "raw": row,
        })

    return {
        "ok": True,
        "provider": "NOAA NDBC",
        "source_url": NDBC_LATEST_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "minimum_latitude": float(min_lat),
        "count": len(observations),
        "observations": observations,
        "raw_path": str(raw_path),
    }
