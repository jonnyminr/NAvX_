from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import desc, func, select

from src.data_providers.byu_current_iceberg_provider import (
    fetch_byu_current_icebergs,
)
from src.db.database import SessionLocal, init_database
from src.db.models import (
    BuoyObservation,
    DatasetSnapshot,
    IcebergObservation,
    ProviderFetch,
    SatelliteScene,
    SchedulerState,
    VesselPosition,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


# ============================================================
# GENERAL HELPERS
# ============================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value

    else:
        text = str(value).strip()

        if not text:
            return None

        candidates = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
        ]

        normalized = (
            text.replace("Z", "+00:00")
            if text.endswith("Z")
            else text
        )

        try:
            dt = datetime.fromisoformat(normalized)

        except ValueError:
            dt = None

            for fmt in candidates:
                try:
                    dt = datetime.strptime(text, fmt)
                    break

                except ValueError:
                    continue

            if dt is None:
                return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


# ============================================================
# PROVIDER AUDIT / SCHEDULER DATABASE HELPERS
# ============================================================

def _start_fetch(
    provider: str,
    job_name: str,
) -> int:
    with SessionLocal() as db:
        row = ProviderFetch(
            provider=provider,
            job_name=job_name,
            started_at=_utc_now(),
        )

        db.add(row)

        state = db.scalar(
            select(SchedulerState).where(
                SchedulerState.job_name
                == job_name
            )
        )

        if state is None:
            state = SchedulerState(
                job_name=job_name,
                provider=provider,
            )

            db.add(state)

        state.last_started_at = _utc_now()
        state.last_status = "RUNNING"
        state.last_message = None

        db.commit()
        db.refresh(row)

        return row.id


def _finish_fetch(
    fetch_id: int,
    job_name: str,
    success: bool,
    rows_written: int,
    message: str,
) -> None:
    now = _utc_now()

    with SessionLocal() as db:
        row = db.get(
            ProviderFetch,
            fetch_id,
        )

        if row:
            row.finished_at = now
            row.success = success
            row.rows_written = int(
                rows_written
            )
            row.message = (
                message or ""
            )[:4000]

        state = db.scalar(
            select(SchedulerState).where(
                SchedulerState.job_name
                == job_name
            )
        )

        if state:
            state.last_finished_at = now

            state.last_status = (
                "SUCCESS"
                if success
                else "ERROR"
            )

            state.last_message = (
                message or ""
            )[:4000]

            if success:
                state.last_success_at = now

        db.commit()


def _run_audited(
    provider: str,
    job_name: str,
    fn: Callable[[], dict],
) -> dict:
    init_database()

    fetch_id = _start_fetch(
        provider,
        job_name,
    )

    try:
        result = fn() or {}

        ok = bool(
            result.get(
                "ok",
                True,
            )
        )

        rows = int(
            result.get(
                "rows_written",
                0,
            )
            or 0
        )

        message = str(
            result.get("message")
            or (
                "Completed"
                if ok
                else "Provider returned unavailable"
            )
        )

        _finish_fetch(
            fetch_id,
            job_name,
            ok,
            rows,
            message,
        )

        return {
            "provider": provider,
            "job_name": job_name,
            **result,
        }

    except Exception as exc:
        message = (
            f"{type(exc).__name__}: {exc}"
        )

        _finish_fetch(
            fetch_id,
            job_name,
            False,
            0,
            message,
        )

        return {
            "provider": provider,
            "job_name": job_name,
            "ok": False,
            "rows_written": 0,
            "message": message,
        }


# ============================================================
# CURRENT-SNAPSHOT HELPERS
# ============================================================

def _latest_source_snapshot(
    db,
    source: str,
) -> dict:
    """
    Determine which rows belong to the newest available
    snapshot of a current iceberg source.

    This prevents old USNIC/BYU observations from being
    presented as current navigation hazards.
    """

    rows = list(
        db.scalars(
            select(
                IcebergObservation
            ).where(
                IcebergObservation.source
                == source
            )
        ).all()
    )

    if not rows:
        return {
            "source": source,
            "iceberg_ids": set(),
            "row_ids": set(),
            "retrieved_at": None,
            "revision": None,
        }

    # BYU publishes one page revision for all rows
    # belonging to the same current source publication.
    if source == "BYU_SCP_CURRENT":
        revision_values = []

        for row in rows:
            raw_data = (
                row.raw_data or {}
            )

            revision = raw_data.get(
                "page_last_revised"
            )

            if revision:
                revision_values.append(
                    str(revision)
                )

        if revision_values:
            latest_revision = max(
                revision_values
            )

            current_rows = [
                row
                for row in rows
                if str(
                    (row.raw_data or {}).get(
                        "page_last_revised"
                    )
                    or ""
                )
                == latest_revision
            ]

            current_retrieved = [
                row.retrieved_at
                for row in current_rows
                if row.retrieved_at
                is not None
            ]

            return {
                "source":
                    source,

                "iceberg_ids":
                    {
                        row.iceberg_id
                        for row in current_rows
                    },

                "row_ids":
                    {
                        row.id
                        for row in current_rows
                    },

                "retrieved_at":
                    (
                        max(current_retrieved)
                        if current_retrieved
                        else None
                    ),

                "revision":
                    latest_revision,
            }

    retrieved_values = [
        row.retrieved_at
        for row in rows
        if row.retrieved_at
        is not None
    ]

    if not retrieved_values:
        return {
            "source": source,
            "iceberg_ids": set(),
            "row_ids": set(),
            "retrieved_at": None,
            "revision": None,
        }

    latest_retrieved = max(
        retrieved_values
    )

    current_rows = [
        row
        for row in rows
        if row.retrieved_at
        == latest_retrieved
    ]

    return {
        "source":
            source,

        "iceberg_ids":
            {
                row.iceberg_id
                for row in current_rows
            },

        "row_ids":
            {
                row.id
                for row in current_rows
            },

        "retrieved_at":
            latest_retrieved,

        "revision":
            None,
    }


# ============================================================
# USNIC CURRENT ICEBERGS
# ============================================================

