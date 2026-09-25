"""Historical Antarctic iceberg-track ingestion.

Historical source:
    Brigham Young University / Scatterometer Climate Record Pathfinder
    consolidated NIC + scatterometer Antarctic iceberg database.

IMPORTANT:
Historical database positions are NOT treated as current hazards.
Current operational iceberg positions continue to come from USNIC.
"""

from __future__ import annotations

import csv
import io
import os
import re
import zipfile

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urljoin

import httpx


BYU_DATABASE_PAGE = "https://www.scp.byu.edu/iceberg/default.html"

# Only used if automatic discovery fails.
BYU_FALLBACK_ZIP = (
    "https://www.scp.byu.edu/iceberg/"
    "consolidated_database_v8.0.zip"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _float(value) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


def _date_from_yyyyddd(value: str | None) -> Optional[datetime]:
    """
    BYU historical database dates are normally YYYYDDD,
    for example 2026250.
    """

    text = str(value or "").strip()

    if not re.fullmatch(r"\d{7}", text):
        return None

    try:
        dt = datetime.strptime(text, "%Y%j")

        return dt.replace(
            tzinfo=timezone.utc,
            hour=12
        )

    except ValueError:
        return None


def _valid_lat_lon(
    lat: Optional[float],
    lon: Optional[float]
) -> bool:

    return (
        lat is not None
        and lon is not None
        and -90 <= lat <= -40
        and -180 <= lon <= 180
    )


@dataclass
class HistoricalIcebergRecord:

    iceberg_id: str

    observed_at: datetime

    latitude: float
    longitude: float

    sensor: str

    source_file: str

    raw_data: dict

    @property
    def observed_label(self) -> str:

        return self.observed_at.date().isoformat()


class BYUIcebergHistoryProvider:

    def __init__(self, data_root: Path):

        self.data_root = Path(data_root)

        self.archive_dir = (
            self.data_root
            / "raw"
            / "iceberg_history"
        )

        self.archive_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.zip_path = (
            self.archive_dir
            / "byu_nic_consolidated_latest.zip"
        )

        self.last_url_file = (
            self.archive_dir
            / "byu_nic_source_url.txt"
        )

    def discover_latest_zip_url(self) -> str:

        override = (
            os.getenv("BYU_ICEBERG_HISTORY_URL")
            or ""
        ).strip()

        if override:
            return override

        headers = {
            "User-Agent":
                "ANTARCTIC-NAV-X/3.0 "
                "(educational decision-support prototype)"
        }

        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers=headers
        ) as client:

            response = client.get(
                BYU_DATABASE_PAGE
            )

            response.raise_for_status()

            matches = re.findall(
                r'href=["\']([^"\']*'
                r'consolidated_database_v'
                r'[^"\']+\.zip)["\']',
                response.text,
                flags=re.IGNORECASE
            )

            if matches:

                return urljoin(
                    str(response.url),
                    matches[-1]
                )

        return BYU_FALLBACK_ZIP

    def download(
        self,
        force: bool = False
    ) -> dict:

        refresh_days = max(
            1,
            int(
                os.getenv(
                    "BYU_HISTORY_REFRESH_DAYS",
                    "7"
                )
            )
        )

        if (
            self.zip_path.exists()
            and not force
        ):

            modified = datetime.fromtimestamp(
                self.zip_path.stat().st_mtime,
                tz=timezone.utc
            )

            age = _utc_now() - modified

            if age < timedelta(
                days=refresh_days
            ):

                previous_url = (
                    self.last_url_file
                    .read_text(
                        encoding="utf-8"
                    )
                    .strip()
                    if self.last_url_file.exists()
                    else BYU_FALLBACK_ZIP
                )

                return {
                    "path": str(
                        self.zip_path
                    ),
                    "downloaded": False,
                    "url": previous_url,
                    "mode":
                        "LOCAL_RECENT_CACHE"
                }

        url = self.discover_latest_zip_url()

        headers = {
            "User-Agent":
                "ANTARCTIC-NAV-X/3.0 "
                "(educational decision-support prototype)"
        }

        with httpx.Client(
            timeout=120.0,
            follow_redirects=True,
            headers=headers
        ) as client:

            response = client.get(url)

            response.raise_for_status()

            raw = response.content

        # Verify we actually received a ZIP
        # containing CSV data.
        with zipfile.ZipFile(
            io.BytesIO(raw)
        ) as zf:

            csv_names = [
                name
                for name in zf.namelist()
                if name.lower().endswith(
                    ".csv"
                )
            ]

            if not csv_names:

                raise ValueError(
                    "Downloaded historical "
                    "iceberg archive contains "
                    "no CSV files"
                )

        temp_path = (
            self.zip_path
            .with_suffix(".tmp")
        )

        temp_path.write_bytes(raw)

        temp_path.replace(
            self.zip_path
        )

        self.last_url_file.write_text(
            url,
            encoding="utf-8"
        )

        return {
            "path": str(
                self.zip_path
            ),
            "downloaded": True,
            "url": url,
            "mode":
                "FRESH_DOWNLOAD"
        }

    @staticmethod
    def _select_position(
        row: dict
    ) -> tuple[
        Optional[float],
        Optional[float],
        Optional[str]
    ]:

        fields = {
            str(k).strip().lower(): v
            for k, v in row.items()
            if k is not None
        }

        prefixes = []

        for key in fields:

            if key.endswith("_1"):

                prefix = key[:-2]

                if (
                    prefix != "size"
                    and f"{prefix}_2"
                    in fields
                ):
                    prefixes.append(
                        prefix
                    )

        # NIC coordinate wins whenever
        # present.
        preferred = [
            "nic",
            "ascat",
            "ascatb",
            "ascatc",
            "oscat",
            "oscat2",
            "qscat",
            "ers",
            "nscat",
            "sass"
        ]

        ordered = []

        for prefix in (
            preferred
            + sorted(
                set(prefixes)
            )
        ):

            if (
                prefix in prefixes
                and prefix not in ordered
            ):
                ordered.append(
                    prefix
                )

        for prefix in ordered:

            lat = _float(
                fields.get(
                    f"{prefix}_1"
                )
            )

            lon = _float(
                fields.get(
                    f"{prefix}_2"
                )
            )

            if _valid_lat_lon(
                lat,
                lon
            ):

                return (
                    lat,
                    lon,
                    prefix.upper()
                )

        return None, None, None

    def iter_records(
        self,
        zip_path: str | Path | None = None
    ) -> Iterator[
        HistoricalIcebergRecord
    ]:

        path = Path(
            zip_path
            or self.zip_path
        )

        if not path.exists():

            raise FileNotFoundError(
                path
            )

        with zipfile.ZipFile(
            path
        ) as zf:

            for member in zf.namelist():

                if (
                    not member
                    .lower()
                    .endswith(".csv")
                    or member.endswith("/")
                ):
                    continue

                iceberg_id = (
                    Path(member)
                    .stem
                    .strip()
                    .upper()
                    .replace(
                        "_",
                        "-"
                    )
                )

                if not iceberg_id:
                    continue

                try:

                    with zf.open(
                        member
                    ) as raw_handle:

                        wrapper = (
                            io.TextIOWrapper(
                                raw_handle,
                                encoding="utf-8-sig",
                                errors="replace",
                                newline=""
                            )
                        )

                        for row in csv.DictReader(
                            wrapper
                        ):

                            normalized = {
                                str(k)
                                .strip()
                                .lower(): v
                                for k, v
                                in row.items()
                                if k is not None
                            }

                            observed_at = (
                                _date_from_yyyyddd(
                                    normalized.get(
                                        "date"
                                    )
                                )
                            )

                            if (
                                observed_at
                                is None
                            ):
                                continue

                            lat, lon, sensor = (
                                self._select_position(
                                    normalized
                                )
                            )

                            if (
                                not _valid_lat_lon(
                                    lat,
                                    lon
                                )
                                or not sensor
                            ):
                                continue

                            yield (
                                HistoricalIcebergRecord(
                                    iceberg_id=
                                        iceberg_id,

                                    observed_at=
                                        observed_at,

                                    latitude=
                                        float(lat),

                                    longitude=
                                        float(lon),

                                    sensor=
                                        sensor,

                                    source_file=
                                        member,

                                    raw_data={
                                        **normalized,

                                        "selected_sensor":
                                            sensor,

                                        "source_file":
                                            member,

                                        "dataset":
                                            "BYU/NIC Consolidated Antarctic Iceberg Database",

                                        "data_semantics":
                                            "PUBLISHED_HISTORICAL_TRACK_POSITION",

                                        "interpolation_note":
                                            "Historical research position. "
                                            "Current USNIC observations remain "
                                            "authoritative for current NAV-X hazards."
                                    }
                                )
                            )

                except (
                    OSError,
                    UnicodeError,
                    csv.Error
                ):
                    continue