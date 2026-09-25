from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Callable

from src.services.ingestion_service import (
    cds_credentials_configured,
    cmems_credentials_configured,
    iceberg_history_summary,
    sync_ais,
    sync_cmems,
    sync_era5,
    sync_iceberg_history,
    sync_ndbc,
    sync_nsidc,
    sync_sentinel1,
    sync_usnic,
)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:  # App remains inspectable; requirements.txt installs APScheduler for actual scheduling.
    AsyncIOScheduler = None


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class NavXIngestionScheduler:
    def __init__(self, usnic_live: Any, ais_tracker: Any):
        self.usnic_live = usnic_live
        self.ais_tracker = ais_tracker
        self.scheduler = AsyncIOScheduler(timezone="UTC") if AsyncIOScheduler else None
        self.started = False
        self.last_start_error: str | None = None

    async def _thread(self, fn: Callable, *args):
        return await asyncio.to_thread(fn, *args)

    async def run_usnic(self):
        return await self._thread(sync_usnic, self.usnic_live)

    async def run_ais(self):
        return await self._thread(sync_ais, self.ais_tracker)

    async def run_nsidc(self):
        return await self._thread(sync_nsidc)

    async def run_cmems(self):
        return await self._thread(sync_cmems)

    async def run_era5(self):
        return await self._thread(sync_era5)

    async def run_ndbc(self):
        return await self._thread(sync_ndbc)

    async def run_sentinel1(self):
        return await self._thread(sync_sentinel1)

    async def run_iceberg_history(self):
        return await self._thread(sync_iceberg_history, False)

    async def run_ais_ml(self):
        # Import lazily so server startup remains usable even if ML dependencies
        # are still being installed in a new environment.
        from src.ml.train_all import train_ais
        return await self._thread(train_ais, False)

    def start(self) -> None:
        if not _truthy("AUTO_INGESTION_ENABLED", True):
            self.last_start_error = "AUTO_INGESTION_ENABLED=false"
            return
        if self.scheduler is None:
            self.last_start_error = "APScheduler is not installed; run pip install -r requirements.txt"
            return
        if self.started:
            return

        ais_seconds = max(30, int(os.getenv("AIS_DB_SNAPSHOT_SECONDS", "30")))
        usnic_minutes = max(15, int(os.getenv("USNIC_REFRESH_MINUTES", "30")))
        nsidc_hours = max(1, int(os.getenv("NSIDC_REFRESH_HOURS", "6")))
        ndbc_minutes = max(5, int(os.getenv("NDBC_REFRESH_MINUTES", "10")))
        sentinel_hours = max(1, int(os.getenv("SENTINEL_REFRESH_HOURS", "6")))
        history_days = max(1, int(os.getenv("BYU_HISTORY_REFRESH_DAYS", "7")))
        ais_ml_minutes = max(5, int(os.getenv("AIS_ANOMALY_TRAIN_MINUTES", "15")))

        if self.ais_tracker.enabled:
            self.scheduler.add_job(
                self.run_ais, "interval", seconds=ais_seconds,
                id="ais_database_snapshot", replace_existing=True,
                max_instances=1, coalesce=True,
            )
            if _truthy("AUTO_TRAIN_AIS_ANOMALY", True):
                self.scheduler.add_job(
                    self.run_ais_ml, "interval", minutes=ais_ml_minutes,
                    id="ais_anomaly_training", replace_existing=True,
                    max_instances=1, coalesce=True,
                )

        self.scheduler.add_job(
            self.run_usnic, "interval", minutes=usnic_minutes,
            id="usnic_refresh", replace_existing=True, max_instances=1, coalesce=True,
        )
        self.scheduler.add_job(
            self.run_nsidc, "interval", hours=nsidc_hours,
            id="nsidc_refresh", replace_existing=True, max_instances=1, coalesce=True,
        )
        self.scheduler.add_job(
            self.run_ndbc, "interval", minutes=ndbc_minutes,
            id="ndbc_refresh", replace_existing=True, max_instances=1, coalesce=True,
        )
        if _truthy("AUTO_FETCH_ICEBERG_HISTORY", True):
            self.scheduler.add_job(
                self.run_iceberg_history, "interval", days=history_days,
                id="iceberg_history_refresh", replace_existing=True,
                max_instances=1, coalesce=True,
            )

        sentinel_configured = bool((os.getenv("SENTINEL_CLIENT_ID") or "").strip() and (os.getenv("SENTINEL_CLIENT_SECRET") or "").strip())
        if _truthy("AUTO_FETCH_SENTINEL1", True) and sentinel_configured:
            self.scheduler.add_job(
                self.run_sentinel1, "interval", hours=sentinel_hours,
                id="sentinel1_catalog_refresh", replace_existing=True,
                max_instances=1, coalesce=True,
            )

        if _truthy("AUTO_FETCH_CMEMS", True) and cmems_credentials_configured():
            self.scheduler.add_job(
                self.run_cmems, "cron",
                hour=int(os.getenv("CMEMS_REFRESH_UTC_HOUR", "2")), minute=0,
                id="cmems_refresh", replace_existing=True, max_instances=1, coalesce=True,
            )
        if _truthy("AUTO_FETCH_ERA5", True) and cds_credentials_configured():
            self.scheduler.add_job(
                self.run_era5, "cron",
                hour=int(os.getenv("ERA5_REFRESH_UTC_HOUR", "3")), minute=0,
                id="era5_refresh", replace_existing=True, max_instances=1, coalesce=True,
            )

        self.scheduler.start()
        self.started = True
        self.last_start_error = None

        # Bootstrap lightweight/current sources immediately without blocking
        # FastAPI startup. Historical backfill is bootstrapped only if the DB has
        # no imported historical rows, because a full archive import is large.
        loop = asyncio.get_running_loop()
        loop.create_task(self.run_usnic())
        if self.ais_tracker.enabled:
            loop.create_task(self.run_ais())
            if _truthy("AUTO_TRAIN_AIS_ANOMALY", True):
                loop.create_task(self.run_ais_ml())
        loop.create_task(self.run_nsidc())
        loop.create_task(self.run_ndbc())
        if _truthy("AUTO_FETCH_SENTINEL1", True) and sentinel_configured:
            loop.create_task(self.run_sentinel1())
        if _truthy("AUTO_FETCH_ICEBERG_HISTORY", True):
            try:
                if int(iceberg_history_summary(limit=1).get("historical_rows") or 0) == 0:
                    loop.create_task(self.run_iceberg_history())
            except Exception:
                loop.create_task(self.run_iceberg_history())

    def stop(self) -> None:
        if self.scheduler is not None and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.started = False

    def public_status(self) -> dict:
        jobs = []
        if self.scheduler is not None:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "next_run_time": job.next_run_time.astimezone(timezone.utc).isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })
        return {
            "enabled": _truthy("AUTO_INGESTION_ENABLED", True),
            "running": self.started,
            "engine": "APScheduler" if self.scheduler is not None else "UNAVAILABLE",
            "start_error": self.last_start_error,
            "provider_configuration": {
                "ais": bool(self.ais_tracker.enabled),
                "ais_anomaly_auto_training": bool(self.ais_tracker.enabled and _truthy("AUTO_TRAIN_AIS_ANOMALY", True)),
                "usnic": "KEYLESS_PUBLIC_SOURCE",
                "iceberg_history": "BYU_NIC_PUBLISHED_ARCHIVE",
                "nsidc": "KEYLESS_PUBLIC_HTTPS",
                "noaa_ndbc": "KEYLESS_PUBLIC_HTTPS",
                "cmems": cmems_credentials_configured(),
                "era5_cds": cds_credentials_configured(),
                "sentinel1_cdse": bool((os.getenv("SENTINEL_CLIENT_ID") or "").strip() and (os.getenv("SENTINEL_CLIENT_SECRET") or "").strip()),
            },
            "jobs": jobs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