def persist_usnic_payload(
    payload: dict,
) -> int:
    rows_written = 0

    retrieved_at = (
        _parse_datetime(
            (
                payload.get("metadata")
                or {}
            ).get(
                "retrieved_at"
            )
        )
        or _utc_now()
    )

    with SessionLocal() as db:
        for feature in payload.get(
            "features",
            [],
        ):
            props = (
                feature.get("properties")
                or {}
            )

            geometry = (
                feature.get("geometry")
                or {}
            )

            coords = (
                geometry.get("coordinates")
                or []
            )

            try:
                lon = float(
                    coords[0]
                )

                lat = float(
                    coords[1]
                )

            except (
                IndexError,
                TypeError,
                ValueError,
            ):
                continue

            iceberg_id = str(
                props.get("id")
                or ""
            ).strip().upper()

            if not iceberg_id:
                continue

            observed_label = str(
                props.get(
                    "date_observed"
                )
                or "UNKNOWN"
            ).strip()

            existing = db.scalar(
                select(
                    IcebergObservation
                ).where(
                    IcebergObservation.iceberg_id
                    == iceberg_id,

                    IcebergObservation.observed_label
                    == observed_label,

                    IcebergObservation.source
                    == "USNIC",
                )
            )

            values = dict(
                observed_at=
                    _parse_datetime(
                        props.get(
                            "date_observed"
                        )
                    ),

                latitude=
                    lat,

                longitude=
                    lon,

                length_nm=
                    props.get(
                        "length_nm"
                    ),

                width_nm=
                    props.get(
                        "width_nm"
                    ),

                area_sqkm=
                    props.get(
                        "area_sqkm"
                    ),

                retrieved_at=
                    retrieved_at,

                raw_data=
                    props,
            )

            if existing:
                for key, value in values.items():
                    setattr(
                        existing,
                        key,
                        value,
                    )

            else:
                db.add(
                    IcebergObservation(
                        iceberg_id=
                            iceberg_id,

                        observed_label=
                            observed_label,

                        source=
                            "USNIC",

                        **values,
                    )
                )

                rows_written += 1

        db.commit()

    return rows_written


def sync_usnic(
    usnic_live,
) -> dict:
    def work() -> dict:
        payload = usnic_live.refresh(
            force=True,
            min_interval_seconds=0,
        )

        features = payload.get(
            "features",
            [],
        )

        rows = (
            persist_usnic_payload(
                payload
            )
            if features
            else 0
        )

        ok = bool(
            features
        )

        return {
            "ok":
                ok,

            "rows_written":
                rows,

            "records_seen":
                len(features),

            "message":
                (
                    f"USNIC records={len(features)}, "
                    f"new_database_rows={rows}"
                    if ok
                    else
                    "No verified USNIC records available"
                ),
        }

    return _run_audited(
        "USNIC",
        "usnic_refresh",
        work,
    )


# ============================================================
# BYU/SCP SUPPLEMENTAL CURRENT ICEBERGS
# ============================================================

def sync_byu_current_icebergs() -> dict:
    """
    Fetch and persist BYU/SCP ASCAT + OSCAT-2
    supplemental current iceberg observations.

    USNIC remains the authoritative current source.

    Existing rows are refreshed so we know which
    observations still belong to the newest source page.
    """

    source = "BYU_SCP_CURRENT"

    def work() -> dict:
        records, metadata = (
            fetch_byu_current_icebergs()
        )

        inserted = 0
        updated = 0

        # Use exactly the same retrieval timestamp
        # for the whole publication snapshot.
        retrieved_at = _utc_now()

        with SessionLocal() as db:
            for record in records:
                observed_label = (
                    record.observed_at.strftime(
                        "%Y-%m-%d"
                    )
                )

                existing = db.scalar(
                    select(
                        IcebergObservation
                    ).where(
                        IcebergObservation.iceberg_id
                        == record.iceberg_id,

                        IcebergObservation.observed_label
                        == observed_label,

                        IcebergObservation.source
                        == source,
                    )
                )

                if existing is None:
                    row = IcebergObservation(
                        iceberg_id=
                            record.iceberg_id,

                        observed_at=
                            record.observed_at,

                        observed_label=
                            observed_label,

                        latitude=
                            record.latitude,

                        longitude=
                            record.longitude,

                        source=
                            source,

                        retrieved_at=
                            retrieved_at,

                        raw_data=
                            record.raw_data,
                    )

                    db.add(row)

                    inserted += 1

                else:
                    existing_date = (
                        existing.observed_at.date()
                        if existing.observed_at
                        else None
                    )

                    incoming_date = (
                        record.observed_at.date()
                        if record.observed_at
                        else None
                    )

                    existing_lat = (
                        float(
                            existing.latitude
                        )
                        if existing.latitude
                        is not None
                        else None
                    )

                    existing_lon = (
                        float(
                            existing.longitude
                        )
                        if existing.longitude
                        is not None
                        else None
                    )

                    incoming_lat = float(
                        record.latitude
                    )

                    incoming_lon = float(
                        record.longitude
                    )

                    changed = (
                        existing_lat is None
                        or existing_lon is None
                        or abs(
                            existing_lat
                            - incoming_lat
                        )
                        > 1e-9
                        or abs(
                            existing_lon
                            - incoming_lon
                        )
                        > 1e-9
                        or existing_date
                        != incoming_date
                    )

                    existing.observed_at = (
                        record.observed_at
                    )

                    existing.latitude = (
                        record.latitude
                    )

                    existing.longitude = (
                        record.longitude
                    )

                    existing.retrieved_at = (
                        retrieved_at
                    )

                    existing.raw_data = (
                        record.raw_data
                    )

                    if changed:
                        updated += 1

            db.commit()

        return {
            "provider":
                source,

            "job_name":
                "byu_current_refresh",

            "ok":
                True,

            "records_seen":
                len(records),

            "rows_written":
                inserted,

            "rows_updated":
                updated,

            "page_last_revised":
                metadata.get(
                    "page_last_revised"
                ),

            "authoritative_current_source":
                "USNIC",

            "source_role":
                "SUPPLEMENTAL_CURRENT",

            "message":
                (
                    "BYU/SCP supplemental current "
                    "iceberg observations stored."
                ),
        }

    return _run_audited(
        "BYU_SCP_CURRENT",
        "byu_current_refresh",
        work,
    )


# ============================================================
# HISTORICAL BYU / NIC ICEBERG TRACK DATABASE
# ============================================================

