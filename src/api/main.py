from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

import os
import json
import asyncio
import math
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
except ImportError:
    pass
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
from src.data_providers.realtime_provider import USNICLiveCache, AISProviderManager
from src.models.route_optimizer import PolarAStarRouter, extract_hazard_points, route_distance_km, risk_score, initial_bearing_deg
from src.models.ocean_mask import RealOceanSurface
from src.models.risk import haversine_distance
from src.ml import IcebergResidualML, AISAnomalyML
from src.ai.decision_engine import build_decision_report
from src.db.database import database_status, init_database
from src.jobs.scheduler import NavXIngestionScheduler
from src.services.ingestion_service import (
    iceberg_unified_catalog,
    iceberg_unified_track,
    cds_credentials_configured,
    cmems_credentials_configured,
    database_summary,
    iceberg_history_records,
    iceberg_history_summary,
    recent_buoy_observations,
    recent_satellite_scenes,
    scheduler_status,
    sync_ais,
    sync_cmems,
    sync_era5,
    sync_iceberg_history,
    sync_ndbc,
    sync_nsidc,
    sync_sentinel1,
    sync_usnic,
)

app = FastAPI(title="ANTARCTIC NAV-X Navigation API")

# The bundled frontend is served from this FastAPI process, so it is same-origin
# by default and requires no CORS.  For an intentionally separate frontend, set
# a comma-separated allow-list (never use * for an authenticated deployment).
_cors_origins = [x.strip() for x in (os.getenv("CORS_ORIGINS") or "").split(",") if x.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
RAW_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
ICEBERG_FILE = os.path.join(PROCESSED_DIR, "icebergs.geojson")

ICE_EXTENT_DIR = os.path.join(RAW_DIR, "usnic_extent")

LIVE_DIR = "/tmp/live"
os.makedirs(LIVE_DIR, exist_ok=True)
FORECAST_LOG_FILE = os.path.join(LIVE_DIR, "forecast_verification_log.jsonl")

# Fresh/live source managers. USNIC is refreshed from the official current CSV
# (weekly observation cadence); AIS is a true event-driven live stream when configured.
usnic_live = USNICLiveCache(Path(DATA_DIR))
ais_tracker = AISProviderManager(data_root=Path(DATA_DIR))
ocean_surface = RealOceanSurface(Path(DATA_DIR))
iceberg_ml = IcebergResidualML(Path(__file__).resolve().parents[2])
ais_ml = AISAnomalyML(Path(__file__).resolve().parents[2])
ais_task = None
ingestion_scheduler = NavXIngestionScheduler(usnic_live=usnic_live, ais_tracker=ais_tracker)


# Verified/reference Antarctic locations used by the operator UI.  Fixed-station
# coordinates come from the authoritative organizations listed in ``source``.
# Regional sea coordinates are the project's existing operational reference
# points and are explicitly labelled as such rather than presented as station
# coordinates.  ``routing_eligible`` is evaluated against the real CMEMS/NSIDC
# surface at request time because a named station can legitimately be on land.
ANTARCTIC_LOCATIONS = [
    {
        "id": "bharati-station", "name": "Bharati Station", "lat": -69.406833, "lon": 76.195333,
        "group": "Research Station", "kind": "FIXED_STATION",
        "source": "NCPOR / National Polar Data Center, Government of India",
        "source_url": "https://npdc.ncpor.res.in/npdc/research-stations.action",
        "coordinate_precision": "0.01 arc-minute as published (about 20 m latitude; longitude scale varies)",
        "note": "Station reference coordinate. Routing requires a separately validated navigable ocean point.",
    },
    {
        "id": "maitri-station", "name": "Maitri Station", "lat": -70.764444, "lon": 11.734167,
        "group": "Research Station", "kind": "FIXED_STATION",
        "source": "NCPOR, Government of India",
        "source_url": "https://ncpor.res.in/antarcticas/display/376-maitri",
        "coordinate_precision": "1 arc-second as published (about 31 m latitude)",
        "note": "Inland station reference coordinate; not a marine route endpoint unless an adjacent ocean point is selected and validated.",
    },
    {
        "id": "dakshin-gangotri", "name": "Dakshin Gangotri (historical)", "lat": -70.074167, "lon": 12.003333,
        "group": "Historical Research Station", "kind": "FIXED_STATION",
        "source": "NCPOR / Indian Polar Data portal",
        "source_url": "https://www.data.ncpor.res.in/newhtml/",
        "coordinate_precision": "1 arc-second as published",
        "note": "Historical station reference; not a current operational marine endpoint.",
    },
    {
        "id": "mcmurdo-station", "name": "McMurdo Station", "lat": -77.848167, "lon": 166.668500,
        "group": "Research Station", "kind": "FIXED_STATION",
        "source": "U.S. National Science Foundation",
        "source_url": "https://www.nsf.gov/geo/opp/ail/mcmurdo-station",
        "coordinate_precision": "0.01 arc-minute as published",
        "note": "Station reference on Ross Island; use a validated adjacent water point for ship routing.",
    },
    {
        "id": "rothera-station", "name": "Rothera Research Station", "lat": -67.568889, "lon": -68.124800,
        "group": "Research Station", "kind": "FIXED_STATION",
        "source": "British Antarctic Survey",
        "source_url": "https://www.bas.ac.uk/polar-operations/sites-and-facilities/facility/rothera/",
        "coordinate_precision": "Six decimal places for latitude / four for longitude as published",
        "note": "Station reference on Adelaide Island; use a validated adjacent water point for ship routing.",
    },
    {
        "id": "south-pole", "name": "Amundsen-Scott South Pole Station", "lat": -90.0, "lon": 0.0,
        "group": "Research Station", "kind": "FIXED_STATION",
        "source": "U.S. National Science Foundation",
        "source_url": "https://www.nsf.gov/od/opp/ail/amundson-scott-south-pole-station",
        "coordinate_precision": "Geographic pole (90°S); longitude is undefined and displayed as conventional 0°",
        "note": "Interior reference only. It cannot be used as a ship-routing endpoint.",
    },
    # Existing NAV-X marine reference points.  These are regional map anchors,
    # not surveyed station coordinates.  Their route eligibility is checked
    # against the real navigation surface on every API request.
    {"id":"antarctic-ocean","name":"Antarctic Ocean Overview","lat":-70.0,"lon":0.0,"zoom":3,"group":"Southern Ocean","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"weddell-sea","name":"Weddell Sea","lat":-67.0,"lon":-45.0,"zoom":4,"group":"Antarctic Sea","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"ross-sea","name":"Ross Sea","lat":-73.0,"lon":175.0,"zoom":4,"group":"Antarctic Sea","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"amundsen-sea","name":"Amundsen Sea","lat":-72.5,"lon":-110.0,"zoom":4,"group":"Antarctic Sea","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"bellingshausen-sea","name":"Bellingshausen Sea","lat":-69.0,"lon":-85.0,"zoom":4,"group":"Antarctic Sea","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"scotia-sea","name":"Scotia Sea / Peninsula Approach","lat":-58.5,"lon":-45.0,"zoom":4,"group":"Southern Ocean","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"davis-sea","name":"Davis Sea","lat":-66.5,"lon":90.0,"zoom":4,"group":"Antarctic Sea","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
    {"id":"cooperation-sea","name":"Cooperation Sea","lat":-67.0,"lon":70.0,"zoom":4,"group":"Antarctic Sea","kind":"REGIONAL_REFERENCE","source":"Existing NAV-X operational map reference","source_url":None,"coordinate_precision":"Regional reference point; not a surveyed feature"},
]


OPENFREEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"
OSM_RASTER_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def _map_provider_config() -> dict:
    """Return the keyless operator-map configuration.

    OpenFreeMap is the preferred MapLibre-native vector basemap.  The bundled
    same-origin style endpoint is an OpenStreetMap raster fallback.  Neither
    path requires or exposes an API credential.
    """
    preferred = (os.getenv("OPENFREEMAP_STYLE_URL") or OPENFREEMAP_STYLE_URL).strip()
    if not preferred.startswith("https://"):
        preferred = OPENFREEMAP_STYLE_URL
    return {
        "provider": "OpenFreeMap + OpenStreetMap fallback + MapLibre GL JS",
        "enabled": True,
        "status": "READY_KEYLESS",
        "mode": "KEYLESS_WITH_FALLBACK",
        "style_url": preferred,
        "fallback_style_url": "/api/map/style",
        "maplibre_version": "6.7.0",
        "requires_api_key": False,
        "credential_exposure": "NONE",
        "mappls_configured": bool((os.getenv("MAPPLS_STATIC_KEY") or "").strip()),
        "note": "No basemap API key is required. OpenFreeMap is preferred; OpenStreetMap raster tiles are used as the automatic fallback.",
    }


@app.on_event("startup")
async def start_realtime_feeds():
    global ais_task
    init_database()
    if ais_tracker.enabled and (ais_task is None or ais_task.done()):
        ais_task = asyncio.create_task(ais_tracker.run())
    ingestion_scheduler.start()


@app.on_event("shutdown")
async def stop_realtime_feeds():
    global ais_task
    ingestion_scheduler.stop()
    ais_tracker.stop()
    if ais_task and not ais_task.done():
        ais_task.cancel()
        try:
            await ais_task
        except (asyncio.CancelledError, Exception):
            pass


@app.get("/api/config/map")
def get_map_config():
    """Return safe, keyless runtime map configuration."""
    return _map_provider_config()


@app.get("/api/map/style")
def get_map_style():
    """Same-origin keyless raster fallback style for MapLibre GL JS.

    The browser requests only tiles needed for the visible viewport and keeps
    normal browser caching/referrer behaviour, matching the OpenStreetMap tile
    usage policy for ordinary interactive viewing.
    """
    return {
        "version": 8,
        "name": "ANTARCTIC NAV-X OpenStreetMap Fallback",
        "sources": {
            "osm": {
                "type": "raster",
                "tiles": [OSM_RASTER_TILE_URL],
                "tileSize": 256,
                "attribution": "© OpenStreetMap contributors",
                "maxzoom": 19,
            }
        },
        "layers": [
            {"id": "osm", "type": "raster", "source": "osm", "minzoom": 0, "maxzoom": 19}
        ],
    }


@app.get("/api/map/tiles/{z}/{x}/{y}")
def retired_legacy_tile_proxy(z: int, x: int, y: int):
    """Compatibility endpoint retained after the legacy tile-proxy removal.

    NAV-X no longer proxies provider tiles. Returning 410 prevents old clients
    from mistaking this retired path for an operational tile source.
    """
    raise HTTPException(
        status_code=410,
        detail="Legacy map tile proxy retired. Reload /app/ to use the keyless OpenFreeMap/OpenStreetMap basemap.",
    )


@app.get("/api/locations/antarctica")
def get_antarctic_locations():
    """
    Return Antarctic reference locations plus verified marine route anchors.

    The published station coordinate is preserved.
    If the reference point is on land/coast/no-data, NAV-X searches for the
    nearest CMEMS + NSIDC validated marine cell within 150 km.
    """

    locations = []

    for raw in ANTARCTIC_LOCATIONS:
        item = dict(raw)

        reference_lat = float(item["lat"])
        reference_lon = float(item["lon"])

        item["reference_lat"] = reference_lat
        item["reference_lon"] = reference_lon

        anchor = None

        if ocean_surface.available:

            if ocean_surface.is_navigable(
                reference_lat,
                reference_lon,
            ):
                anchor = {
                    "lat": reference_lat,
                    "lon": reference_lon,
                    "distance_km": 0.0,
                    "source": "CMEMS + NSIDC RealOceanSurface",
                }

                item["routing_mode"] = (
                    "DIRECT_VALIDATED_REFERENCE"
                )

            else:
                anchor = ocean_surface.nearest_navigable_point(
                    reference_lat,
                    reference_lon,
                    max_radius_km=150.0,
                )

                if anchor:
                    item["routing_mode"] = (
                        "NEAREST_VALIDATED_MARINE_ACCESS"
                    )
                else:
                    item["routing_mode"] = (
                        "REFERENCE_ONLY"
                    )

        else:
            item["routing_mode"] = (
                "REFERENCE_ONLY"
            )

        item["routing_eligible"] = bool(anchor)
        item["route_anchor"] = anchor

        if anchor:
            item["route_lat"] = float(
                anchor["lat"]
            )
            item["route_lon"] = float(
                anchor["lon"]
            )
        else:
            item["route_lat"] = None
            item["route_lon"] = None

        if (
            anchor
            and
            float(anchor.get("distance_km", 0.0)) > 0.0
        ):
            item["routing_note"] = (
                "Published reference coordinate preserved. "
                "Ship routing uses the nearest CMEMS + NSIDC "
                f"validated marine point {float(anchor['distance_km']):.1f} km away."
            )

        elif anchor:
            item["routing_note"] = (
                "Reference coordinate itself is a validated marine route point."
            )

        else:
            item["routing_note"] = (
                "No CMEMS + NSIDC validated marine route point "
                "was found within 150 km."
            )

        locations.append(item)

    return {
        "operational_latitude_limit": -45.0,
        "coordinate_order": "latitude, longitude",
        "marine_anchor_radius_km": 150.0,
        "locations": locations,
        "selection_note": (
            "Named station/reference coordinates remain unchanged. "
            "Routing uses a separate verified marine anchor when required."
        ),
    }

@app.get("/api/navigation/surface-check")
def navigation_surface_check(lat: float, lon: float):
    """Validate a map-picked point against the genuine CMEMS/NSIDC surface."""
    if not (-90.0 <= float(lat) <= -45.0 and -180.0 <= float(lon) <= 180.0):
        return JSONResponse(status_code=400, content={"error": "Point must be within the Antarctic/Southern Ocean operational area (90°S to 45°S)."})
    if not ocean_surface.available:
        return JSONResponse(status_code=503, content={"error": "Required CMEMS/NSIDC navigation surface is unavailable."})
    description = ocean_surface.describe_point(float(lat), float(lon))
    nearest = None
    best = float("inf")
    for loc in ANTARCTIC_LOCATIONS:
        d = haversine_distance(float(lat), float(lon), float(loc["lat"]), float(loc["lon"]))
        if d < best:
            best = d
            nearest = loc
    return {
        "lat": float(lat),
        "lon": float(lon),
        "navigable": bool(description.get("navigable")),
        "surface": description,
        "source": "CMEMS + NSIDC RealOceanSurface",
        "coordinate_precision": "Map click coordinate rounded by browser display only; routing uses the numeric WGS84 value received by the API.",
        "nearest_location": None if nearest is None else {
            "id": nearest["id"], "name": nearest["name"], "distance_km": round(best, 2),
            "source": nearest.get("source"), "kind": nearest.get("kind"),
        },
        "message": "VALID NAVIGABLE OCEAN CELL" if description.get("navigable") else "INVALID LAND / COAST / NO-DATA CELL",
    }

@app.get("/api/system/health")
def system_health():
    """Lightweight startup diagnostic used by the UI and deployment troubleshooting."""
    datasets = {
        "icebergs": os.path.exists(ICEBERG_FILE),
        "ocean": os.path.exists(os.path.join(RAW_DIR, "ocean_currents_offline.nc")) or os.path.exists(os.path.join(PROCESSED_DIR, "ocean_combined_processed.nc")),
        "era5": bool(__import__("glob").glob(os.path.join(PROCESSED_DIR, "era5_*_processed.nc"))) or bool(__import__("glob").glob(os.path.join(RAW_DIR, "era5_*.nc"))),
        "nsidc": bool(__import__("glob").glob(os.path.join(RAW_DIR, "S_*_concentration_v4.0.tif"))),
        "usnic_extent": os.path.exists(ICE_EXTENT_DIR),
    }
    return {
        "status": "ok" if all(datasets.values()) else "degraded",
        "map_configured": True,
        "map_provider": "OpenFreeMap + OpenStreetMap fallback",
        "map_mode": "KEYLESS_WITH_FALLBACK",
        "map_key_required": False,
        "mappls_key_set": bool(os.getenv("MAPPLS_STATIC_KEY", "").strip()),
        "aisstream_key_set": bool(os.getenv("AISSTREAM_API_KEY", "").strip()),
        "aisstream_status": ais_tracker.status if ais_tracker.selected == "aisstream" else "NOT_SELECTED",
        "ais_provider": ais_tracker.provider_name,
        "ais_provider_selected": ais_tracker.selected,
        "ais_provider_enabled": ais_tracker.enabled,
        "precision_forecast": {
            "version": "5.1 + NAVX-DRIFT-ML",
            "online_forcing": "Open-Meteo Marine currents + ECMWF IFS wind with cached CMEMS/ERA5 fallback",
            "usnic_motion_assimilation": True,
            "observation_time_aware": True,
            "spatial_forcing_blend": True,
            "ensemble_members": 48,
            "validated_navigation_accuracy": False,
            "ml_residual": iceberg_ml.public_status(),
        },
        "ai_ml": {
            "iceberg_drift": iceberg_ml.public_status(),
            "ais_anomaly": ais_ml.public_status(),
            "structured_decision_support": True,
        },
        "datasets": datasets,
        "navigation_surface": {
            "available": ocean_surface.available,
            "sources": ocean_surface.sources,
        },
        "database": database_status(),
        "automatic_ingestion": ingestion_scheduler.public_status(),
        "app_url": "/app/"
    }


@app.get("/api/system/ingestion")
def get_ingestion_status():
    return {
        "scheduler": ingestion_scheduler.public_status(),
        "database": database_status(),
        "database_summary": database_summary(),
        **scheduler_status(),
    }


@app.post("/api/system/ingestion/run/{source}")
async def run_ingestion_now(source: str, x_navx_admin_token: str | None = Header(default=None)):
    expected = (os.getenv("NAVX_ADMIN_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="Manual ingestion API is disabled. Use scripts/ingest_now.py locally or configure NAVX_ADMIN_TOKEN.")
    if not x_navx_admin_token or not secrets.compare_digest(x_navx_admin_token, expected):
        raise HTTPException(status_code=403, detail="Invalid admin token")
    source = source.strip().lower()
    jobs = {
        "usnic": lambda: sync_usnic(usnic_live),
        "iceberg_history": lambda: sync_iceberg_history(True),
        "ais": lambda: sync_ais(ais_tracker),
        "nsidc": sync_nsidc,
        "ndbc": sync_ndbc,
        "sentinel1": sync_sentinel1,
        "cmems": sync_cmems,
        "era5": sync_era5,
    }
    if source not in jobs:
        raise HTTPException(status_code=400, detail="source must be one of: usnic, iceberg_history, ais, nsidc, ndbc, sentinel1, cmems, era5")
    return await asyncio.to_thread(jobs[source])


@app.get("/api/data/database/summary")
def get_database_summary():
    return {"database": database_status(), **database_summary()}


@app.get("/api/data/buoys")
def get_buoy_observations(limit: int = 200):
    observations = recent_buoy_observations(limit=limit)
    return {
        "source": "NOAA NDBC",
        "data_type": "LATEST_VERIFIED_OBSERVATIONS_PERSISTED_BY_NAVX",
        "count": len(observations),
        "observations": observations,
    }


@app.get("/api/data/satellite/scenes")
def get_satellite_scenes(limit: int = 100):
    scenes = recent_satellite_scenes(limit=limit)
    return {
        "source": "Copernicus Data Space Ecosystem",
        "collection": "sentinel-1-grd",
        "data_semantics": "CATALOGUE_METADATA_ONLY",
        "analysis_claim": "No SAR iceberg detection is claimed by this endpoint.",
        "count": len(scenes),
        "scenes": scenes,
    }


@app.get("/api/data/icebergs")
def get_icebergs(refresh: bool = False):
    """Return every currently available official USNIC tracked iceberg.

    ``refresh=true`` attempts to fetch the official current CSV, then falls back
    to the last successful/bundled snapshot when the machine is offline. USNIC
    publishes the iceberg table on a weekly cadence, so the positions are
    freshest official observations rather than continuous GPS telemetry.
    """
    payload = usnic_live.refresh(force=False) if refresh else usnic_live.load_best()
    features = payload.get("features", [])
    meta = payload.get("metadata", {})
    observed_dates = [f.get("properties", {}).get("date_observed") for f in features]
    observed_dates = [d for d in observed_dates if d]
    newest_age = None
    ages = [f.get("properties", {}).get("observation_age_hours") for f in features]
    ages = [a for a in ages if isinstance(a, (int, float))]
    if ages:
        newest_age = min(ages)
    return {
        "source": "USNIC",
        "source_url": "https://usicecenter.gov/Products/AntarcIcebergs/",
        "cadence": "WEEKLY_OFFICIAL_OBSERVATIONS",
        "realtime": False,
        "freshness_note": "USNIC publishes Antarctic iceberg tracking positions weekly; NAV-X refreshes the official current file and never fabricates additional positions.",
        "timestamp": max(observed_dates) if observed_dates else None,
        "retrieved_at": meta.get("retrieved_at") or usnic_live.last_success,
        "cache_mode": meta.get("mode", "UNKNOWN"),
        "refresh_error": meta.get("refresh_error") or usnic_live.last_error,
        "newest_observation_age_hours": newest_age,
        "count": len(features),
        "icebergs": {"type": "FeatureCollection", "features": features}
    }

@app.get("/api/data/icebergs/all/catalog")
def get_all_iceberg_catalog(
    q: str | None = None,
    limit: int = 5000,
):
    return iceberg_unified_catalog(
        limit=limit,
        search=q,
    )


@app.get("/api/data/icebergs/all/{iceberg_id}/track")
def get_all_iceberg_track(
    iceberg_id: str,
    limit: int = 20000,
):
    return iceberg_unified_track(
        iceberg_id=iceberg_id,
        limit=limit,
    )

@app.get("/api/data/icebergs/history/catalog")
def get_iceberg_history_catalog(q: str | None = None, limit: int = 2000):
    """Combined historical catalogue plus current USNIC designations.

    Historical BYU/NIC positions are clearly separated from current USNIC
    observations and are never promoted to current navigation hazards.
    """
    return iceberg_history_summary(limit=limit, search=q)


@app.get("/api/data/icebergs/{iceberg_id}/history")
def get_iceberg_history(iceberg_id: str):
    """Backward-compatible official USNIC history only.

    This endpoint intentionally preserves the original contract used by the
    routing/precision tests: every returned point is an archived official USNIC
    table fix. The expanded research history is available at /history/all.
    """
    points = load_history(Path(DATA_DIR), iceberg_id)
    return {
        "iceberg_id": iceberg_id.upper(),
        "count": len(points),
        "timestamp_assumption": "USNIC public table is date-only; displayed history timestamps are placed at 12:00 UTC for computation and should be interpreted as ±12 h.",
        "observations": [
            {
                "timestamp_assumed": p.timestamp.isoformat(),
                "date": p.timestamp.date().isoformat(),
                "latitude": p.lat,
                "longitude": p.lon,
                "source_file": p.source_file,
                "source": "USNIC",
                "position_type": "OFFICIAL_USNIC_TABLE_FIX",
                "historical_only": False,
            }
            for p in points
        ],
    }


@app.get("/api/data/icebergs/{iceberg_id}/history/all")
def get_complete_iceberg_history(iceberg_id: str):
    """Published BYU/NIC historical positions plus current/archived USNIC fixes."""
    observations = iceberg_history_records(iceberg_id)
    return {
        "iceberg_id": iceberg_id.upper(),
        "count": len(observations),
        "authoritative_current_source": "USNIC",
        "historical_source": "BYU/NIC consolidated Antarctic iceberg database",
        "scientific_integrity": (
            "Historical published positions remain historical. Current USNIC fixes remain authoritative "
            "for present hazards; model forecast positions are not inserted into observation history."
        ),
        "observations": observations,
    }


@app.get("/api/data/icebergs/archive")
def get_iceberg_archive():
    """Return archived official USNIC iceberg snapshots bundled with NAV-X.

    Every point comes directly from a stored USNIC CSV snapshot. No
    interpolation, animation frames, or synthetic positions are added.
    """
    import csv
    import glob

    snapshots = []
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "usnic_icebergs_*.csv"))):
        features = []
        observed_dates = []
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    try:
                        lat = float(row.get("Latitude", ""))
                        lon = float(row.get("Longitude", ""))
                    except (TypeError, ValueError):
                        continue
                    observed = (row.get("Last Update") or "").strip() or None
                    if observed:
                        observed_dates.append(observed)
                    def _num(name):
                        try:
                            return float(row.get(name, ""))
                        except (TypeError, ValueError):
                            return None
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            "id": (row.get("Iceberg") or "UNKNOWN").strip(),
                            "length_nm": _num("Length (NM)"),
                            "width_nm": _num("Width (NM)"),
                            "area_sqkm": _num("Area (sqKM)"),
                            "date_observed": observed,
                            "source": "USNIC archived official snapshot",
                            "position_type": "OFFICIAL_USNIC_TABLE_FIX",
                        },
                    })
        except OSError:
            continue
        file_stamp = Path(path).stem.replace("usnic_icebergs_", "")
        snapshots.append({
            "snapshot_id": file_stamp,
            "source_file": os.path.basename(path),
            "observed_date": max(observed_dates) if observed_dates else None,
            "count": len(features),
            "icebergs": {"type": "FeatureCollection", "features": features},
        })
    return {
        "source": "U.S. National Ice Center (USNIC)",
        "data_type": "ARCHIVED_OFFICIAL_SNAPSHOTS",
        "scientific_integrity": "Verbatim archived USNIC table coordinates; no synthetic interpolation.",
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }


