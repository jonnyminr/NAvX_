"""Copernicus Data Space Sentinel-1 catalogue client.

This provider fetches authenticated, real Sentinel-1 GRD scene metadata only.
It does not claim that a SAR product has been downloaded or analysed until a
separate product-processing workflow actually does so.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CATALOG_URL = "https://sh.dataspace.copernicus.eu/catalog/v1/search"
COLLECTION = "sentinel-1-grd"

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def credentials_configured() -> bool:
    return bool((os.getenv("SENTINEL_CLIENT_ID") or "").strip() and (os.getenv("SENTINEL_CLIENT_SECRET") or "").strip())


def _access_token() -> str:
    now = time.time()
    cached = _token_cache.get("access_token")
    if cached and now < float(_token_cache.get("expires_at") or 0) - 60:
        return str(cached)

    client_id = (os.getenv("SENTINEL_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("SENTINEL_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Sentinel-1 OAuth client credentials are not configured")

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()

    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Copernicus Data Space token response did not contain access_token")
    expires_in = int(payload.get("expires_in") or 3600)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + max(60, expires_in)
    return str(token)


def fetch_recent_sentinel1(hours: int = 24, limit_per_half: int = 50) -> dict:
    token = _access_token()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(1, int(hours)))
    interval = f"{start.isoformat().replace('+00:00', 'Z')}/{end.isoformat().replace('+00:00', 'Z')}"
    # Split the Antarctic longitude range at 0° to avoid relying on a 360°-wide
    # bbox interpretation in downstream STAC implementations.
    bboxes = [[-180.0, -90.0, 0.0, -55.0], [0.0, -90.0, 180.0, -55.0]]
    features: dict[str, dict] = {}
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=45.0, follow_redirects=True, headers=headers) as client:
        for bbox in bboxes:
            response = client.post(
                CATALOG_URL,
                json={
                    "bbox": bbox,
                    "datetime": interval,
                    "collections": [COLLECTION],
                    "limit": max(1, min(int(limit_per_half), 100)),
                },
            )
            response.raise_for_status()
            payload = response.json()
            for feature in payload.get("features", []):
                scene_id = str(feature.get("id") or "").strip()
                if scene_id:
                    features[scene_id] = feature

    return {
        "ok": True,
        "provider": "Copernicus Data Space Ecosystem / Sentinel Hub Catalog",
        "collection": COLLECTION,
        "search_start": start.isoformat(),
        "search_end": end.isoformat(),
        "count": len(features),
        "features": list(features.values()),
        "catalogue_url": CATALOG_URL,
        "data_semantics": "CATALOGUE_METADATA_ONLY",
    }