def persist_historical_iceberg_records(
    records,
) -> dict:
    """
    Persist published historical track positions without
    mixing them with current USNIC/BYU fixes.
    """

    source = "BYU_NIC_CONSOLIDATED"

    inserted = 0
    updated = 0
    seen = 0

    unique_icebergs = set()

    with SessionLocal() as db:
        existing_rows = list(
            db.scalars(
                select(
                    IcebergObservation
                ).where(
                    IcebergObservation.source
                    == source
                )
            ).all()
        )

        existing = {
            (
                row.iceberg_id,
                row.observed_label,
            ):
                row

            for row in existing_rows
        }

        for record in records:
            seen += 1

            unique_icebergs.add(
                record.iceberg_id
            )

            key = (
                record.iceberg_id,
                record.observed_label,
            )

            row = existing.get(
                key
            )

            values = dict(
                observed_at=
                    record.observed_at,

                latitude=
                    record.latitude,

                longitude=
                    record.longitude,

                retrieved_at=
                    _utc_now(),

                raw_data=
                    record.raw_data,
            )

            if row is None:
                row = IcebergObservation(
                    iceberg_id=
                        record.iceberg_id,

                    observed_label=
                        record.observed_label,

                    source=
                        source,

                    **values,
                )

                db.add(row)

                existing[key] = row

                inserted += 1

            else:
                changed = any(
                    getattr(
                        row,
                        key_name,
                    )
                    != value

                    for (
                        key_name,
                        value
                    ) in values.items()

                    if key_name
                    != "retrieved_at"
                )

                for (
                    key_name,
                    value
                ) in values.items():
                    setattr(
                        row,
                        key_name,
                        value,
                    )

                if changed:
                    updated += 1

            if seen % 5000 == 0:
                db.flush()

        db.commit()

    return {
        "records_seen":
            seen,

        "rows_written":
            inserted,

        "rows_updated":
            updated,

        "unique_icebergs":
            len(
                unique_icebergs
            ),
    }


def sync_iceberg_history(
    force_download: bool = False,
) -> dict:
    """
    Download/import the published BYU/NIC historical
    iceberg track database.

    Historical positions remain a research/history layer.
    They are never automatically treated as current
    navigation hazards.
    """

    def work() -> dict:
        from src.data_providers.iceberg_archive_provider import (
            BYUIcebergHistoryProvider,
        )

        provider = (
            BYUIcebergHistoryProvider(
                DATA_DIR
            )
        )

        info = provider.download(
            force=force_download
        )

        archive_path = Path(
            info["path"]
        )

        archive_checksum = (
            sha256_file(
                archive_path
            )
        )

        with SessionLocal() as db:
            already_imported = db.scalar(
                select(
                    DatasetSnapshot
                ).where(
                    DatasetSnapshot.provider
                    == "BYU_SCP_NIC",

                    DatasetSnapshot.dataset_type
                    == (
                        "ICEBERG_HISTORICAL_"
                        "TRACK_DATABASE"
                    ),

                    DatasetSnapshot.checksum_sha256
                    == archive_checksum,
                )
            )

            existing_history = int(
                db.scalar(
                    select(func.count())
                    .select_from(
                        IcebergObservation
                    )
                    .where(
                        IcebergObservation.source
                        == "BYU_NIC_CONSOLIDATED"
                    )
                )
                or 0
            )

        if (
            already_imported is not None
            and existing_history > 0
        ):
            return {
                "ok":
                    True,

                "records_seen":
                    0,

                "rows_written":
                    0,

                "rows_updated":
                    0,

                "unique_icebergs":
                    int(
                        iceberg_history_summary(
                            limit=1
                        ).get(
                            "unique_icebergs"
                        )
                        or 0
                    ),

                "dataset_metadata_row":
                    "already_recorded",

                "message":
                    (
                        "Historical iceberg archive "
                        f"unchanged; {existing_history} "
                        "published historical positions "
                        "already stored"
                    ),
            }

        stats = (
            persist_historical_iceberg_records(
                provider.iter_records(
                    info["path"]
                )
            )
        )

        inserted_snapshot = (
            record_dataset_snapshot(
                provider=
                    "BYU_SCP_NIC",

                dataset_type=
                    (
                        "ICEBERG_HISTORICAL_"
                        "TRACK_DATABASE"
                    ),

                local_path=
                    info["path"],

                dataset_id=
                    (
                        "BYU/NIC consolidated "
                        "Antarctic iceberg database"
                    ),

                metadata={
                    "source_url":
                        info.get("url"),

                    "mode":
                        info.get("mode"),

                    "historical_only":
                        True,

                    "authoritative_current_source":
                        "USNIC",
                },
            )
        )

        return {
            "ok":
                stats[
                    "records_seen"
                ]
                > 0,

            **stats,

            "dataset_metadata_row":
                (
                    "created"
                    if inserted_snapshot
                    else "already_recorded"
                ),

            "message":
                (
                    "Historical iceberg track import: "
                    f"{stats['unique_icebergs']} "
                    "designations, "
                    f"{stats['records_seen']} "
                    "published positions, "
                    f"{stats['rows_written']} "
                    "new rows, "
                    f"{stats['rows_updated']} "
                    "updated rows"
                ),
        }

    return _run_audited(
        "BYU_SCP_NIC",
        "iceberg_history_refresh",
        work,
    )


# ============================================================
# UNIFIED ICEBERG CATALOG
# ============================================================