@app.post("/api/data/icebergs/refresh")
def refresh_icebergs():
    payload = usnic_live.refresh(force=True, min_interval_seconds=0)
    return {
        "ok": bool(payload.get("features")),
        "count": len(payload.get("features", [])),
        "metadata": payload.get("metadata", {}),
    }

@app.get("/api/data/vessels")
def get_live_vessels(
    max_age_minutes: int = 180,
    limit: int = 500,
    lat: float | None = None,
    lon: float | None = None,
    radius_nm: float = 50.0,
):
    """Return only genuine AIS positions from the configured provider.

    AISStream and AISHub cover their configured Southern Ocean subscription.
    Datalastic is an on-demand circular scan and therefore needs ``lat``/``lon``;
    its provider limit is capped to 50 NM by the adapter. No simulated vessel
    fallback is ever returned.
    """
    return ais_tracker.snapshot(
        max_age_minutes=max_age_minutes, limit=limit,
        lat=lat, lon=lon, radius_nm=radius_nm,
    )

@app.get("/api/config/realtime")
def get_realtime_config():
    return {
        "icebergs": {
            "provider": "USNIC",
            "mode": "FRESHEST_OFFICIAL_WEEKLY",
            "auto_refresh": True,
            "source_url": "https://usicecenter.gov/Products/AntarcIcebergs/",
        },
        "vessels": ais_tracker.config_public(),
    }


