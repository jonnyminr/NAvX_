"""Live/fresh operational data providers used by ANTARCTIC NAV-X.

Two sources are intentionally treated differently:

* USNIC Antarctic iceberg positions are *official observations*, published on a
  weekly cadence.  The provider refreshes the current CSV whenever possible and
  falls back to the bundled official snapshot when offline.  It never invents
  additional iceberg positions.
* AISStream is an event-driven WebSocket feed of AIS vessel messages.  The API
  key stays on the FastAPI backend and only a small, sanitized live vessel
  snapshot is exposed to the browser.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

USNIC_CURRENT_CSV = "https://usicecenter.gov/File/DownloadCurrent?pId=134"
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")




def _safe_provider_error(value: Any, *secrets: str) -> str:
    """Return a browser-safe provider error without credentials or key/token query values."""
    text = str(value or "Provider request failed.")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(api[_-]?key|token|username)=([^&\s]+)", r"\1=[REDACTED]", text)
    return text[:400]

def _parse_usnic_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _iceberg_feature(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    iceberg_id = str(row.get("Iceberg") or row.get("id") or "").strip()
    lat = _float_or_none(row.get("Latitude", row.get("lat")))
    lon = _float_or_none(row.get("Longitude", row.get("lon")))
    if not iceberg_id or lat is None or lon is None:
        return None
    if not (-90 <= lat <= -40 and -180 <= lon <= 180):
        return None

    observed = str(row.get("Last Update") or row.get("date_observed") or "").strip() or None
    observed_dt = _parse_usnic_date(observed)
    age_hours = None
    if observed_dt:
        age_hours = max(0.0, (datetime.now(timezone.utc) - observed_dt).total_seconds() / 3600.0)

    length_nm = _float_or_none(row.get("Length (NM)", row.get("length_nm")))
    width_nm = _float_or_none(row.get("Width (NM)", row.get("width_nm")))
    area_sqnm = _float_or_none(row.get("Area (sqNM)", row.get("area_sqnm")))
    area_sqkm = _float_or_none(row.get("Area (sqKM)", row.get("area_sqkm")))
    if area_sqnm is None and length_nm is not None and width_nm is not None:
        # Only a UI estimate when the source does not provide an area field.
        # Keep it explicitly separate from official values.
        area_sqnm_est = length_nm * width_nm
    else:
        area_sqnm_est = None

    props = {
        "id": iceberg_id,
        "length_nm": length_nm,
        "width_nm": width_nm,
        "area_sqnm": area_sqnm,
        "area_sqkm": area_sqkm,
        "area_sqnm_estimate": area_sqnm_est,
        "lat": lat,
        "lon": lon,
        "source_lat_text": str(row.get("Latitude", row.get("lat", lat))).strip(),
        "source_lon_text": str(row.get("Longitude", row.get("lon", lon))).strip(),
        "coordinate_precision": "As published in the official USNIC source table; no additional precision is inferred.",
        "date_observed": observed,
        "observation_age_hours": round(age_hours, 1) if age_hours is not None else None,
        "source": "USNIC",
        "position_type": "OFFICIAL_OBSERVATION",
        "position_note": "USNIC tracked position; observation cadence is weekly, not continuous real-time GPS.",
    }
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def parse_usnic_csv(raw: bytes) -> Dict[str, Any]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    features: List[Dict[str, Any]] = []
    seen = set()
    for row in reader:
        feat = _iceberg_feature(row)
        if not feat:
            continue
        iid = feat["properties"]["id"]
        if iid in seen:
            continue
        seen.add(iid)
        features.append(feat)
    if not features:
        raise ValueError("USNIC CSV contained no valid Antarctic iceberg positions")
    features.sort(key=lambda f: f["properties"]["id"])
    newest = max(
        (f["properties"].get("date_observed") or "" for f in features),
        default="",
    )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "provider": "U.S. National Ice Center (USNIC)",
            "source_url": USNIC_CURRENT_CSV,
            "retrieved_at": _utc_now_iso(),
            "latest_observation_label": newest or None,
        },
    }


class USNICLiveCache:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self.live_dir = self.data_root / "live"
        self.live_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.live_dir / "usnic_current.geojson"
        self.raw_cache_file = self.live_dir / "usnic_current.csv"
        self.last_attempt = 0.0
        self.last_error: Optional[str] = None
        self.last_success: Optional[str] = None

    def _bundled_geojson(self) -> Path:
        return self.data_root / "processed" / "icebergs.geojson"

    def _bundled_csv_candidates(self) -> List[Path]:
        return sorted((self.data_root / "raw").glob("usnic_icebergs_*.csv"), reverse=True)

    def load_best(self) -> Dict[str, Any]:
        if self.cache_file.exists():
            try:
                payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if payload.get("features"):
                    return payload
            except Exception:
                pass

        candidates = self._bundled_csv_candidates()
        if candidates:
            try:
                payload = parse_usnic_csv(candidates[0].read_bytes())
                payload.setdefault("metadata", {})["mode"] = "BUNDLED_OFFICIAL_SNAPSHOT"
                return payload
            except Exception:
                pass

        # Compatibility with older processed GeoJSON: use properties lat/lon rather
        # than its projected geometry, then normalize to WGS84 geometry.
        geo = self._bundled_geojson()
        if geo.exists():
            raw = json.loads(geo.read_text(encoding="utf-8"))
            features = []
            for old in raw.get("features", []):
                p = old.get("properties", {})
                row = {
                    "id": p.get("id"), "lat": p.get("lat"), "lon": p.get("lon"),
                    "length_nm": p.get("length_nm"), "width_nm": p.get("width_nm"),
                    "date_observed": p.get("date_observed"),
                }
                feat = _iceberg_feature(row)
                if feat:
                    features.append(feat)
            return {"type": "FeatureCollection", "features": features, "metadata": {"mode": "BUNDLED_OFFICIAL_SNAPSHOT"}}
        return {"type": "FeatureCollection", "features": [], "metadata": {"mode": "MISSING"}}

    def refresh(self, force: bool = False, min_interval_seconds: int = 900) -> Dict[str, Any]:
        now = time.time()
        if not force and now - self.last_attempt < min_interval_seconds:
            return self.load_best()
        self.last_attempt = now
        try:
            headers = {"User-Agent": "ANTARCTIC-NAV-X/3.0 (+educational decision-support prototype)"}
            with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
                response = client.get(USNIC_CURRENT_CSV)
                response.raise_for_status()
                raw = response.content
            payload = parse_usnic_csv(raw)
            payload["metadata"]["mode"] = "FRESH_OFFICIAL_DOWNLOAD"
            self.raw_cache_file.write_bytes(raw)
            # Preserve dated official snapshots so the trajectory model can
            # estimate recent observed motion on later refreshes.  The archive
            # contains only original USNIC CSV bytes; no synthetic positions.
            try:
                dates = []
                for feat in payload.get("features", []):
                    d = _parse_usnic_date(feat.get("properties", {}).get("date_observed"))
                    if d:
                        dates.append(d)
                stamp = max(dates).strftime("%Y%m%d") if dates else datetime.now(timezone.utc).strftime("%Y%m%d")
                archive = self.data_root / "raw" / f"usnic_icebergs_{stamp}.csv"
                archive.parent.mkdir(parents=True, exist_ok=True)
                if not archive.exists():
                    archive.write_bytes(raw)
            except Exception:
                pass
            self.cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.last_success = payload["metadata"].get("retrieved_at")
            self.last_error = None
            return payload
        except Exception as exc:
            self.last_error = str(exc)
            payload = self.load_best()
            payload.setdefault("metadata", {})["refresh_error"] = self.last_error
            payload["metadata"]["mode"] = payload["metadata"].get("mode", "CACHED_FALLBACK")
            return payload


@dataclass
class VesselState:
    mmsi: str
    name: str
    lat: float
    lon: float
    sog_knots: Optional[float]
    cog_deg: Optional[float]
    heading_deg: Optional[float]
    position_accuracy: Optional[bool]
    message_type: str
    last_seen_utc: str
    last_seen_epoch: float
    imo: Optional[str] = None
    call_sign: Optional[str] = None
    destination: Optional[str] = None
    ship_type: Optional[str] = None
    nav_status: Optional[int] = None
    rate_of_turn: Optional[float] = None
    raim: Optional[bool] = None
    zone: str = "ANTARCTIC"

    def public(self) -> Dict[str, Any]:
        d = asdict(self)
        age = max(0.0, time.time() - self.last_seen_epoch)
        if age <= 120:
            freshness = "LIVE"
        elif age <= 900:
            freshness = "RECENT"
        else:
            freshness = "STALE"
        d["received_age_seconds"] = round(age, 1)
        d["freshness"] = freshness
        d["data_quality"] = (
            "AIS_POSITION_ACCURACY_FLAG_TRUE" if self.position_accuracy is True else
            "AIS_POSITION_ACCURACY_FLAG_FALSE" if self.position_accuracy is False else
            "POSITION_ACCURACY_NOT_REPORTED"
        )
        d.pop("last_seen_epoch", None)
        return d


class AISStreamTracker:
    """Server-side AISStream client for real vessel positions in the Southern Ocean.

    The stream is authoritative for what AISStream actually receives. NAV-X never
    fabricates vessel positions. A small rolling trail/cache is kept so sparse
    Antarctic reception remains understandable between messages and across local
    app restarts. Every cached point retains its real receive timestamp.
    """

    def __init__(self, api_key: str | None, data_root: Path | None = None):
        from collections import deque
        self.api_key = (api_key or "").strip()
        self.vessels: Dict[str, VesselState] = {}
        self.trails: Dict[str, Any] = {}
        self.static_meta: Dict[str, Dict[str, Any]] = {}
        self.status = "DISABLED" if not self.api_key else "STARTING"
        self.last_error: Optional[str] = None
        self.connected_since: Optional[str] = None
        self.last_message_at: Optional[str] = None
        self.messages_received = 0
        self.position_messages_received = 0
        self._stop = asyncio.Event()
        self._deque = deque
        self.min_lat = float(os.getenv("AIS_MIN_LAT", "-45"))
        self.max_age_cache_seconds = int(os.getenv("AIS_CACHE_HOURS", "6")) * 3600
        self.data_root = Path(data_root) if data_root else None
        self.cache_file = None
        self._last_cache_write = 0.0
        if self.data_root:
            live_dir = self.data_root / "live"
            live_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file = live_dir / "ais_recent.json"
            self._load_cache()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _zone_for_lat(self, lat: float) -> str:
        return "ANTARCTIC" if lat <= -60.0 else "SOUTHERN_OCEAN_APPROACH"

    def _prune(self, max_age_seconds: int = 21600) -> None:
        cutoff = time.time() - max_age_seconds
        stale = [m for m, v in self.vessels.items() if v.last_seen_epoch < cutoff]
        for m in stale:
            self.vessels.pop(m, None)
            self.trails.pop(m, None)
            self.static_meta.pop(m, None)

    def _load_cache(self) -> None:
        if not self.cache_file or not self.cache_file.exists():
            return
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            now = time.time()
            for item in raw.get("vessels", []):
                epoch = float(item.get("last_seen_epoch") or 0)
                if epoch <= 0 or now - epoch > self.max_age_cache_seconds:
                    continue
                allowed = {f.name for f in VesselState.__dataclass_fields__.values()}
                state_data = {k: v for k, v in item.items() if k in allowed}
                state = VesselState(**state_data)
                self.vessels[state.mmsi] = state
            for mmsi, points in (raw.get("trails") or {}).items():
                cleaned = []
                for pt in points[-40:]:
                    if isinstance(pt, dict) and all(k in pt for k in ("lat", "lon", "t")):
                        cleaned.append(pt)
                if cleaned:
                    self.trails[str(mmsi)] = self._deque(cleaned, maxlen=40)
        except Exception:
            # Cache is only a convenience; a malformed cache must never block startup.
            pass

    def _save_cache(self, force: bool = False) -> None:
        if not self.cache_file:
            return
        now = time.time()
        if not force and now - self._last_cache_write < 30:
            return
        self._last_cache_write = now
        try:
            payload = {
                "saved_at": _utc_now_iso(),
                "vessels": [asdict(v) for v in self.vessels.values()],
                "trails": {m: list(points) for m, points in self.trails.items()},
            }
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.cache_file)
        except Exception:
            pass

    def snapshot(self, max_age_minutes: int = 180, limit: int = 500, **_: Any) -> Dict[str, Any]:
        max_age_minutes = max(1, min(int(max_age_minutes), 360))
        self._prune(max_age_seconds=max(60, max_age_minutes * 60))
        cutoff = time.time() - max_age_minutes * 60
        items = [v for v in self.vessels.values() if v.last_seen_epoch >= cutoff]
        items.sort(key=lambda v: v.last_seen_epoch, reverse=True)
        items = items[: max(1, min(int(limit), 1000))]
        public_items = []
        for v in items:
            d = v.public()
            d["source"] = "AISStream.io"
            points = list(self.trails.get(v.mmsi, []))
            d["trail"] = points[-24:]
            public_items.append(d)
        live_count = sum(1 for v in public_items if v.get("freshness") == "LIVE")
        recent_count = sum(1 for v in public_items if v.get("freshness") == "RECENT")
        stale_count = sum(1 for v in public_items if v.get("freshness") == "STALE")
        return {
            "provider": "AISStream.io",
            "mode": "LIVE_AIS_WEBSOCKET" if self.enabled else "NOT_CONFIGURED",
            "enabled": self.enabled,
            "status": self.status,
            "count": len(public_items),
            "live_count": live_count,
            "recent_count": recent_count,
            "stale_count": stale_count,
            "last_error": self.last_error,
            "connected_since": self.connected_since,
            "last_message_at": self.last_message_at,
            "messages_received": self.messages_received,
            "position_messages_received": self.position_messages_received,
            "coverage": f"Southern Ocean/AIS bounding area south of {abs(self.min_lat):.0f}°S",
            "coverage_note": "Only genuine AIS messages received by AISStream are shown. Antarctic reception can be sparse; cached points keep their original receive time and are visibly marked RECENT/STALE.",
            "vessels": public_items,
            "generated_at": _utc_now_iso(),
        }

    async def run(self) -> None:
        if not self.api_key:
            return
        try:
            import websockets
        except ImportError:
            self.status = "ERROR"
            self.last_error = "Python package 'websockets' is not installed"
            return

        backoff = 2.0
        # Four non-dateline-crossing boxes cover the Southern Ocean and Antarctic
        # approaches. The northern edge is configurable (default 45°S) so real
        # approach traffic can be observed before vessels reach the continent.
        north = max(-89.0, min(-40.0, self.min_lat))
        boxes = [
            [[-90.0, -180.0], [north, -90.0]],
            [[-90.0, -90.0], [north, 0.0]],
            [[-90.0, 0.0], [north, 90.0]],
            [[-90.0, 90.0], [north, 180.0]],
        ]
        subscription = {
            "APIKey": self.api_key,
            "BoundingBoxes": boxes,
            "FilterMessageTypes": [
                "PositionReport",
                "StandardClassBPositionReport",
                "ExtendedClassBPositionReport",
                "ShipStaticData",
                "StaticDataReport",
            ],
        }

        while not self._stop.is_set():
            try:
                self.status = "CONNECTING"
                async with websockets.connect(
                    AISSTREAM_URL,
                    compression="deflate",
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2_000_000,
                ) as ws:
                    await ws.send(json.dumps(subscription))
                    self.status = "LIVE"
                    self.connected_since = _utc_now_iso()
                    self.last_error = None
                    backoff = 2.0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        self.messages_received += 1
                        self.last_message_at = _utc_now_iso()
                        self._consume(event)
            except asyncio.CancelledError:
                self.status = "STOPPED"
                self._save_cache(force=True)
                raise
            except Exception as exc:
                self.status = "RECONNECTING"
                self.last_error = _safe_provider_error(exc, self.api_key)
                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 1.8, 60.0)

    def _consume(self, event: Dict[str, Any]) -> None:
        msg_type = str(event.get("MessageType") or "")
        if msg_type == "SubscriptionConfirmation":
            self.status = "LIVE"
            return

        meta = event.get("MetaData") or {}
        mmsi_raw = meta.get("MMSI")
        if mmsi_raw is None:
            return
        mmsi = str(mmsi_raw)
        body = (event.get("Message") or {}).get(msg_type) or {}

        # Static/voyage messages enrich real position markers but do not create
        # a vessel position on their own.
        if msg_type in {"ShipStaticData", "StaticDataReport"}:
            md = self.static_meta.setdefault(mmsi, {})
            for key, candidates in {
                "name": [meta.get("ShipName"), body.get("Name")],
                "imo": [body.get("ImoNumber"), body.get("IMO")],
                "call_sign": [body.get("CallSign")],
                "destination": [body.get("Destination")],
                "ship_type": [body.get("Type"), body.get("ShipType")],
            }.items():
                val = next((v for v in candidates if v not in (None, "")), None)
                if val is not None:
                    md[key] = str(val).strip()
            if mmsi in self.vessels:
                v = self.vessels[mmsi]
                for key in ("imo", "call_sign", "destination", "ship_type"):
                    if md.get(key):
                        setattr(v, key, md[key])
                if md.get("name"):
                    v.name = md["name"]
            return

        if msg_type not in {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}:
            return

        # Prefer position fields from the typed AIS body when available and
        # fall back to normalized envelope metadata.
        lat = _float_or_none(body.get("Latitude"))
        lon = _float_or_none(body.get("Longitude"))
        if lat is None:
            lat = _float_or_none(meta.get("Latitude"))
        if lon is None:
            lon = _float_or_none(meta.get("Longitude"))
        if lat is None or lon is None or lat > self.min_lat or not (-180 <= lon <= 180):
            return

        sog = _float_or_none(body.get("Sog"))
        cog = _float_or_none(body.get("Cog"))
        heading = _float_or_none(body.get("TrueHeading"))
        if heading is not None and (heading < 0 or heading >= 360):
            heading = None
        if cog is not None and (cog < 0 or cog >= 360):
            cog = None
        if sog is not None and (sog < 0 or sog > 102.3):
            sog = None
        pos_accuracy = body.get("PositionAccuracy")
        if not isinstance(pos_accuracy, bool):
            pos_accuracy = None
        nav_status = body.get("NavigationalStatus")
        nav_status = int(nav_status) if isinstance(nav_status, (int, float)) else None
        rot = _float_or_none(body.get("RateOfTurn"))
        raim = body.get("Raim") if isinstance(body.get("Raim"), bool) else None

        static = self.static_meta.get(mmsi, {})
        name = str(meta.get("ShipName") or static.get("name") or "").strip() or ""
        now = time.time()
        state = VesselState(
            mmsi=mmsi,
            name=name,
            lat=lat,
            lon=lon,
            sog_knots=sog,
            cog_deg=cog,
            heading_deg=heading,
            position_accuracy=pos_accuracy,
            message_type=msg_type,
            last_seen_utc=_utc_now_iso(),
            last_seen_epoch=now,
            imo=static.get("imo"),
            call_sign=static.get("call_sign"),
            destination=static.get("destination"),
            ship_type=static.get("ship_type"),
            nav_status=nav_status,
            rate_of_turn=rot,
            raim=raim,
            zone=self._zone_for_lat(lat),
        )
        self.vessels[mmsi] = state
        self.position_messages_received += 1

        trail = self.trails.get(mmsi)
        if trail is None:
            trail = self._deque(maxlen=40)
            self.trails[mmsi] = trail
        if not trail or abs(trail[-1]["lat"] - lat) > 1e-5 or abs(trail[-1]["lon"] - lon) > 1e-5 or now - trail[-1]["epoch"] > 15:
            trail.append({
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "t": state.last_seen_utc,
                "epoch": now,
            })

        self._prune(max_age_seconds=self.max_age_cache_seconds)
        self._save_cache()

    def stop(self) -> None:
        self._save_cache(force=True)
        self._stop.set()

# ---------------------------------------------------------------------------
# Additional genuine AIS providers. These adapters never synthesize positions.
# ---------------------------------------------------------------------------

AISHUB_URL = "https://data.aishub.net/ws.php"
DATALASTIC_INRADIUS_URL = "https://api.datalastic.com/api/v0/vessel_inradius"


def _epoch_from_utc_text(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return 0.0
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S GMT", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _iso_from_epoch(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return _utc_now_iso()


class AISHubTracker:
    """AISHub web-service adapter using only genuine returned AIS records.

    AISHub explicitly asks clients not to request the service more often than
    once per minute. NAV-X therefore polls no faster than every 65 seconds.
    """

    def __init__(self, username: str | None):
        self.username = (username or "").strip()
        self.min_lat = float(os.getenv("AIS_MIN_LAT", "-45"))
        self.status = "DISABLED" if not self.username else "READY"
        self.last_error: Optional[str] = None
        self.last_message_at: Optional[str] = None
        self.vessels: Dict[str, VesselState] = {}
        self._stop = asyncio.Event()
        self._poll_seconds = max(65, int(os.getenv("AISHUB_POLL_SECONDS", "65")))

    @property
    def enabled(self) -> bool:
        return bool(self.username)

    def _parse_payload(self, payload: Any) -> None:
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], dict):
            raise ValueError("Unexpected AISHub JSON response structure")
        header, records = payload[0], payload[1]
        if bool(header.get("ERROR")):
            raise ValueError(str(header.get("ERROR_MESSAGE") or header.get("ERROR") or "AISHub returned an error"))
        if not isinstance(records, list):
            records = []
        fresh: Dict[str, VesselState] = {}
        for row in records:
            if not isinstance(row, dict):
                continue
            lat = _float_or_none(row.get("LATITUDE"))
            lon = _float_or_none(row.get("LONGITUDE"))
            if lat is None or lon is None or lat > self.min_lat or not (-180 <= lon <= 180):
                continue
            mmsi = str(row.get("MMSI") or "").strip()
            if not mmsi:
                continue
            epoch = _epoch_from_utc_text(row.get("TIME")) or time.time()
            heading = _float_or_none(row.get("HEADING"))
            if heading is not None and (heading < 0 or heading >= 360 or heading == 511):
                heading = None
            cog = _float_or_none(row.get("COG"))
            if cog is not None and (cog < 0 or cog >= 360):
                cog = None
            sog = _float_or_none(row.get("SOG"))
            if sog is not None and (sog < 0 or sog >= 102.4):
                sog = None
            imo = str(row.get("IMO") or "").strip() or None
            if imo == "0":
                imo = None
            nav = row.get("NAVSTAT")
            try:
                nav = int(nav) if nav is not None else None
            except Exception:
                nav = None
            fresh[mmsi] = VesselState(
                mmsi=mmsi,
                name=str(row.get("NAME") or "").strip(),
                lat=float(lat), lon=float(lon),
                sog_knots=sog, cog_deg=cog, heading_deg=heading,
                position_accuracy=None,
                message_type="AISHUB_WEB_SERVICE",
                last_seen_utc=_iso_from_epoch(epoch), last_seen_epoch=epoch,
                imo=imo,
                call_sign=str(row.get("CALLSIGN") or "").strip() or None,
                destination=str(row.get("DEST") or "").strip() or None,
                ship_type=(f"AIS type {row.get('TYPE')}" if row.get("TYPE") not in (None, "") else None),
                nav_status=nav,
                rate_of_turn=_float_or_none(row.get("ROT")),
                zone="ANTARCTIC" if lat <= -60 else "SOUTHERN_OCEAN_APPROACH",
            )
        self.vessels = fresh
        self.last_message_at = _utc_now_iso()

    def _fetch(self) -> None:
        if not self.enabled:
            return
        params = {
            "username": self.username,
            "format": 1,
            "output": "json",
            "compress": 0,
            "latmin": -90,
            "latmax": self.min_lat,
            "lonmin": -180,
            "lonmax": 180,
            "interval": max(1, int(os.getenv("AIS_MAX_POSITION_AGE_MINUTES", "180"))),
        }
        with httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": "ANTARCTIC-NAV-X/3.0"}) as client:
            response = client.get(AISHUB_URL, params=params)
            response.raise_for_status()
            self._parse_payload(response.json())
        self.status = "LIVE"
        self.last_error = None

    async def run(self) -> None:
        if not self.enabled:
            return
        while not self._stop.is_set():
            try:
                self.status = "POLLING"
                await asyncio.to_thread(self._fetch)
            except asyncio.CancelledError:
                self.status = "STOPPED"
                raise
            except Exception as exc:
                self.status = "ERROR"
                self.last_error = _safe_provider_error(exc, self.username)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass

    def snapshot(self, max_age_minutes: int = 180, limit: int = 500, **_: Any) -> Dict[str, Any]:
        cutoff = time.time() - max(1, int(max_age_minutes)) * 60
        items = [v for v in self.vessels.values() if v.last_seen_epoch >= cutoff]
        items.sort(key=lambda x: x.last_seen_epoch, reverse=True)
        items = items[:max(1, min(int(limit), 1000))]
        public = [v.public() | {"trail": [], "source": "AISHub"} for v in items]
        return {
            "provider": "AISHub",
            "mode": "LIVE_AISHUB_WEBSERVICE" if self.enabled else "NOT_CONFIGURED",
            "enabled": self.enabled,
            "status": self.status,
            "count": len(public),
            "live_count": sum(1 for v in public if v.get("freshness") == "LIVE"),
            "recent_count": sum(1 for v in public if v.get("freshness") == "RECENT"),
            "stale_count": sum(1 for v in public if v.get("freshness") == "STALE"),
            "last_error": self.last_error,
            "last_message_at": self.last_message_at,
            "coverage": f"AISHub records south of {abs(self.min_lat):.0f}°S",
            "coverage_note": "Only genuine AISHub records are shown. AISHub access is member/registration based and NAV-X respects its minimum one-minute request interval.",
            "vessels": public,
            "generated_at": _utc_now_iso(),
        }

    def stop(self) -> None:
        self._stop.set()


class DatalasticTracker:
    """On-demand Datalastic area-scan adapter.

    Datalastic's vessel_inradius endpoint accepts a maximum radius of 50 NM.
    NAV-X only calls it when a center point is supplied by the UI/API caller and
    caches identical scans briefly to avoid unnecessary paid-credit usage.
    """

    def __init__(self, api_key: str | None):
        self.api_key = (api_key or "").strip()
        self.min_lat = float(os.getenv("AIS_MIN_LAT", "-45"))
        self.status = "DISABLED" if not self.api_key else "READY"
        self.last_error: Optional[str] = None
        self.last_message_at: Optional[str] = None
        self._stop = asyncio.Event()
        self._cache_key: Optional[tuple] = None
        self._cache_time = 0.0
        self._cache_payload: Optional[Dict[str, Any]] = None
        self._cache_seconds = max(60, int(os.getenv("DATALASTIC_CACHE_SECONDS", "120")))

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def run(self) -> None:
        if not self.enabled:
            return
        self.status = "READY_ON_DEMAND"
        await self._stop.wait()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self, max_age_minutes: int = 180, limit: int = 500,
                 lat: Optional[float] = None, lon: Optional[float] = None,
                 radius_nm: float = 50.0, **_: Any) -> Dict[str, Any]:
        base = {
            "provider": "Datalastic",
            "mode": "LIVE_DATALASTIC_INRADIUS" if self.enabled else "NOT_CONFIGURED",
            "enabled": self.enabled,
            "status": self.status,
            "last_error": self.last_error,
            "last_message_at": self.last_message_at,
            "generated_at": _utc_now_iso(),
        }
        if not self.enabled:
            return base | {"count": 0, "vessels": [], "coverage_note": "Datalastic API key is not configured."}
        if lat is None or lon is None:
            return base | {
                "count": 0, "vessels": [],
                "status": "CENTER_REQUIRED",
                "coverage_note": "Datalastic scans a maximum 50-NM radius. Pan/select an Antarctic map area or route point so NAV-X can query a real local scan without wasting API credits.",
            }
        try:
            lat = float(lat); lon = float(lon)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("invalid Datalastic scan center")
            radius_nm = max(1.0, min(float(radius_nm), 50.0))
            cache_key = (round(lat, 3), round(lon, 3), round(radius_nm, 1))
            if self._cache_payload is not None and cache_key == self._cache_key and time.time() - self._cache_time < self._cache_seconds:
                return self._cache_payload
            with httpx.Client(timeout=15.0, headers={"x-api-key": self.api_key, "User-Agent": "ANTARCTIC-NAV-X/3.0"}) as client:
                response = client.get(DATALASTIC_INRADIUS_URL, params={"lat": lat, "lon": lon, "radius": radius_nm})
                response.raise_for_status()
                raw = response.json()
            data = raw.get("data") if isinstance(raw, dict) else None
            rows = (data or {}).get("vessels", []) if isinstance(data, dict) else []
            now = time.time()
            vessels: List[Dict[str, Any]] = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                vlat = _float_or_none(row.get("lat")); vlon = _float_or_none(row.get("lon"))
                if vlat is None or vlon is None or not (-90 <= vlat <= 90 and -180 <= vlon <= 180):
                    continue
                epoch = _epoch_from_utc_text(row.get("last_position_epoch") or row.get("last_position_UTC")) or now
                if now - epoch > max(1, int(max_age_minutes)) * 60:
                    continue
                heading = _float_or_none(row.get("heading"))
                if heading is not None and not (0 <= heading < 360): heading = None
                cog = _float_or_none(row.get("course"))
                if cog is not None and not (0 <= cog < 360): cog = None
                state = VesselState(
                    mmsi=str(row.get("mmsi") or row.get("uuid") or "").strip(),
                    name=str(row.get("name") or "").strip(),
                    lat=float(vlat), lon=float(vlon),
                    sog_knots=_float_or_none(row.get("speed")), cog_deg=cog, heading_deg=heading,
                    position_accuracy=None, message_type="DATALASTIC_INRADIUS",
                    last_seen_utc=_iso_from_epoch(epoch), last_seen_epoch=epoch,
                    imo=str(row.get("imo") or "").strip() or None,
                    destination=str(row.get("destination") or "").strip() or None,
                    ship_type=str(row.get("type_specific") or row.get("type") or "").strip() or None,
                    zone="ANTARCTIC" if vlat <= -60 else "SOUTHERN_OCEAN_APPROACH",
                )
                d = state.public(); d["trail"] = []; d["source"] = "Datalastic"; d["provider_distance_nm"] = _float_or_none(row.get("distance"))
                vessels.append(d)
            vessels = vessels[:max(1, min(int(limit), 1000))]
            self.status = "LIVE"
            self.last_error = None
            self.last_message_at = _utc_now_iso()
            payload = base | {
                "status": self.status,
                "count": len(vessels),
                "live_count": sum(1 for v in vessels if v.get("freshness") == "LIVE"),
                "recent_count": sum(1 for v in vessels if v.get("freshness") == "RECENT"),
                "stale_count": sum(1 for v in vessels if v.get("freshness") == "STALE"),
                "coverage": f"{radius_nm:.0f}-NM Datalastic live scan around {lat:.4f}, {lon:.4f}",
                "coverage_note": "Only vessels returned by Datalastic's genuine vessel_inradius endpoint are shown. Each unique scan may consume provider credits; identical scans are cached briefly.",
                "query_center": {"lat": lat, "lon": lon, "radius_nm": radius_nm},
                "vessels": vessels,
                "last_message_at": self.last_message_at,
                "generated_at": _utc_now_iso(),
            }
            self._cache_key, self._cache_time, self._cache_payload = cache_key, time.time(), payload
            return payload
        except Exception as exc:
            self.status = "ERROR"
            self.last_error = _safe_provider_error(exc, self.api_key)
            return base | {"status": self.status, "last_error": self.last_error, "count": 0, "vessels": [], "coverage_note": "The genuine Datalastic request failed; NAV-X did not substitute simulated vessels."}


class AISProviderManager:
    """Select exactly one configured genuine AIS source; never synthesize ships."""

    def __init__(self, data_root: Path):
        requested = (os.getenv("AIS_PROVIDER", "auto") or "auto").strip().lower()
        configured = {
            "aisstream": bool((os.getenv("AISSTREAM_API_KEY") or "").strip()),
            "aishub": bool((os.getenv("AISHUB_USERNAME") or "").strip()),
            "datalastic": bool((os.getenv("DATALASTIC_API_KEY") or "").strip()),
        }
        if requested == "auto":
            selected = next((p for p in ("aisstream", "aishub", "datalastic") if configured[p]), "none")
        elif requested in configured:
            selected = requested if configured[requested] else "none"
        else:
            selected = "none"
        self.requested = requested
        self.selected = selected
        if selected == "aisstream":
            self.backend: Any = AISStreamTracker(os.getenv("AISSTREAM_API_KEY", ""), data_root=data_root)
        elif selected == "aishub":
            self.backend = AISHubTracker(os.getenv("AISHUB_USERNAME", ""))
        elif selected == "datalastic":
            self.backend = DatalasticTracker(os.getenv("DATALASTIC_API_KEY", ""))
        else:
            self.backend = None
            self.min_lat = float(os.getenv("AIS_MIN_LAT", "-45"))

    @property
    def enabled(self) -> bool:
        return self.backend is not None and bool(self.backend.enabled)

    @property
    def status(self) -> str:
        return self.backend.status if self.backend is not None else "NOT_CONFIGURED"

    @property
    def provider_name(self) -> str:
        return {"aisstream": "AISStream.io", "aishub": "AISHub", "datalastic": "Datalastic"}.get(self.selected, "No AIS provider configured")

    @property
    def min_latitude(self) -> float:
        return float(getattr(self.backend, "min_lat", getattr(self, "min_lat", -45.0)))

    async def run(self) -> None:
        if self.backend is not None and self.backend.enabled:
            await self.backend.run()

    def stop(self) -> None:
        if self.backend is not None:
            self.backend.stop()

    def snapshot(self, max_age_minutes: int = 180, limit: int = 500,
                 lat: Optional[float] = None, lon: Optional[float] = None,
                 radius_nm: float = 50.0) -> Dict[str, Any]:
        if self.backend is None:
            return {
                "provider": "None",
                "mode": "NOT_CONFIGURED",
                "enabled": False,
                "status": "NOT_CONFIGURED",
                "count": 0,
                "live_count": 0,
                "recent_count": 0,
                "stale_count": 0,
                "vessels": [],
                "coverage": f"Southern Ocean south of {abs(self.min_latitude):.0f}°S",
                "coverage_note": "0 live vessels. Register/configure AISStream, AISHub, or Datalastic in .env. NAV-X does not generate placeholder vessel positions.",
                "required_action": "Set AIS_PROVIDER and the matching credential in .env, then restart the server.",
                "generated_at": _utc_now_iso(),
            }
        return self.backend.snapshot(max_age_minutes=max_age_minutes, limit=limit, lat=lat, lon=lon, radius_nm=radius_nm)

    def config_public(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "selected": self.selected,
            "requested": self.requested,
            "enabled": self.enabled,
            "status": self.status,
            "coverage": f"Southern Ocean south of {abs(self.min_latitude):.0f}°S",
            "actual_positions_only": True,
            "secret_location": ".env / server-side only",
            "supported_providers": ["AISStream.io", "AISHub", "Datalastic"],
        }