def iceberg_history_summary(
    limit: int = 2000,
    search: str | None = None,
) -> dict:
    """
    Unified iceberg catalogue.

    Combines:
    - latest official current USNIC publication
    - latest supplemental BYU/SCP publication
    - BYU/NIC historical tracks

    The database can contain previous USNIC/BYU observations,
    but only observations belonging to the newest publication
    are labelled CURRENT.
    """

    init_database()

    with SessionLocal() as db:
        stmt = (
            select(
                IcebergObservation.iceberg_id,

                func.count(
                    IcebergObservation.id
                ).label(
                    "observation_count"
                ),

                func.min(
                    IcebergObservation.observed_at
                ).label(
                    "first_observed_at"
                ),

                func.max(
                    IcebergObservation.observed_at
                ).label(
                    "last_observed_at"
                ),
            )
            .group_by(
                IcebergObservation.iceberg_id
            )
            .order_by(
                IcebergObservation.iceberg_id
            )
        )

        if search:
            stmt = stmt.where(
                IcebergObservation.iceberg_id.ilike(
                    f"%{search.strip()}%"
                )
            )

        rows = db.execute(
            stmt.limit(
                max(
                    1,
                    min(
                        int(limit),
                        5000,
                    ),
                )
            )
        ).all()

        usnic_snapshot = (
            _latest_source_snapshot(
                db,
                "USNIC",
            )
        )

        byu_snapshot = (
            _latest_source_snapshot(
                db,
                "BYU_SCP_CURRENT",
            )
        )

        usnic_current_ids = (
            usnic_snapshot[
                "iceberg_ids"
            ]
        )

        byu_current_ids = (
            byu_snapshot[
                "iceberg_ids"
            ]
        )

        historical_ids = set(
            db.scalars(
                select(
                    IcebergObservation.iceberg_id
                ).where(
                    IcebergObservation.source
                    == "BYU_NIC_CONSOLIDATED"
                )
            ).all()
        )

        historical_rows = int(
            db.scalar(
                select(func.count())
                .select_from(
                    IcebergObservation
                )
                .where(
                    IcebergObservation.source
                    == "BYU_NIC_CONSOLIDATED"
                )
            )
            or 0
        )

        usnic_rows = int(
            db.scalar(
                select(func.count())
                .select_from(
                    IcebergObservation
                )
                .where(
                    IcebergObservation.source
                    == "USNIC"
                )
            )
            or 0
        )

        byu_current_rows = int(
            db.scalar(
                select(func.count())
                .select_from(
                    IcebergObservation
                )
                .where(
                    IcebergObservation.source
                    == "BYU_SCP_CURRENT"
                )
            )
            or 0
        )

        total_rows = int(
            db.scalar(
                select(func.count())
                .select_from(
                    IcebergObservation
                )
            )
            or 0
        )

        unique_count = int(
            db.scalar(
                select(
                    func.count(
                        func.distinct(
                            IcebergObservation.iceberg_id
                        )
                    )
                )
            )
            or 0
        )

        earliest = db.scalar(
            select(
                func.min(
                    IcebergObservation.observed_at
                )
            )
        )

        latest = db.scalar(
            select(
                func.max(
                    IcebergObservation.observed_at
                )
            )
        )

    catalog = []

    for row in rows:
        iceberg_id = (
            row.iceberg_id
        )

        in_usnic = (
            iceberg_id
            in usnic_current_ids
        )

        in_byu_current = (
            iceberg_id
            in byu_current_ids
        )

        has_history = (
            iceberg_id
            in historical_ids
        )

        if in_usnic:
            current_status = (
                "OFFICIAL_CURRENT"
            )

        elif in_byu_current:
            current_status = (
                "SUPPLEMENTAL_CURRENT"
            )

        else:
            current_status = (
                "HISTORICAL_ONLY"
            )

        catalog.append(
            {
                "iceberg_id":
                    iceberg_id,

                "observation_count":
                    int(
                        row.observation_count
                        or 0
                    ),

                "first_observed_at":
                    (
                        row.first_observed_at.isoformat()
                        if row.first_observed_at
                        else None
                    ),

                "last_observed_at":
                    (
                        row.last_observed_at.isoformat()
                        if row.last_observed_at
                        else None
                    ),

                "currently_in_usnic_database":
                    in_usnic,

                "currently_in_byu_scp_database":
                    in_byu_current,

                "has_historical_track":
                    has_history,

                "current_status":
                    current_status,

                "sources": [
                    source_name

                    for (
                        source_name,
                        enabled,
                    ) in [
                        (
                            "USNIC",
                            in_usnic,
                        ),
                        (
                            "BYU/SCP CURRENT",
                            in_byu_current,
                        ),
                        (
                            "BYU/NIC HISTORICAL",
                            has_history,
                        ),
                    ]

                    if enabled
                ],
            }
        )

    return {
        "source_model":
            (
                "USNIC official current + "
                "BYU/SCP supplemental current + "
                "BYU/NIC historical tracks"
            ),

        "authoritative_current_source":
            "USNIC",

        "supplemental_current_source":
            "BYU/SCP ASCAT + OSCAT-2",

        "historical_source":
            (
                "BYU Scatterometer Climate "
                "Record Pathfinder / NIC "
                "consolidated database"
            ),

        "unique_icebergs":
            unique_count,

        "observation_rows":
            total_rows,

        "historical_rows":
            historical_rows,

        "usnic_observation_rows":
            usnic_rows,

        "byu_current_observation_rows":
            byu_current_rows,

        "current_usnic_designations":
            len(
                usnic_current_ids
            ),

        "current_byu_designations":
            len(
                byu_current_ids
            ),

        "earliest_observed_at":
            (
                earliest.isoformat()
                if earliest
                else None
            ),

        "latest_observed_at":
            (
                latest.isoformat()
                if latest
                else None
            ),

        "usnic_latest_retrieved_at":
            (
                usnic_snapshot[
                    "retrieved_at"
                ].isoformat()
                if usnic_snapshot[
                    "retrieved_at"
                ]
                else None
            ),

        "byu_latest_retrieved_at":
            (
                byu_snapshot[
                    "retrieved_at"
                ].isoformat()
                if byu_snapshot[
                    "retrieved_at"
                ]
                else None
            ),

        "byu_page_revision":
            byu_snapshot.get(
                "revision"
            ),

        "catalog":
            catalog,

        "data_policy":
            (
                "Historical and archived observations "
                "are retained for tracks and research "
                "but are not automatically treated as "
                "present-day navigation hazards."
            ),
    }


def iceberg_history_records(
    iceberg_id: str,
    limit: int = 20000,
) -> list[dict]:
    """
    Return all stored positions for one iceberg while
    preserving the real source classification.
    """

    init_database()

    target = (
        str(iceberg_id)
        .strip()
        .upper()
    )

    with SessionLocal() as db:
        usnic_snapshot = (
            _latest_source_snapshot(
                db,
                "USNIC",
            )
        )

        byu_snapshot = (
            _latest_source_snapshot(
                db,
                "BYU_SCP_CURRENT",
            )
        )

        current_usnic_row_ids = (
            usnic_snapshot[
                "row_ids"
            ]
        )

        current_byu_row_ids = (
            byu_snapshot[
                "row_ids"
            ]
        )

        rows = list(
            db.scalars(
                select(
                    IcebergObservation
                )
                .where(
                    IcebergObservation.iceberg_id
                    == target
                )
                .order_by(
                    IcebergObservation.observed_at,
                    IcebergObservation.id,
                )
                .limit(
                    max(
                        1,
                        min(
                            int(limit),
                            50000,
                        ),
                    )
                )
            ).all()
        )

        results = []

        for row in rows:
            is_current_snapshot = False

            if row.source == "USNIC":
                if (
                    row.id
                    in current_usnic_row_ids
                ):
                    position_type = (
                        "OFFICIAL_CURRENT"
                    )

                    is_current_snapshot = True

                else:
                    position_type = (
                        "OFFICIAL_USNIC_"
                        "ARCHIVED_OBSERVATION"
                    )

            elif (
                row.source
                == "BYU_SCP_CURRENT"
            ):
                if (
                    row.id
                    in current_byu_row_ids
                ):
                    position_type = (
                        "SUPPLEMENTAL_CURRENT"
                    )

                    is_current_snapshot = True

                else:
                    position_type = (
                        "SUPPLEMENTAL_"
                        "ARCHIVED_OBSERVATION"
                    )

            elif (
                row.source
                == "BYU_NIC_CONSOLIDATED"
            ):
                position_type = (
                    "PUBLISHED_HISTORICAL_"
                    "TRACK_POSITION"
                )

            else:
                position_type = (
                    "SOURCE_CLASSIFICATION_UNKNOWN"
                )

            raw_data = (
                row.raw_data
                or {}
            )

            results.append(
                {
                    "date":
                        (
                            row.observed_at
                            .date()
                            .isoformat()
                            if row.observed_at
                            else row.observed_label
                        ),

                    "timestamp":
                        (
                            row.observed_at.isoformat()
                            if row.observed_at
                            else None
                        ),

                    "latitude":
                        row.latitude,

                    "longitude":
                        row.longitude,

                    "length_nm":
                        row.length_nm,

                    "width_nm":
                        row.width_nm,

                    "area_sqkm":
                        row.area_sqkm,

                    "source":
                        row.source,

                    "position_type":
                        position_type,

                    "is_current_snapshot":
                        is_current_snapshot,

                    "historical_only":
                        not is_current_snapshot,

                    "sensor":
                        (
                            raw_data.get(
                                "sensor"
                            )
                            or raw_data.get(
                                "selected_sensor"
                            )
                        ),

                    "source_url":
                        raw_data.get(
                            "source_url"
                        ),

                    "page_last_revised":
                        raw_data.get(
                            "page_last_revised"
                        ),

                    "raw_source_file":
                        raw_data.get(
                            "source_file"
                        ),

                    "interpolation_note":
                        raw_data.get(
                            "interpolation_note"
                        ),
                }
            )

    return results