@app.get("/api/data/weather")
def get_weather():
    import glob
    import xarray as xr
    era5_files = glob.glob(os.path.join(PROCESSED_DIR, "era5_*_processed.nc"))
    
    if era5_files:
        try:
            ds = xr.open_dataset(era5_files[0])
            return {
                "source": "Copernicus ERA5",
                "timestamp": str(ds.valid_time.values[0]) if hasattr(ds, 'valid_time') else None,
                "count": ds.sizes.get('latitude', 0) * ds.sizes.get('longitude', 0),
                "grid": f"{ds.sizes.get('latitude', 0)}x{ds.sizes.get('longitude', 0)}",
                "variables": list(ds.data_vars.keys())
            }
        except Exception as e:
            # Keep the dashboard operational even when an optional NetCDF backend
            # is unavailable or a cached file cannot be decoded. The UI can show
            # the degraded state while other datasets continue to work.
            return {
                "source": "Copernicus ERA5",
                "timestamp": None,
                "count": 0,
                "error": f"Cached ERA5 file could not be opened: {e}",
                "required_action": "Install requirements.txt dependencies (including netcdf4) or refresh the cached ERA5 file."
            }

    return {
        "source": "Copernicus ERA5",
        "timestamp": None,
        "count": 0,
        "error": "Missing or invalid CDS API credentials. Please set up ~/.cdsapirc.",
        "required_action": "Register at https://cds.climate.copernicus.eu/ and configure API token."
    }

@app.get("/api/data/ocean")
def get_ocean():
    from src.data_providers.ocean_provider import OceanDataOrchestrator
    orchestrator = OceanDataOrchestrator()
    try:
        _, metadata = orchestrator.get_data()
        return metadata
    except Exception as e:
        return {
            "source": "UNAVAILABLE",
            "error": str(e),
            "required_action": "Configure CMEMS credentials OR provide an offline NetCDF file in data/raw/"
        }

@app.get("/api/data/ice-extent-trends")
def get_ice_extent_trends():
    """
    Returns official, verbatim USNIC Antarctic sea ice daily extent records (2024-2026)
    and 10-year climatological average (2009-2018), adapted from:
    https://usicecenter.gov/Products/AntarcTrendGraph
    
    STRICT SCIENTIFIC INTEGRITY:
    - Verbatim observations from USNIC raw files in data/raw/usnic_extent/.
    - Zero synthetic points or artificial smoothing.
    """
    extent_dir = ICE_EXTENT_DIR
    if not os.path.exists(extent_dir):
        raise HTTPException(status_code=404, detail="USNIC extent datasets not found locally.")

    years_data = {}
    stats_data = {}

    for year in ["2026", "2025", "2024"]:
        fpath = os.path.join(extent_dir, f"ANTARC_{year}_daily_ice_extents.txt")
        if not os.path.exists(fpath):
            continue

        entries = []
        extents_m = []
        min_entry = None
        max_entry = None

        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "," not in line:
                    continue
                parts = line.split(",")
                date_str = parts[0].strip()
                try:
                    val_sqkm = float(parts[1].strip())
                    val_millions = round(val_sqkm / 1_000_000.0, 3)
                    entry = {"date": date_str, "extent_sqkm": val_sqkm, "extent_millions_sqkm": val_millions}
                    entries.append(entry)
                    extents_m.append(val_millions)

                    if min_entry is None or val_millions < min_entry["extent_millions_sqkm"]:
                        min_entry = entry
                    if max_entry is None or val_millions > max_entry["extent_millions_sqkm"]:
                        max_entry = entry
                except ValueError:
                    continue

        if entries:
            avg_val = round(sum(extents_m) / len(extents_m), 3)
            years_data[year] = entries
            stats_data[year] = {
                "count": len(entries),
                "maximum": max_entry,
                "minimum": min_entry,
                "daily_average": avg_val
            }

    # 10-year Climatological Baseline (2009-2018)
    climo_file = os.path.join(extent_dir, "10yrclimo.csv")
    climo_entries = []
    if os.path.exists(climo_file):
        with open(climo_file, "r", encoding="utf-8") as f:
            doy = 1
            for line in f:
                line = line.strip()
                if not line or "," not in line:
                    continue
                parts = line.split(",")
                try:
                    # Column 1 is Antarctic extent
                    ant_val = float(parts[1].strip())
                    climo_entries.append({
                        "doy": doy,
                        "extent_sqkm": ant_val,
                        "extent_millions_sqkm": round(ant_val / 1_000_000.0, 3)
                    })
                    doy += 1
                except (ValueError, IndexError):
                    continue

    # Seasonal Navigability Phase Determination (based on latest 2026 data)
    latest_2026 = years_data.get("2026", [])[-1] if years_data.get("2026") else None
    phase_info = {
        "phase": "Unknown",
        "navigability_window": "Evaluating",
        "impact_on_icebergs": "Unknown"
    }

    if latest_2026:
        val = latest_2026["extent_millions_sqkm"]
        if val <= 5.0:
            phase_info = {
                "phase": "Summer Minimum / Peak Open Window",
                "navigability_window": "HIGH (Unrestricted outer polar seas)",
                "impact_on_icebergs": "Peak Free Drift (Icebergs fully coupled to ocean currents & winds; highest encounters)",
                "seasonal_months": "January - March"
            }
        elif val <= 10.0:
            phase_info = {
                "phase": "Autumn Freeze-Up / Contracting Corridors",
                "navigability_window": "MODERATE (Fast ice advancing; corridors narrowing)",
                "impact_on_icebergs": "Partial Entrapment (Tabular icebergs encountering expanding pack ice)",
                "seasonal_months": "April - June"
            }
        elif val <= 15.0:
            phase_info = {
                "phase": "Winter Expansion / Advanced Ice Season",
                "navigability_window": "RESTRICTED (Ice-strengthened vessels and icebreakers only)",
                "impact_on_icebergs": "Pack Ice Locked (Icebergs predominantly locked in heavy multi-year pack)",
                "seasonal_months": "July - August"
            }
        else:
            phase_info = {
                "phase": "Winter Maximum / Closed Corridors",
                "navigability_window": "CRITICAL (Heavy pack ice barrier; icebreaker escort required)",
                "impact_on_icebergs": "Complete Entrapment (Minimal independent drift)",
                "seasonal_months": "September - October"
            }

    return {
        "source": "U.S. National Ice Center (USNIC)",
        "reference": "https://usicecenter.gov/Products/AntarcTrendGraph",
        "provenance": "Official USNIC Daily Ice Extent Analysis",
        "scientific_integrity": "100% genuine USNIC records; no synthetic interpolation or altered values.",
        "years": years_data,
        "climo_10yr": climo_entries,
        "stats": stats_data,
        "latest_observation": latest_2026,
        "navigability_context": phase_info
    }


def sample_environmental_forcing(lat: float, lon: float) -> dict:
    """Sample genuine cached CMEMS current and ERA5 wind at ``lat/lon``.

    The preferred reader is xarray/NetCDF4.  Lightweight demo environments may
    not have the optional NetCDF engine installed, so the same NetCDF4/HDF5
    bytes are read through h5py as a compatibility fallback.  Missing/NaN values
    are never replaced with zero.
    """
    import numpy as np

    ocean_file = os.path.join(RAW_DIR, "ocean_currents_offline.nc")
    if not os.path.exists(ocean_file):
        ocean_file = os.path.join(PROCESSED_DIR, "ocean_combined_processed.nc")
    if not os.path.exists(ocean_file):
        raise HTTPException(status_code=503, detail="CMEMS ocean current dataset is unavailable in local/cached data. Cannot sample physical forcing.")

    era5_file = os.path.join(RAW_DIR, "era5_antarctic_2026-08-27.nc")
    if not os.path.exists(era5_file):
        era5_file = os.path.join(PROCESSED_DIR, "era5_antarctic_2026-08-27_processed.nc")
    if not os.path.exists(era5_file):
        raise HTTPException(status_code=503, detail="ERA5 atmospheric wind dataset is unavailable in local/cached data. Cannot sample physical forcing.")

    def _nearest(values, target):
        arr = np.asarray(values, dtype=float)
        return int(np.nanargmin(np.abs(arr - float(target))))

    def _read_h5(path: str, lat_name: str, lon_name: str, u_names: tuple[str, ...], v_names: tuple[str, ...]):
        import h5py
        with h5py.File(path, "r") as h5:
            if lat_name not in h5 or lon_name not in h5:
                raise KeyError("coordinate variables unavailable")
            u_name = next((n for n in u_names if n in h5), None)
            v_name = next((n for n in v_names if n in h5), None)
            if not u_name or not v_name:
                raise KeyError("forcing variables unavailable")
            lats = np.asarray(h5[lat_name][...], dtype=float)
            lons = np.asarray(h5[lon_name][...], dtype=float)
            iy, ix = _nearest(lats, lat), _nearest(lons, lon)
            u = np.asarray(h5[u_name][...], dtype=float)
            v = np.asarray(h5[v_name][...], dtype=float)
            # Coordinate axes are the final latitude/longitude dimensions in
            # the bundled CMEMS/ERA5 files. Select the first actual time/depth
            # record only when the source itself contains that dimension.
            u_val = float(np.asarray(u[..., iy, ix]).reshape(-1)[0])
            v_val = float(np.asarray(v[..., iy, ix]).reshape(-1)[0])
            return u_val, v_val

    try:
        import xarray as xr
        with xr.open_dataset(ocean_file) as ds_o:
            u_var = "uo" if "uo" in ds_o else "ocean_u"
            v_var = "vo" if "vo" in ds_o else "ocean_v"
            s_o = ds_o.sel(latitude=lat, longitude=lon, method="nearest")
            uo_val = float(np.asarray(s_o[u_var].values).reshape(-1)[0])
            vo_val = float(np.asarray(s_o[v_var].values).reshape(-1)[0])
    except Exception:
        try:
            uo_val, vo_val = _read_h5(ocean_file, "latitude", "longitude", ("uo", "ocean_u"), ("vo", "ocean_v"))
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to read the cached CMEMS current dataset with the available NetCDF/HDF5 readers.")

    if not np.isfinite(uo_val) or not np.isfinite(vo_val):
        raise HTTPException(status_code=422, detail=f"CMEMS ocean currents at lat={lat}, lon={lon} are undefined (likely land/grounded shelf/no-data). Physical drift cannot be calculated without verified ocean forcing.")

    try:
        import xarray as xr
        with xr.open_dataset(era5_file) as ds_e:
            u_var_e = "u10" if "u10" in ds_e else "10u"
            v_var_e = "v10" if "v10" in ds_e else "10v"
            s_e = ds_e.sel(latitude=lat, longitude=lon, method="nearest")
            wu_val = float(np.asarray(s_e[u_var_e].values).reshape(-1)[0])
            wv_val = float(np.asarray(s_e[v_var_e].values).reshape(-1)[0])
    except Exception:
        try:
            wu_val, wv_val = _read_h5(era5_file, "latitude", "longitude", ("u10", "10u"), ("v10", "10v"))
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to read the cached ERA5 wind dataset with the available NetCDF/HDF5 readers.")

    if not np.isfinite(wu_val) or not np.isfinite(wv_val):
        raise HTTPException(status_code=422, detail=f"ERA5 atmospheric wind at lat={lat}, lon={lon} is undefined (no-data). Physical drift cannot be calculated without verified wind forcing.")

    return {
        "ocean_u": uo_val,
        "ocean_v": vo_val,
        "wind_u": wu_val,
        "wind_v": wv_val,
        "source": "REAL LOCAL / CACHED (CMEMS ocean currents + ERA5 / ECMWF wind)",
        "data_mode": "VERIFIED_CACHED_SCIENTIFIC_FORCING",
    }

@app.get("/api/environmental/sample")
def get_environmental_sample(lat: float, lon: float):
    """
    Samples real ocean current (uo, vo) from CMEMS offline NetCDF and
    real wind (u10, v10) from ERA5 offline NetCDF at the given (lat, lon).
    Returns clear 422 error if coordinates are on land or undefined.
    """
    return sample_environmental_forcing(lat, lon)

@app.get("/api/environmental/precision-sample")
def get_precision_environmental_sample(lat: float, lon: float):
    """Fresh current model guidance for the operator display, with cached fallback."""
    from src.data_providers.forecast_forcing import OpenMeteoForcingProvider, sample_control_series
    now = datetime.now(timezone.utc)
    try:
        provider = OpenMeteoForcingProvider()
        series = provider.fetch_multi([(lat, lon)], now - timedelta(hours=6), now + timedelta(hours=12))
        if not series:
            raise RuntimeError("No online forcing series returned")
        sample = sample_control_series(series[0], now)
        return {
            **sample,
            "source": "REAL ONLINE MODEL GUIDANCE (Open-Meteo Marine ocean-current guidance + ECMWF IFS wind)",
            "mode": "FRESH_MODEL_GUIDANCE",
            "sample_time": now.isoformat(),
            "current_resolution_note": "Marine current guidance ~0.08° (~8 km); coastal accuracy is limited.",
            "wind_resolution_note": "ECMWF IFS high-resolution global forecast guidance where available.",
            "navigation_grade": False,
        }
    except Exception as online_exc:
        local = sample_environmental_forcing(lat, lon)
        return {
            **local,
            "mode": "CACHED_FALLBACK",
            "sample_time": None,
            "online_error": str(online_exc),
            "navigation_grade": False,
        }