# Backwards/forwards-compatible unified API helper.
def iceberg_unified_catalog(
    limit: int = 5000,
    search: str | None = None,
) -> dict:
    return iceberg_history_summary(
        limit=limit,
        search=search,
    )


def iceberg_unified_track(
    iceberg_id: str,
    limit: int = 20000,
) -> dict:
    records = iceberg_history_records(
        iceberg_id,
        limit=limit,
    )

    target = (
        str(iceberg_id)
        .strip()
        .upper()
    )

    return {
        "iceberg_id":
            target,

        "position_count":
            len(records),

        "positions":
            records,
    }


# ============================================================
# AIS DATABASE
# ============================================================

def persist_ais_snapshot(
    snapshot: dict,
) -> int:
    provider = str(
        snapshot.get("provider")
        or snapshot.get("source")
        or "AIS"
    ).strip()

    rows_written = 0

    with SessionLocal() as db:
        for vessel in snapshot.get(
            "vessels",
            [],
        ):
            mmsi = str(
                vessel.get("mmsi")
                or ""
            ).strip()

            if not mmsi:
                continue

            received_at = (
                _parse_datetime(
                    vessel.get(
                        "last_seen_utc"
                    )
                    or vessel.get(
                        "received_at"
                    )
                )
            )

            if received_at is None:
                continue

            try:
                lat = float(
                    vessel.get(
                        "lat",
                        vessel.get(
                            "latitude"
                        ),
                    )
                )

                lon = float(
                    vessel.get(
                        "lon",
                        vessel.get(
                            "longitude"
                        ),
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            existing = db.scalar(
                select(
                    VesselPosition
                ).where(
                    VesselPosition.provider
                    == provider,

                    VesselPosition.mmsi
                    == mmsi,

                    VesselPosition.received_at
                    == received_at,
                )
            )

            if existing:
                continue

            db.add(
                VesselPosition(
                    provider=
                        provider,

                    mmsi=
                        mmsi,

                    name=
                        vessel.get(
                            "name"
                        ),

                    latitude=
                        lat,

                    longitude=
                        lon,

                    sog_knots=
                        vessel.get(
                            "sog_knots"
                        ),

                    cog_deg=
                        vessel.get(
                            "cog_deg"
                        ),

                    heading_deg=
                        vessel.get(
                            "heading_deg"
                        ),

                    imo=
                        (
                            str(
                                vessel.get(
                                    "imo"
                                )
                            )
                            if vessel.get(
                                "imo"
                            )
                            is not None
                            else None
                        ),

                    call_sign=
                        vessel.get(
                            "call_sign"
                        ),

                    destination=
                        vessel.get(
                            "destination"
                        ),

                    freshness=
                        vessel.get(
                            "freshness"
                        ),

                    received_at=
                        received_at,

                    raw_data=
                        vessel,
                )
            )

            rows_written += 1

        db.commit()

    return rows_written


def sync_ais(
    ais_tracker,
) -> dict:
    def work() -> dict:
        snapshot = ais_tracker.snapshot(
            max_age_minutes=int(
                os.getenv(
                    "AIS_MAX_POSITION_AGE_MINUTES",
                    "180",
                )
            ),
            limit=1000,
        )

        vessels = snapshot.get(
            "vessels",
            [],
        )

        rows = (
            persist_ais_snapshot(
                snapshot
            )
            if vessels
            else 0
        )

        configured = (
            bool(
                snapshot.get(
                    "enabled"
                )
            )
            or snapshot.get(
                "status"
            )
            not in {
                "NOT_CONFIGURED",
                "DISABLED",
            }
        )

        # Zero vessels is valid.
        # We never manufacture AIS positions.
        ok = configured

        return {
            "ok":
                ok,

            "rows_written":
                rows,

            "records_seen":
                len(vessels),

            "message":
                (
                    f"AIS current_positions="
                    f"{len(vessels)}, "
                    f"new_database_rows={rows}"
                    if configured
                    else
                    (
                        "AIS provider is not configured; "
                        "no vessel data was invented"
                    )
                ),
        }

    return _run_audited(
        "AIS",
        "ais_database_snapshot",
        work,
    )


# ============================================================
# DATASET SNAPSHOTS
# ============================================================

def record_dataset_snapshot(
    provider: str,
    dataset_type: str,
    local_path: str | Path,
    dataset_id: str | None = None,
    observed_at: Any = None,
    metadata: dict | None = None,
) -> bool:
    path = Path(
        local_path
    )

    if (
        not path.exists()
        or not path.is_file()
    ):
        return False

    checksum = sha256_file(
        path
    )

    with SessionLocal() as db:
        existing = db.scalar(
            select(
                DatasetSnapshot
            ).where(
                DatasetSnapshot.provider
                == provider,

                DatasetSnapshot.dataset_type
                == dataset_type,

                DatasetSnapshot.checksum_sha256
                == checksum,
            )
        )

        if existing:
            return False

        try:
            relative = str(
                path.resolve().relative_to(
                    ROOT.resolve()
                )
            )

        except ValueError:
            relative = str(
                path.resolve()
            )

        db.add(
            DatasetSnapshot(
                provider=
                    provider,

                dataset_type=
                    dataset_type,

                dataset_id=
                    dataset_id,

                local_path=
                    relative,

                checksum_sha256=
                    checksum,

                observed_at=
                    _parse_datetime(
                        observed_at
                    ),

                retrieved_at=
                    _utc_now(),

                metadata_json=
                    metadata or {},
            )
        )

        db.commit()

        return True


# ============================================================
# NSIDC SEA ICE
# ============================================================

def sync_nsidc() -> dict:
    def work() -> dict:
        from src.data_ingestion.ingest_sea_ice import (
            run_ingestion,
        )

        result = run_ingestion(
            quiet=True
        )

        if (
            not result
            or not result.get("ok")
        ):
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    (
                        result or {}
                    ).get(
                        "message",
                        (
                            "NSIDC ingestion "
                            "unavailable"
                        ),
                    ),
            }

        inserted = (
            record_dataset_snapshot(
                provider=
                    "NSIDC",

                dataset_type=
                    "SEA_ICE_CONCENTRATION",

                local_path=
                    result["path"],

                dataset_id=
                    "G02135-v4",

                observed_at=
                    result.get(
                        "observed_at"
                    ),

                metadata=
                    result,
            )
        )

        return {
            "ok":
                True,

            "rows_written":
                1 if inserted else 0,

            "records_seen":
                1,

            "message":
                (
                    f"NSIDC file="
                    f"{Path(result['path']).name}; "
                    f"metadata_row="
                    f"{'created' if inserted else 'already_recorded'}"
                ),
        }

    return _run_audited(
        "NSIDC",
        "nsidc_refresh",
        work,
    )


# ============================================================
# COPERNICUS MARINE / CMEMS
# ============================================================

def cmems_credentials_configured() -> bool:
    user = (
        os.getenv(
            "COPERNICUSMARINE_SERVICE_USERNAME"
        )
        or os.getenv(
            "COPERNICUS_USERNAME"
        )
        or ""
    ).strip()

    password = (
        os.getenv(
            "COPERNICUSMARINE_SERVICE_PASSWORD"
        )
        or os.getenv(
            "COPERNICUS_PASSWORD"
        )
        or ""
    ).strip()

    credential_file = (
        Path.home()
        / ".copernicusmarine"
        / ".copernicusmarine-credentials"
    )

    netrc = (
        Path.home()
        / "_netrc"
    )

    return bool(
        (user and password)
        or credential_file.exists()
        or netrc.exists()
    )


def sync_cmems() -> dict:
    def work() -> dict:
        from src.data_ingestion.ocean_loader import (
            load_ocean_data,
        )

        if not cmems_credentials_configured():
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    (
                        "Copernicus Marine credentials "
                        "are not configured"
                    ),
            }

        ds, metadata = (
            load_ocean_data()
        )

        if (
            ds is None
            or metadata is None
        ):
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    (
                        "CMEMS refresh failed and "
                        "no usable cache metadata "
                        "was returned"
                    ),
            }

        processed = (
            PROCESSED_DIR
            / "ocean_combined_processed.nc"
        )

        inserted = (
            record_dataset_snapshot(
                provider=
                    "COPERNICUS_MARINE",

                dataset_type=
                    "OCEAN_CURRENT",

                local_path=
                    processed,

                dataset_id=
                    str(
                        metadata.get(
                            "dataset_id"
                        )
                        or ""
                    ),

                observed_at=
                    metadata.get(
                        "timestamp"
                    ),

                metadata=
                    metadata,
            )
            if processed.exists()
            else False
        )

        try:
            ds.close()

        except Exception:
            pass

        return {
            "ok":
                processed.exists(),

            "rows_written":
                1 if inserted else 0,

            "message":
                (
                    "CMEMS processed cache "
                    + (
                        "updated"
                        if processed.exists()
                        else "unavailable"
                    )
                ),
        }

    return _run_audited(
        "COPERNICUS_MARINE",
        "cmems_refresh",
        work,
    )