from src.models.trajectory import PhysicsTrajectoryModel
from src.models.precision_trajectory import PrecisionIcebergTrajectoryModel
from src.data_providers.forecast_forcing import OpenMeteoForcingProvider, fallback_constant_series, sample_control_series
from src.data_providers.iceberg_history import estimate_recent_motion, load_history
from src.models.risk import NavigationRiskEngine

def _parse_observation_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            # USNIC table is date-only. Midday minimizes the maximum unknown
            # time error; the response states this assumption explicitly.
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc, hour=12)
        except ValueError:
            continue
    return None

def _nearest_track_position(track: list[dict], when: datetime) -> tuple[float, float]:
    p = min(track, key=lambda x: abs((x["time"] - when).total_seconds()))
    return float(p["lat"]), float(p["lon"])

def _source_coordinate_resolution_km(iceberg_id: str, lat: float, lon: float) -> float:
    """Estimate *printed coordinate resolution*, not geolocation accuracy.

    USNIC's CSV can print latitude/longitude with different decimal precision.
    We propagate that quantization scale into the sensitivity ensemble rather
    than displaying more coordinate precision than the source actually gives.
    """
    try:
        payload = usnic_live.load_best()
        feat = next((f for f in payload.get("features", []) if str(f.get("properties", {}).get("id", "")).upper() == str(iceberg_id).upper()), None)
        props = (feat or {}).get("properties", {})
        lat_txt = str(props.get("source_lat_text", lat))
        lon_txt = str(props.get("source_lon_text", lon))
        def digits(x: str) -> int:
            x = x.strip().split("e")[0].split("E")[0]
            return len(x.split(".", 1)[1]) if "." in x else 0
        lat_step_deg = 10.0 ** (-digits(lat_txt))
        lon_step_deg = 10.0 ** (-digits(lon_txt))
        lat_km = 111.32 * lat_step_deg
        lon_km = 111.32 * max(0.05, abs(__import__("math").cos(__import__("math").radians(lat)))) * lon_step_deg
        return max(0.1, min(20.0, (lat_km*lat_km + lon_km*lon_km) ** 0.5))
    except Exception:
        return 1.5

def _iceberg_ml_properties(iceberg_id: str) -> dict:
    try:
        payload = usnic_live.load_best()
        feat = next((f for f in payload.get("features", []) if str(f.get("properties", {}).get("id", "")).upper() == str(iceberg_id).upper()), None)
        p = (feat or {}).get("properties", {})
        return {
            "length_nm": p.get("length_nm"),
            "width_nm": p.get("width_nm"),
            "area_sqkm": p.get("area_sqkm"),
        }
    except Exception:
        return {"length_nm": None, "width_nm": None, "area_sqkm": None}


def _attach_ml_prior(motion: dict, iceberg_id: str, lat: float, lon: float, forcing: dict) -> tuple[dict, dict]:
    """Attach the verified-gated ML residual prior to physics assimilation."""
    props = _iceberg_ml_properties(iceberg_id)
    pred = iceberg_ml.predict_residual(
        lat=lat, lon=lon, length_nm=props.get("length_nm"), width_nm=props.get("width_nm"),
        area_sqkm=props.get("area_sqkm"), ocean_u=float(forcing.get("ocean_u") or 0.0),
        ocean_v=float(forcing.get("ocean_v") or 0.0), wind_u=float(forcing.get("wind_u") or 0.0),
        wind_v=float(forcing.get("wind_v") or 0.0),
    )
    out = dict(motion or {})
    if pred.get("available") and pred.get("applied"):
        has_observed_motion = bool(out.get("available"))
        out["ml_prior_applied"] = True
        out["ml_residual_u_ms"] = pred.get("residual_u_ms")
        out["ml_residual_v_ms"] = pred.get("residual_v_ms")
        out["ml_prior_weight"] = 0.25 if has_observed_motion else 0.70
        out["ml_decay_hours"] = 72.0
        out["ml_model_version"] = pred.get("model_version")
        out["ml_note"] = (
            "Machine-learning residual prior trained on official USNIC transitions and cached CMEMS/ERA5 forcing. "
            "Direct observed-motion assimilation is weighted more strongly when available."
        )
    return out, pred


def _precision_prediction(iceberg_id: str, lat: float, lon: float, observation_date: str | None,
                          ocean_u: float | None, ocean_v: float | None,
                          wind_u: float | None, wind_v: float | None) -> dict:
    now = datetime.now(timezone.utc)
    obs_time = _parse_observation_time(observation_date) or now
    if obs_time > now:
        obs_time = now
    end = now + timedelta(hours=72)
    model = PrecisionIcebergTrajectoryModel()
    motion = estimate_recent_motion(Path(DATA_DIR), iceberg_id)
    ml_meta = {"available": iceberg_ml.available, "applied": False, "reason": "ML prior is disabled for manual forcing or unavailable."}

    manual = ocean_u is not None and ocean_v is not None
    if manual:
        constant = {
            "ocean_u": float(ocean_u), "ocean_v": float(ocean_v),
            "wind_u": float(wind_u or 0.0), "wind_v": float(wind_v or 0.0),
        }
        control_times = [obs_time]
        control_series = fallback_constant_series(constant, [(lat, lon)])
        forcing_meta = {
            "online": False, "time_varying": False, "spatially_refined": False,
            "source": "MANUALLY_SPECIFIED_API_FORCING", "control_points": 1,
        }
    else:
        provider = OpenMeteoForcingProvider()
        try:
            first_series = provider.fetch_multi([(lat, lon)], obs_time, end)
            if not first_series:
                raise RuntimeError("fresh forcing provider returned no series")
            # Estimate the environmental residual against recent observed USNIC
            # motion before generating the provisional path.
            f0 = sample_control_series(first_series[0], obs_time)
            if motion.get("available"):
                motion = dict(motion)
                motion["residual_u_ms"] = float(motion["u_ms"]) - (float(f0.get("ocean_u") or 0.0) + model.windage*float(f0.get("wind_u") or 0.0))
                motion["residual_v_ms"] = float(motion["v_ms"]) - (float(f0.get("ocean_v") or 0.0) + model.windage*float(f0.get("wind_v") or 0.0))

            provisional = model.integrate(lat, lon, obs_time, end, [obs_time], first_series, motion)
            control_times = []
            control_positions = []
            t = obs_time
            # Six-hour spatial control points keep network load bounded while
            # letting the second pass sample forcing along the moving path.
            while t <= end and len(control_times) < 40:
                control_times.append(t)
                control_positions.append(_nearest_track_position(provisional, t))
                t += timedelta(hours=6)
            if control_times[-1] < end:
                control_times.append(end)
                control_positions.append(_nearest_track_position(provisional, end))
            refined = provider.fetch_multi(control_positions, obs_time, end)
            if len(refined) != len(control_times):
                raise RuntimeError("spatial forcing refinement returned incomplete control points")
            control_series = refined
            # Recompute residual against the refined first control point.
            f0 = sample_control_series(control_series[0], obs_time)
            if motion.get("available"):
                motion["residual_u_ms"] = float(motion["u_ms"]) - (float(f0.get("ocean_u") or 0.0) + model.windage*float(f0.get("wind_u") or 0.0))
                motion["residual_v_ms"] = float(motion["v_ms"]) - (float(f0.get("ocean_v") or 0.0) + model.windage*float(f0.get("wind_v") or 0.0))
            motion, ml_meta = _attach_ml_prior(motion, iceberg_id, lat, lon, f0)
            forcing_meta = {
                "online": True, "time_varying": True, "spatially_refined": True,
                "source": "REAL ONLINE MODEL GUIDANCE (Open-Meteo Marine ocean-current guidance + ECMWF IFS wind)",
                "current_resolution_note": "Marine current guidance is approximately 0.08° (~8 km); coastal accuracy is limited.",
                "wind_resolution_note": "ECMWF IFS HRES wind guidance is global high-resolution model output where available.",
                "control_points": len(control_times),
            }
        except Exception as online_exc:
            # Offline fallback preserves operation but is explicitly downgraded.
            local = sample_environmental_forcing(lat, lon)
            control_times = [obs_time]
            control_series = fallback_constant_series(local, [(lat, lon)])
            if motion.get("available"):
                motion = dict(motion)
                motion["residual_u_ms"] = float(motion["u_ms"]) - (float(local.get("ocean_u") or 0.0) + model.windage*float(local.get("wind_u") or 0.0))
                motion["residual_v_ms"] = float(motion["v_ms"]) - (float(local.get("ocean_v") or 0.0) + model.windage*float(local.get("wind_v") or 0.0))
            motion, ml_meta = _attach_ml_prior(motion, iceberg_id, lat, lon, local)
            forcing_meta = {
                "online": False, "time_varying": False, "spatially_refined": False,
                "source": local.get("source", "CACHED_LOCAL_FORCING"), "control_points": 1,
                "online_error": str(online_exc),
                "quality_warning": "Fresh online model guidance unavailable; using one cached local vector for all forecast hours.",
            }

    result = model.build_result(
        iceberg_id=iceberg_id, start_lat=lat, start_lon=lon, observation_time=obs_time, now=now,
        horizons_hours=[6, 12, 24, 48, 72], control_times=control_times, control_series=control_series,
        observed_motion=motion, forcing_metadata=forcing_meta, ensemble_members=48,
        source_position_resolution_km=_source_coordinate_resolution_km(iceberg_id, lat, lon),
        observation_time_uncertainty_hours=12.0,
    )
    result["ml_correction"] = {
        "status": "APPLIED" if ml_meta.get("applied") else ("AVAILABLE_NOT_APPLIED" if ml_meta.get("available") else "NOT_AVAILABLE"),
        **ml_meta,
        "model_status": iceberg_ml.public_status(),
        "integrity_note": "ML corrects the physics residual only; it never replaces the official USNIC observation.",
    }
    if ml_meta.get("applied"):
        result["model_name"] = "Physics-informed + ML residual iceberg drift model"
        result["model_version"] = f"{result.get('model_version')} + {ml_meta.get('model_version')}"
    return result

def _log_forecast_for_future_verification(result: dict, observation_date: str | None = None) -> None:
    """Persist model output so a later official USNIC fix can verify it.

    No accuracy value is fabricated at forecast time. Verification occurs only
    when a later official observation exists close to a stored target timestamp.
    """
    try:
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "iceberg_id": result.get("iceberg_id"),
            "source_observation_date": observation_date,
            "model_version": result.get("model_version") or result.get("forecast_version") or "precision-v5",
            "trajectory": [
                {
                    "forecast_timestamp": p.get("forecast_timestamp"),
                    "horizon_hours": p.get("horizon_hours"),
                    "latitude": p.get("latitude"),
                    "longitude": p.get("longitude"),
                    "uncertainty_radius_km": p.get("uncertainty_radius_km") or p.get("p90_radius_km"),
                }
                for p in (result.get("trajectory") or [])
                if p.get("forecast_timestamp") and p.get("latitude") is not None and p.get("longitude") is not None
            ],
        }
        if not record["iceberg_id"] or not record["trajectory"]:
            return
        with open(FORECAST_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _verified_forecast_metrics() -> dict:
    """Compare stored forecasts with later official USNIC fixes when available."""
    from src.models.risk import haversine_distance
    if not os.path.exists(FORECAST_LOG_FILE):
        return {
            "verified_samples": 0,
            "status": "AWAITING_FUTURE_OFFICIAL_OBSERVATIONS",
            "note": "NAV-X has started the verification pipeline, but no stored forecast can be scored until a later official USNIC fix exists.",
            "mae_km": {},
        }
    rows = []
    try:
        for line in Path(FORECAST_LOG_FILE).read_text(encoding="utf-8").splitlines()[-2500:]:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        rows = []
    errors: dict[int, list[float]] = {}
    matched = 0
    seen = set()
    for row in rows:
        iid = str(row.get("iceberg_id") or "").upper()
        if not iid:
            continue
        history = load_history(Path(DATA_DIR), iid)
        if not history:
            continue
        for pred in row.get("trajectory") or []:
            try:
                target = datetime.fromisoformat(str(pred["forecast_timestamp"]).replace("Z", "+00:00"))
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                candidates = [h for h in history if abs((h.timestamp - target).total_seconds()) <= 18*3600]
                if not candidates:
                    continue
                obs = min(candidates, key=lambda h: abs((h.timestamp - target).total_seconds()))
                key = (iid, target.date().isoformat(), pred.get("horizon_hours"))
                if key in seen:
                    continue
                seen.add(key)
                err = haversine_distance(float(pred["latitude"]), float(pred["longitude"]), obs.lat, obs.lon)
                horizon = int(round(float(pred.get("horizon_hours") or 0)))
                errors.setdefault(horizon, []).append(err)
                matched += 1
            except Exception:
                continue
    mae = {str(k): round(sum(v)/len(v), 2) for k, v in sorted(errors.items()) if v}
    return {
        "verified_samples": matched,
        "status": "VERIFIED_HISTORY_AVAILABLE" if matched else "AWAITING_FUTURE_OFFICIAL_OBSERVATIONS",
        "mae_km": mae,
        "note": "MAE is reported only for stored forecasts that later matched an official USNIC fix within ±18 h. No score is invented when verification data is absent.",
    }


@app.post("/api/prediction/trajectory")
def predict_trajectory(
    iceberg_id: str,
    lat: float,
    lon: float,
    observation_date: str = None,
    ocean_u: float = None,
    ocean_v: float = None,
    wind_u: float = None,
    wind_v: float = None
):
    """Observation-aware +6h..72h iceberg drift estimate.

    Default mode uses fresh time-varying online model guidance, spatially
    refined along a provisional track, and recent USNIC position history when
    available. Manual u/v parameters remain supported for reproducible tests.
    """
    result = _precision_prediction(iceberg_id, lat, lon, observation_date, ocean_u, ocean_v, wind_u, wind_v)
    _log_forecast_for_future_verification(result, observation_date)
    return result

from fastapi import Body

@app.post("/api/navigation/risk")
def calculate_risk(prediction_data: dict = Body(...), vessel_route: list = Body(...)):
    engine = NavigationRiskEngine()
    trajectory = prediction_data.get('trajectory', [])
    if not trajectory or not vessel_route:
        return JSONResponse(status_code=400, content={"error": "Missing trajectory or route data"})
        
    risk_assessment = engine.assess_risk(vessel_route, trajectory)
    return risk_assessment

from src.models.navigation import VesselSimulator, SpatiotemporalHazardAnalyzer, DataFreshnessChecker

@app.post("/api/navigation/analyze")
def analyze_navigation(payload: dict = Body(...)):
    """
    Spatiotemporal hazard analysis mapping vessel route against iceberg forecasts.
    """
    vessel = payload.get("vessel", {"speed_kmh": 20.0})
    route = payload.get("route", [])
    safety_threshold = payload.get("safety_threshold", 25.0)
    icebergs = payload.get("icebergs", [])
    
    if not route or not icebergs:
        return JSONResponse(status_code=400, content={"error": "Missing route or icebergs"})
        
    start_time = datetime.utcnow()
    
    # 1. Simulate Vessel
    sim = VesselSimulator(speed_kmh=vessel.get("speed_kmh", 20.0))
    vessel_path = sim.interpolate_route(route, start_time)
    
    # 2. Hazard Analysis
    analyzer = SpatiotemporalHazardAnalyzer(safety_threshold_km=safety_threshold)
    risk_report = analyzer.analyze_hazards(vessel_path, icebergs)
    
    # 3. This endpoint analyzes the supplied route only.  Operational route
    # alternatives are intentionally generated exclusively by /optimize using
    # PolarAStarRouter + RealOceanSurface.  The former heuristic east/west
    # detours were not navigation-surface validated and are no longer exposed.
    alternatives = []
    if risk_report["overall_risk"] in ["CRITICAL", "HIGH"]:
        recommendation = "CURRENT ROUTE REQUIRES OPERATOR REVIEW. Generate verified alternatives with /api/navigation/optimize."
        reasons = "A time-matched iceberg hazard was detected on the supplied route; no unverified detour geometry is generated by this analysis endpoint."
    else:
        recommendation = "Current supplied route has no HIGH/CRITICAL iceberg encounter under the provided forecast set."
        reasons = "This is route analysis only; use /api/navigation/optimize for RealOceanSurface-validated alternatives."
            
    # 4. Freshness
    fresh_checker = DataFreshnessChecker()
    provenance = [
        fresh_checker.check_freshness("USNIC Icebergs", start_time.isoformat())
    ]
    
    return {
        "overall_risk": risk_report["overall_risk"],
        "hazards": risk_report["hazards"],
        "closest_approaches": risk_report["min_effective_clearance_km"],
        "minimum_cpa_km": risk_report.get("minimum_cpa_km"),
        "tca_utc": risk_report.get("tca_utc"),
        "closest_iceberg_id": risk_report.get("closest_iceberg_id"),
        "clearance_series": risk_report.get("clearance_series", []),
        "original_route": route,
        "alternatives": alternatives,
        "alternative_route_status": "NOT_GENERATED_HERE_USE_OCEAN_SAFE_OPTIMIZER",
        "recommendation": recommendation,
        "reasons": reasons,
        "data_provenance": provenance,
        "model_version": "1.0-PhysicsKinematic-DecisionSupport",
        "warnings": ["This prototype is a research and decision-support system. It is not a certified maritime navigation system and does not replace qualified human judgment, official navigation products, or maritime safety procedures."]
    }


@app.post("/api/navigation/routes")
@app.post("/api/navigation/optimize")
def optimize_navigation(payload: dict = Body(...)):
    """Generate FASTEST / BALANCED / SAFEST ocean-safe route candidates.

    Routing remains deterministic and explainable. Candidate cells must be
    identified as navigable ocean/sea-ice by the real CMEMS/NSIDC surface mask;
    iceberg costs are time-matched to supplied forecast trajectories, and NSIDC
    sea-ice concentration is used as a soft route penalty. No straight-line
    fallback through land is returned.
    """
    origin = payload.get("origin") or {}
    destination = payload.get("destination") or {}
    icebergs = payload.get("icebergs") or []
    try:
        speed_kmh = float(payload.get("speed_kmh", 20.0))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "speed_kmh must be a numeric vessel speed."})
    if not math.isfinite(speed_kmh) or not (1.0 <= speed_kmh <= 70.0):
        return JSONResponse(status_code=400, content={"error": "speed_kmh must be between 1 and 70 km/h; the value is not silently clamped."})
    try:
        safety = float(payload.get("safety_threshold_km", 25.0))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "safety_threshold_km must be numeric."})
    if not math.isfinite(safety) or not (5.0 <= safety <= 150.0):
        return JSONResponse(status_code=400, content={"error": "safety_threshold_km must be between 5 and 150 km."})
    vessel_type = str(payload.get("vessel_type") or "Unspecified vessel").strip() or "Unspecified vessel"

    try:
        start = {"lat": float(origin["lat"]), "lon": float(origin["lon"])}
        end = {"lat": float(destination["lat"]), "lon": float(destination["lon"])}
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Valid origin and destination coordinates are required."})

    for label, point in (("origin", start), ("destination", end)):
        if not (-90.0 <= point["lat"] <= -45.0):
            return JSONResponse(status_code=400, content={"error": f"{label} must be within the Antarctic/Southern Ocean operational area (90°S to 45°S)."})
        if not (-180.0 <= point["lon"] <= 180.0):
            return JSONResponse(status_code=400, content={"error": f"{label} longitude must be between -180 and 180 degrees. Latitude/longitude are not auto-swapped."})

    departure_raw = payload.get("departure_utc")
    if departure_raw:
        try:
            start_time = datetime.fromisoformat(str(departure_raw).replace("Z", "+00:00"))
            if start_time.tzinfo is not None:
                start_time = start_time.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return JSONResponse(status_code=400, content={"error": "departure_utc must be a valid ISO-8601 timestamp."})
    else:
        start_time = datetime.utcnow()

    if not ocean_surface.available:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Real ocean/land navigation surface is unavailable. Route generation is disabled rather than returning an unverified straight line.",
                "required_data": ["CMEMS surface-current NetCDF", "NSIDC Antarctic sea-ice GeoTIFF"],
            },
        )

    hazards = extract_hazard_points(icebergs)
    verified_forecast_count = sum(1 for item in icebergs if isinstance(item, dict) and (item.get("trajectory") or []))
    analyzer = SpatiotemporalHazardAnalyzer(safety_threshold_km=safety)
    candidates = []

    for profile in ("FASTEST", "BALANCED", "SAFEST"):
        router = PolarAStarRouter(max_nodes=int(payload.get("grid_nodes") or 56), surface=ocean_surface)
        try:
            route = router.route(start, end, hazards, safety, profile, speed_kmh=speed_kmh)
        except ValueError as exc:
            # One profile may fail even if another profile has a feasible path.
            candidates.append({
                "profile": profile,
                "available": False,
                "error": str(exc),
                "route": [],
            })
            continue

        vessel_path = VesselSimulator(speed_kmh=speed_kmh).interpolate_route(route, start_time)
        assessment = analyzer.analyze_hazards(vessel_path, icebergs)
        distance = route_distance_km(route)
        eta_h = distance / speed_kmh
        route_ice = []
        missing_ice_samples = 0
        for pt in route:
            c = ocean_surface.sea_ice_concentration_percent(pt["lat"], pt["lon"])
            if c is not None:
                route_ice.append(float(c))
            else:
                missing_ice_samples += 1
        if missing_ice_samples:
            candidates.append({
                "profile": profile,
                "available": False,
                "error": "Required NSIDC sea-ice concentration is unavailable at one or more route samples; the route is not verified.",
                "route": [],
                "missing_sea_ice_samples": missing_ice_samples,
            })
            continue
        avg_ice = round(sum(route_ice) / len(route_ice), 1) if route_ice else None
        max_ice = round(max(route_ice), 1) if route_ice else None

        hazards_found = assessment.get("hazards") or []
        min_clearance = assessment.get("min_effective_clearance_km")
        if verified_forecast_count:
            route_risk = assessment.get("overall_risk")
            rscore = risk_score(route_risk, min_clearance, len(hazards_found), safety)
            # Sea ice is genuine NSIDC input and therefore contributes transparently
            # to the displayed decision score. It does not silently rewrite the
            # hazard analyzer's iceberg risk label.
            if max_ice is not None:
                rscore = min(100, int(round(rscore + max(0.0, max_ice - 50.0) * 0.18)))
        else:
            route_risk = "INSUFFICIENT_VERIFIED_DATA"
            rscore = None

        why = []
        if not verified_forecast_count:
            why.append("No verified iceberg trajectory forecast was supplied for this calculation; iceberg risk is therefore reported as INSUFFICIENT VERIFIED DATA rather than LOW.")
        elif hazards_found:
            closest_h = min(hazards_found, key=lambda h: float(h.get("closest_approach_distance_km", 1e9)))
            why.append(
                f"Iceberg {closest_h.get('iceberg_id', 'UNKNOWN')} is forecast to approach within "
                f"{closest_h.get('closest_approach_distance_km')} km effective clearance near "
                f"{closest_h.get('closest_approach_time', 'the vessel ETA window')}."
            )
        else:
            why.append(f"No supplied iceberg forecast enters the configured {safety:.0f} km safety envelope on this route.")
        if max_ice is not None:
            why.append(f"NSIDC sea-ice concentration reaches {max_ice:.1f}% along sampled route points (average {avg_ice:.1f}%).")
        else:
            why.append("NSIDC sea-ice concentration is unavailable for the sampled route points; no value is assumed.")
        if min_clearance is not None:
            why.append(f"Minimum effective iceberg clearance is {float(min_clearance):.1f} km after forecast uncertainty is included.")
        why.append("Every route segment was checked against the real CMEMS/NSIDC ocean surface; land/no-data cells were excluded.")

        candidates.append({
            "profile": profile,
            "available": True,
            "route": route,
            "distance_km": round(distance, 2),
            "eta_hours": round(eta_h, 2),
            "arrival_utc": (start_time + timedelta(hours=eta_h)).replace(microsecond=0).isoformat() + "Z",
            "initial_bearing_deg": round(initial_bearing_deg(start["lat"], start["lon"], end["lat"], end["lon"]), 1),
            "risk": route_risk,
            "risk_score": rscore,
            "min_clearance_km": min_clearance,
            "minimum_cpa_km": assessment.get("minimum_cpa_km"),
            "tca_utc": assessment.get("tca_utc"),
            "closest_iceberg_id": assessment.get("closest_iceberg_id"),
            "clearance_series": assessment.get("clearance_series", []),
            "hazards": hazards_found,
            "sea_ice": {
                "source": "NSIDC/NOAA G02135",
                "sample_count": len(route_ice),
                "average_concentration_percent": avg_ice,
                "maximum_concentration_percent": max_ice,
            },
            "explainability": {
                "why": why,
                "hazard_count": len(hazards_found),
                "safety_buffer_km": safety,
                "sea_ice_max_percent": max_ice,
                "land_avoidance": True,
            },
            "waypoint_count": len(route),
            "fallback_direct": False,
            "route_geometry": "OCEAN_MASKED_POLAR_ASTAR_GEODESIC",
            "hazard_timing": "TIME_MATCHED_TO_VESSEL_ETA",
            "surface_checks": {
                "samples": router.last_surface_samples,
                "blocked": router.last_surface_blocked,
            },
        })

    available = [c for c in candidates if c.get("available")]
    if not available:
        return JSONResponse(
            status_code=422,
            content={
                "error": "No ocean-safe candidate route could be generated for these coordinates with the loaded real datasets.",
                "routes": candidates,
                "surface_sources": ocean_surface.sources,
            },
        )

    fastest_distance = min(c["distance_km"] for c in available)
    for c in available:
        c["extra_distance_km"] = round(c["distance_km"] - fastest_distance, 2)
        detour_pct = max(0.0, (c["distance_km"] - fastest_distance) / max(fastest_distance, 1.0) * 100.0)
        clearance = c.get("min_clearance_km")
        clearance_bonus = 0.0 if clearance is None else min(15.0, max(0.0, float(clearance)) / max(safety * 6.0, 1.0) * 15.0)
        ice_penalty = 0.0
        max_ice = c.get("sea_ice", {}).get("maximum_concentration_percent")
        if max_ice is not None:
            ice_penalty = max(0.0, float(max_ice) - 35.0) * 0.12
        risk_component = float(c["risk_score"]) * 0.70 if c.get("risk_score") is not None else 0.0
        c["decision_score"] = round(risk_component + min(30.0, detour_pct * 0.50) - clearance_bonus + ice_penalty, 2)

    rank = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
    if verified_forecast_count:
        best_rank = min(rank.get(str(c.get("risk")).upper(), 9) for c in available)
        tier = [c for c in available if rank.get(str(c.get("risk")).upper(), 9) == best_rank]
        recommended = min(tier, key=lambda c: c["decision_score"])
        recommended_profile = recommended["profile"]
        explanation = (
            f"{recommended['profile'].title()} is the lower-risk recommendation under the supplied verified forecast set: "
            f"risk score {recommended['risk_score']}/100, distance {recommended['distance_km']} km, and minimum effective iceberg clearance "
            f"{recommended['min_clearance_km'] if recommended['min_clearance_km'] is not None else 'not constrained'} km. "
            "All geometry was generated through verified CMEMS/NSIDC navigation cells."
        )
        recommended_why = recommended.get("explainability", {}).get("why", [])
    else:
        recommended = min(available, key=lambda c: c["distance_km"])
        recommended_profile = None
        explanation = (
            "Route geometry is available from the verified CMEMS/NSIDC surface, but no verified iceberg trajectory forecast was supplied. "
            "NAV-X therefore does not issue a risk-based route recommendation; iceberg risk is INSUFFICIENT VERIFIED DATA."
        )
        recommended_why = recommended.get("explainability", {}).get("why", [])

    return {
        "routes": candidates,
        "recommended_profile": recommended_profile,
        "explanation": explanation,
        "recommended_why": recommended_why,
        "verified_iceberg_forecast_count": verified_forecast_count,
        # Keep the established field value for API/backward compatibility.
        "routing_method": "TIME_AWARE_POLAR_ASTAR_GEODESIC_WITH_P90_ICEBERG_ENVELOPES",
        "routing_method_v2": "OCEAN_MASKED_TIME_AWARE_POLAR_ASTAR_WITH_P90_ICEBERG_AND_NSIDC_SEA_ICE_COSTS",
        "vessel_type": vessel_type,
        "departure_utc": start_time.replace(microsecond=0).isoformat() + "Z",
        "safety_threshold_km": safety,
        "hazard_points_used": len(hazards),
        "profile_definitions": {
            "FASTEST": "Prioritizes travel efficiency while respecting hard navigability and hazard constraints.",
            "BALANCED": "Balances travel efficiency with predicted iceberg and sea-ice exposure.",
            "SAFEST": "Strongly penalizes predicted hazard exposure and increases model safety margins; this means safest available under the current model, not guaranteed safe.",
        },
        "comparison_metrics": [
            {
                "profile": c.get("profile"),
                "available": bool(c.get("available")),
                "distance_km": c.get("distance_km"),
                "eta_hours": c.get("eta_hours"),
                "risk_score": c.get("risk_score"),
                "minimum_cpa_km": c.get("minimum_cpa_km"),
                "min_effective_clearance_km": c.get("min_clearance_km"),
                "initial_bearing_deg": c.get("initial_bearing_deg"),
                "arrival_utc": c.get("arrival_utc"),
                "hazard_count": len(c.get("hazards") or []),
                "sea_ice_max_percent": (c.get("sea_ice") or {}).get("maximum_concentration_percent"),
                "error": c.get("error"),
            }
            for c in candidates
        ],
        "route_precision": {
            "geometry": "great-circle segment interpolation between ocean-safe A* cells",
            "land_avoidance": "CMEMS finite-ocean mask with NSIDC fallback; unknown/non-ocean cells rejected",
            "sea_ice_cost": "genuine NSIDC G02135 concentration used as a soft profile-dependent penalty",
            "hazard_cost": "time matched to vessel ETA at each planning cell",
            "iceberg_buffer": "forecast P90 uncertainty plus operator safety threshold",
            "grid_nodes_requested": int(payload.get("grid_nodes") or 56),
            "operational_area": "south of 45°S",
            "surface_sources": ocean_surface.sources,
        },
        "warning": "Decision-support routing only. Not certified for autonomous or safety-critical marine navigation.",
    }