# ============================================================
# ERA5 / COPERNICUS CDS
# ============================================================

def cds_credentials_configured() -> bool:
    return bool(
        (
            os.getenv(
                "CDSAPI_KEY"
            )
            or ""
        ).strip()
        or (
            Path.home()
            / ".cdsapirc"
        ).exists()
    )


def sync_era5() -> dict:
    def work() -> dict:
        from src.data_ingestion.era5_loader import (
            download_era5_subset,
            process_era5,
        )

        if not cds_credentials_configured():
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    (
                        "CDS/ERA5 credentials "
                        "are not configured"
                    ),
            }

        raw_path = (
            download_era5_subset()
        )

        if not raw_path:
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    (
                        "ERA5 download did not "
                        "produce a file"
                    ),
            }

        processed = (
            process_era5(
                raw_path
            )
        )

        if not processed:
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    "ERA5 processing failed",
            }

        inserted = (
            record_dataset_snapshot(
                provider=
                    "COPERNICUS_CDS",

                dataset_type=
                    "ERA5_ATMOSPHERE",

                local_path=
                    processed,

                dataset_id=
                    "reanalysis-era5-single-levels",

                metadata={
                    "raw_path":
                        str(raw_path),
                },
            )
        )

        return {
            "ok":
                True,

            "rows_written":
                1 if inserted else 0,

            "message":
                (
                    f"ERA5 processed="
                    f"{Path(processed).name}; "
                    f"metadata_row="
                    f"{'created' if inserted else 'already_recorded'}"
                ),
        }

    return _run_audited(
        "COPERNICUS_CDS",
        "era5_refresh",
        work,
    )


# ============================================================
# NOAA NDBC
# ============================================================

def persist_ndbc_observations(
    payload: dict,
) -> int:
    rows_written = 0

    with SessionLocal() as db:
        for item in payload.get(
            "observations",
            [],
        ):
            station_id = str(
                item.get("station_id")
                or ""
            ).strip()

            observed_at = (
                _parse_datetime(
                    item.get(
                        "observed_at"
                    )
                )
            )

            if (
                not station_id
                or observed_at is None
            ):
                continue

            existing = db.scalar(
                select(
                    BuoyObservation
                ).where(
                    BuoyObservation.provider
                    == "NOAA_NDBC",

                    BuoyObservation.station_id
                    == station_id,

                    BuoyObservation.observed_at
                    == observed_at,
                )
            )

            if existing:
                continue

            db.add(
                BuoyObservation(
                    provider=
                        "NOAA_NDBC",

                    station_id=
                        station_id,

                    observed_at=
                        observed_at,

                    latitude=
                        float(
                            item["lat"]
                        ),

                    longitude=
                        float(
                            item["lon"]
                        ),

                    wind_direction_deg=
                        item.get(
                            "wind_direction_deg"
                        ),

                    wind_speed_mps=
                        item.get(
                            "wind_speed_mps"
                        ),

                    gust_mps=
                        item.get(
                            "gust_mps"
                        ),

                    wave_height_m=
                        item.get(
                            "wave_height_m"
                        ),

                    pressure_hpa=
                        item.get(
                            "pressure_hpa"
                        ),

                    air_temperature_c=
                        item.get(
                            "air_temperature_c"
                        ),

                    water_temperature_c=
                        item.get(
                            "water_temperature_c"
                        ),

                    raw_data=
                        item.get(
                            "raw"
                        )
                        or item,
                )
            )

            rows_written += 1

        db.commit()

    return rows_written