@app.get("/api/ai/status")
def ai_status():
    return {
        "status": "ACTIVE" if iceberg_ml.runtime_enabled else "DEGRADED",
        "iceberg_drift": iceberg_ml.public_status(),
        "ais_anomaly": ais_ml.public_status(),
        "decision_layer": {
            "status": "ACTIVE",
            "type": "Structured explainable route decision support",
            "generative_llm": False,
            "chat_interface": False,
            "integrity": "Produces only structured recommendations and evidence from current NAV-X route/model context; missing evidence remains unavailable.",
        },
        "risk_engine": {
            "status": "ACTIVE",
            "type": "Explainable spatiotemporal hazard + CPA/TCA decision engine",
            "ml_claim": "No supervised risk ML is claimed until verified outcome labels exist.",
        },
    }


@app.get("/api/ai/vessel-anomalies")
def ai_vessel_anomalies():
    snapshot = ais_tracker.snapshot(max_age_minutes=360, limit=500) if hasattr(ais_tracker, "snapshot") else {"vessels": []}
    vessels = snapshot.get("vessels", []) if isinstance(snapshot, dict) else []
    return {
        "model": ais_ml.public_status(),
        "count": len(vessels),
        "results": ais_ml.score_many(vessels),
        "note": "Anomaly means statistically unusual movement features, not dangerous intent.",
    }


@app.post("/api/ai/decision-support")
def ai_decision_support(payload: dict = Body(...)):
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    status = {"iceberg_drift": iceberg_ml.public_status(), "ais_anomaly": ais_ml.public_status()}
    return build_decision_report(context, status)


@app.get("/api/model/evaluation")
def model_evaluation():
    return _verified_forecast_metrics()


@app.get("/api/model/calibration")
def model_calibration():
    metrics = _verified_forecast_metrics()
    n = int(metrics.get("verified_samples") or 0)
    return {
        "enabled": n >= 10,
        "verified_samples": n,
        "minimum_samples_required": 10,
        "status": "CALIBRATION_ELIGIBLE" if n >= 10 else "LEARNING_DATA_INSUFFICIENT",
        "note": "Automatic correction remains disabled until at least 10 independently verified forecast outcomes exist. NAV-X will not fabricate calibration confidence.",
        "current_adjustment": "NONE" if n < 10 else "ELIGIBLE_FOR_BOUNDED_RETRAINING_REVIEW",
    }


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Serve static frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/app", StaticFiles(directory=static_dir, html=True), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/system/provenance")
def get_provenance():
    """
    Returns full data provenance and scientific model status.
    Strictly distinguishes REAL LOCAL/CACHED data from UNAVAILABLE live streams.
    """
    import glob

    cmems_candidates = glob.glob(os.path.join(RAW_DIR, "ocean_current_live_*.nc")) + glob.glob(os.path.join(RAW_DIR, "ocean*.nc"))
    era5_candidates = glob.glob(os.path.join(PROCESSED_DIR, "era5_*_processed.nc")) + glob.glob(os.path.join(RAW_DIR, "era5_*.nc"))
    nsidc_candidates = glob.glob(os.path.join(RAW_DIR, "S_*_concentration_v4.0.tif"))
    cmems_file = max(cmems_candidates, key=os.path.getmtime) if cmems_candidates else None
    era5_file = max(era5_candidates, key=os.path.getmtime) if era5_candidates else None
    nsidc_file = max(nsidc_candidates, key=os.path.getmtime) if nsidc_candidates else None
    usnic_payload = usnic_live.load_best()
    usnic_features = usnic_payload.get("features", [])
    usnic_dates = [f.get("properties", {}).get("date_observed") for f in usnic_features]
    usnic_dates = [d for d in usnic_dates if d]

    return {
        "system_name": "ANTARCTIC NAV-X",
        "system_status": "ONLINE",
        "data_mode": "REAL OBSERVATIONS + CACHED/REFRESHABLE SCIENTIFIC DATA; NO SYNTHETIC SOURCE RECORDS",
        "database": database_status(),
        "automatic_ingestion": ingestion_scheduler.public_status(),
        "sources": {
            "cmems": {
                "provider": "Mercator Ocean / Copernicus Marine Service (CMEMS)",
                "product_id": "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
                "status": "REFRESHABLE + LOCAL CACHE" if cmems_file else "DATA UNAVAILABLE",
                "file": os.path.basename(cmems_file) if cmems_file else None,
                "live_status": "AUTH CONFIGURED" if cmems_credentials_configured() else "AUTH NOT CONFIGURED",
                "variables": ["uo (ocean_u)", "vo (ocean_v)"],
                "spatial_coverage": "Antarctic waters (-80°S to -50°S, -180° to +180°)",
                "temporal_coverage": "Read from the current cached/downloaded NetCDF at runtime"
            },
            "era5": {
                "provider": "ECMWF / Copernicus Climate Change Service (ERA5)",
                "product_id": "reanalysis-era5-single-levels",
                "status": "REFRESHABLE + LOCAL CACHE" if era5_file else "DATA UNAVAILABLE",
                "file": os.path.basename(era5_file) if era5_file else None,
                "live_status": "AUTH CONFIGURED" if cds_credentials_configured() else "AUTH NOT CONFIGURED",
                "variables": ["u10 (10m eastward wind)", "v10 (10m northward wind)", "t2m (temperature)", "msl (pressure)"],
                "spatial_coverage": "Antarctic circle (-90°S to -50°S, -180° to +180°)",
                "temporal_coverage": "Read from the current cached/downloaded ERA5 file at runtime"
            },
            "nsidc": {
                "provider": "National Snow and Ice Data Center (NSIDC)",
                "product_id": "NSIDC-G02135 (Climate Data Record of Daily Sea Ice Concentration)",
                "status": "AUTO-REFRESHABLE HTTPS + LOCAL CACHE" if nsidc_file else "DATA UNAVAILABLE",
                "file": os.path.basename(nsidc_file) if nsidc_file else None,
                "date": (os.path.basename(nsidc_file)[2:10] if nsidc_file else None),
                "variables": ["sea_ice_concentration"]
            },
            "usnic": {
                "provider": "U.S. National Ice Center (USNIC)",
                "product_id": "Antarctic Iceberg Tracking Database",
                "status": (usnic_payload.get("metadata") or {}).get("mode", "CACHED_OR_UNAVAILABLE"),
                "file": "data/live/usnic_current.csv" if (Path(LIVE_DIR) / "usnic_current.csv").exists() else None,
                "observation_date": max(usnic_dates) if usnic_dates else None,
                "verified_iceberg_count": len(usnic_features),
                "variables": ["id", "lat", "lon", "length_nm", "width_nm", "date_observed", "source"]
            },
            "usnic_sea_ice_extent": {
                "provider": "U.S. National Ice Center (USNIC)",
                "product_id": "Antarctic Daily Ice Extents / 10-Year Climatology",
                "status": "LOCAL / CACHED OFFICIAL RECORDS",
                "files": [
                    "usnic_extent/ANTARC_2024_daily_ice_extents.txt",
                    "usnic_extent/ANTARC_2025_daily_ice_extents.txt",
                    "usnic_extent/ANTARC_2026_daily_ice_extents.txt",
                    "usnic_extent/10yrclimo.csv"
                ],
                "use": "Seasonal extent/climatology visualization and operational sea-ice context"
            },
            "operator_map": {
                "provider": "OpenFreeMap / OpenStreetMap with MapLibre GL JS",
                "status": "KEYLESS_BASEMAP_CONFIGURED",
                "mode": "KEYLESS_WITH_FALLBACK",
                "role": "Operator-facing Antarctic/Southern Ocean basemap. OpenFreeMap vector tiles are preferred and OpenStreetMap raster tiles provide an automatic fallback; no map API credential is required or exposed.",
                "data_basis": "OpenStreetMap geographic data; scientific navigation overlays remain NAV-X backend outputs from USNIC/CMEMS/NSIDC/ERA5/AIS.",
                "mappls_preserved": bool((os.getenv("MAPPLS_STATIC_KEY") or "").strip()),
                "mappls_note": "Legacy Mappls configuration is preserved as optional deployment metadata but is not required by the current keyless operator basemap."
            }
        },
        "models": {
            "physics_trajectory": {
                "name": "Physics-Informed Kinematic Model",
                "status": "ACTIVE BASELINE",
                "equation": "ice_u = alpha * ocean_u + beta * wind_u + assimilated_residual + gated_ml_residual ; ice_v = alpha * ocean_v + beta * wind_v + assimilated_residual + gated_ml_residual",
                "parameters": {"alpha_ocean": 1.0, "beta_wind": 0.018},
                "parameter_note": "Configurable research-model parameters, NOT universal physical constants",
                "horizons_hours": [6, 12, 24, 48, 72],
                "uncertainty": "P90 perturbation-ensemble sensitivity spread including coordinate/timing/forcing uncertainty; not a certified probability bound."
            },
            "iceberg_residual_ml": iceberg_ml.public_status(),
            "ais_anomaly_ml": ais_ml.public_status(),
            "structured_ai_decision_layer": {
                "status": "ACTIVE",
                "type": "Structured explainable route decision support",
                "generative_llm": False,
                "chat_interface": False,
                "integrity": "Recommendations and rationale are derived only from current NAV-X route/model context."
            },
            "risk_engine": {
                "name": "Spatiotemporal Hazard Analyzer & Navigation Risk Engine",
                "status": "ACTIVE",
                "thresholds_km": {"CRITICAL": "<= 10.0", "HIGH": "<= 25.0", "MODERATE": "<= 50.0", "LOW": "> 50.0"},
                "recommendations": "DECISION SUPPORT FOR FURTHER OPERATOR REVIEW (Not autonomous navigation)"
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