def sync_ndbc() -> dict:
    def work() -> dict:
        from src.data_providers.ndbc_provider import (
            fetch_latest_observations,
        )

        payload = (
            fetch_latest_observations(
                DATA_DIR
            )
        )

        rows = (
            persist_ndbc_observations(
                payload
            )
        )

        record_dataset_snapshot(
            provider=
                "NOAA_NDBC",

            dataset_type=
                "LATEST_OBSERVATIONS_TEXT",

            local_path=
                payload["raw_path"],

            dataset_id=
                "NDBC-latest_obs",

            observed_at=
                payload.get(
                    "retrieved_at"
                ),

            metadata={
                "source_url":
                    payload.get(
                        "source_url"
                    ),

                "filtered_count":
                    payload.get(
                        "count"
                    ),
            },
        )

        return {
            "ok":
                True,

            "rows_written":
                rows,

            "records_seen":
                int(
                    payload.get(
                        "count"
                    )
                    or 0
                ),

            "message":
                (
                    "NOAA NDBC Southern Ocean "
                    f"observations={payload.get('count', 0)}, "
                    f"new_database_rows={rows}"
                ),
        }

    return _run_audited(
        "NOAA_NDBC",
        "ndbc_refresh",
        work,
    )


def recent_buoy_observations(
    limit: int = 200,
) -> list[dict]:
    init_database()

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(
                    BuoyObservation
                )
                .order_by(
                    desc(
                        BuoyObservation.observed_at
                    )
                )
                .limit(
                    max(
                        1,
                        min(
                            limit,
                            1000,
                        ),
                    )
                )
            ).all()
        )

    return [
        {
            "station_id":
                row.station_id,

            "observed_at":
                row.observed_at.isoformat(),

            "lat":
                row.latitude,

            "lon":
                row.longitude,

            "wind_direction_deg":
                row.wind_direction_deg,

            "wind_speed_mps":
                row.wind_speed_mps,

            "gust_mps":
                row.gust_mps,

            "wave_height_m":
                row.wave_height_m,

            "pressure_hpa":
                row.pressure_hpa,

            "air_temperature_c":
                row.air_temperature_c,

            "water_temperature_c":
                row.water_temperature_c,

            "source":
                "NOAA NDBC",
        }

        for row in rows
    ]


# ============================================================
# SENTINEL-1 CATALOGUE
# ============================================================

def persist_satellite_scenes(
    payload: dict,
) -> int:
    rows_written = 0

    provider = (
        "COPERNICUS_DATA_SPACE"
    )

    collection = str(
        payload.get("collection")
        or "sentinel-1-grd"
    )

    with SessionLocal() as db:
        for feature in payload.get(
            "features",
            [],
        ):
            scene_id = str(
                feature.get("id")
                or ""
            ).strip()

            if not scene_id:
                continue

            existing = db.scalar(
                select(
                    SatelliteScene
                ).where(
                    SatelliteScene.provider
                    == provider,

                    SatelliteScene.scene_id
                    == scene_id,
                )
            )

            props = (
                feature.get("properties")
                or {}
            )

            values = dict(
                collection=
                    collection,

                observed_at=
                    _parse_datetime(
                        props.get(
                            "datetime"
                        )
                        or props.get(
                            "start_datetime"
                        )
                    ),

                bbox_json=
                    feature.get(
                        "bbox"
                    ),

                geometry_json=
                    feature.get(
                        "geometry"
                    ),

                metadata_json={
                    "properties":
                        props,

                    "assets":
                        feature.get(
                            "assets"
                        )
                        or {},

                    "links":
                        feature.get(
                            "links"
                        )
                        or [],

                    "data_semantics":
                        "CATALOGUE_METADATA_ONLY",
                },

                catalogue_url=
                    payload.get(
                        "catalogue_url"
                    ),

                retrieved_at=
                    _utc_now(),
            )

            if existing:
                for key, value in values.items():
                    setattr(
                        existing,
                        key,
                        value,
                    )

            else:
                db.add(
                    SatelliteScene(
                        provider=
                            provider,

                        scene_id=
                            scene_id,

                        **values,
                    )
                )

                rows_written += 1

        db.commit()

    return rows_written


def sync_sentinel1() -> dict:
    def work() -> dict:
        from src.data_providers.satellite_provider import (
            credentials_configured,
            fetch_recent_sentinel1,
        )

        if not credentials_configured():
            return {
                "ok":
                    False,

                "rows_written":
                    0,

                "message":
                    (
                        "Sentinel-1 OAuth client "
                        "ID/secret are not configured"
                    ),
            }

        payload = (
            fetch_recent_sentinel1(
                hours=int(
                    os.getenv(
                        "SENTINEL_LOOKBACK_HOURS",
                        "24",
                    )
                )
            )
        )

        rows = (
            persist_satellite_scenes(
                payload
            )
        )

        return {
            "ok":
                True,

            "rows_written":
                rows,

            "records_seen":
                int(
                    payload.get(
                        "count"
                    )
                    or 0
                ),

            "message":
                (
                    "Sentinel-1 catalogue "
                    f"scenes={payload.get('count', 0)}, "
                    f"new_database_rows={rows}; "
                    "metadata only, no SAR iceberg "
                    "analysis claimed"
                ),
        }

    return _run_audited(
        "COPERNICUS_DATA_SPACE",
        "sentinel1_catalog_refresh",
        work,
    )


def recent_satellite_scenes(
    limit: int = 100,
) -> list[dict]:
    init_database()

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(
                    SatelliteScene
                )
                .order_by(
                    desc(
                        SatelliteScene.observed_at
                    ),
                    desc(
                        SatelliteScene.retrieved_at
                    ),
                )
                .limit(
                    max(
                        1,
                        min(
                            limit,
                            500,
                        ),
                    )
                )
            ).all()
        )

    return [
        {
            "scene_id":
                row.scene_id,

            "collection":
                row.collection,

            "observed_at":
                (
                    row.observed_at.isoformat()
                    if row.observed_at
                    else None
                ),

            "bbox":
                row.bbox_json,

            "geometry":
                row.geometry_json,

            "metadata":
                row.metadata_json,

            "source":
                (
                    "Copernicus Data "
                    "Space Ecosystem"
                ),

            "data_semantics":
                "CATALOGUE_METADATA_ONLY",
        }

        for row in rows
    ]


# ============================================================
# SCHEDULER STATUS
# ============================================================

def scheduler_status(
    limit: int = 20,
) -> dict:
    init_database()

    with SessionLocal() as db:
        states = list(
            db.scalars(
                select(
                    SchedulerState
                ).order_by(
                    SchedulerState.job_name
                )
            ).all()
        )

        recent = list(
            db.scalars(
                select(
                    ProviderFetch
                )
                .order_by(
                    desc(
                        ProviderFetch.started_at
                    )
                )
                .limit(
                    limit
                )
            ).all()
        )

    return {
        "jobs": [
            {
                "job_name":
                    state.job_name,

                "provider":
                    state.provider,

                "last_started_at":
                    (
                        state.last_started_at.isoformat()
                        if state.last_started_at
                        else None
                    ),

                "last_finished_at":
                    (
                        state.last_finished_at.isoformat()
                        if state.last_finished_at
                        else None
                    ),

                "last_success_at":
                    (
                        state.last_success_at.isoformat()
                        if state.last_success_at
                        else None
                    ),

                "last_status":
                    state.last_status,

                "last_message":
                    state.last_message,
            }

            for state in states
        ],

        "recent_fetches": [
            {
                "provider":
                    row.provider,

                "job_name":
                    row.job_name,

                "started_at":
                    (
                        row.started_at.isoformat()
                        if row.started_at
                        else None
                    ),

                "finished_at":
                    (
                        row.finished_at.isoformat()
                        if row.finished_at
                        else None
                    ),

                "success":
                    row.success,

                "rows_written":
                    row.rows_written,

                "message":
                    row.message,
            }

            for row in recent
        ],
    }


# ============================================================
# DATABASE SUMMARY
# ============================================================

def database_summary() -> dict:
    init_database()

    with SessionLocal() as db:
        counts = {
            "iceberg_observations":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            IcebergObservation
                        )
                    )
                    or 0
                ),

            "vessel_positions":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            VesselPosition
                        )
                    )
                    or 0
                ),

            "dataset_snapshots":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            DatasetSnapshot
                        )
                    )
                    or 0
                ),

            "provider_fetches":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            ProviderFetch
                        )
                    )
                    or 0
                ),

            "buoy_observations":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            BuoyObservation
                        )
                    )
                    or 0
                ),

            "satellite_scenes":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            SatelliteScene
                        )
                    )
                    or 0
                ),
        }

        iceberg_source_counts = {
            "usnic_observation_rows":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            IcebergObservation
                        )
                        .where(
                            IcebergObservation.source
                            == "USNIC"
                        )
                    )
                    or 0
                ),

            "byu_current_observation_rows":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            IcebergObservation
                        )
                        .where(
                            IcebergObservation.source
                            == "BYU_SCP_CURRENT"
                        )
                    )
                    or 0
                ),

            "historical_observation_rows":
                int(
                    db.scalar(
                        select(func.count())
                        .select_from(
                            IcebergObservation
                        )
                        .where(
                            IcebergObservation.source
                            == "BYU_NIC_CONSOLIDATED"
                        )
                    )
                    or 0
                ),

            "unique_icebergs":
                int(
                    db.scalar(
                        select(
                            func.count(
                                func.distinct(
                                    IcebergObservation.iceberg_id
                                )
                            )
                        )
                    )
                    or 0
                ),
        }

        usnic_snapshot = (
            _latest_source_snapshot(
                db,
                "USNIC",
            )
        )

        byu_snapshot = (
            _latest_source_snapshot(
                db,
                "BYU_SCP_CURRENT",
            )
        )

        iceberg_source_counts[
            "current_usnic_designations"
        ] = len(
            usnic_snapshot[
                "iceberg_ids"
            ]
        )

        iceberg_source_counts[
            "current_byu_designations"
        ] = len(
            byu_snapshot[
                "iceberg_ids"
            ]
        )

        latest_iceberg = db.scalar(
            select(
                IcebergObservation
            )
            .order_by(
                desc(
                    IcebergObservation.retrieved_at
                )
            )
            .limit(1)
        )

        latest_vessel = db.scalar(
            select(
                VesselPosition
            )
            .order_by(
                desc(
                    VesselPosition.received_at
                )
            )
            .limit(1)
        )

        latest_dataset = db.scalar(
            select(
                DatasetSnapshot
            )
            .order_by(
                desc(
                    DatasetSnapshot.retrieved_at
                )
            )
            .limit(1)
        )

        latest_buoy = db.scalar(
            select(
                BuoyObservation
            )
            .order_by(
                desc(
                    BuoyObservation.observed_at
                )
            )
            .limit(1)
        )

        latest_scene = db.scalar(
            select(
                SatelliteScene
            )
            .order_by(
                desc(
                    SatelliteScene.observed_at
                ),
                desc(
                    SatelliteScene.retrieved_at
                ),
            )
            .limit(1)
        )

    return {
        "counts":
            counts,

        "iceberg_sources":
            iceberg_source_counts,

        "latest": {
            "iceberg_retrieved_at":
                (
                    latest_iceberg
                    .retrieved_at
                    .isoformat()
                    if (
                        latest_iceberg
                        and latest_iceberg.retrieved_at
                    )
                    else None
                ),

            "vessel_received_at":
                (
                    latest_vessel
                    .received_at
                    .isoformat()
                    if (
                        latest_vessel
                        and latest_vessel.received_at
                    )
                    else None
                ),

            "dataset_retrieved_at":
                (
                    latest_dataset
                    .retrieved_at
                    .isoformat()
                    if (
                        latest_dataset
                        and latest_dataset.retrieved_at
                    )
                    else None
                ),

            "buoy_observed_at":
                (
                    latest_buoy
                    .observed_at
                    .isoformat()
                    if (
                        latest_buoy
                        and latest_buoy.observed_at
                    )
                    else None
                ),

            "sentinel1_observed_at":
                (
                    latest_scene
                    .observed_at
                    .isoformat()
                    if (
                        latest_scene
                        and latest_scene.observed_at
                    )
                    else None
                ),
        },
    }