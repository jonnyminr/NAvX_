from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup


BYU_CURRENT_URL = "https://www.scp.byu.edu/current_icebergs.html"


@dataclass
class BYUCurrentIceberg:
    iceberg_id: str
    latitude: float
    longitude: float
    observed_at: datetime
    observed_day_of_year: int
    source: str
    raw_data: dict


def _coordinate_to_decimal(
    degrees: str,
    minutes: str,
    direction: str,
) -> float:
    value = float(degrees) + float(minutes) / 60.0

    if direction.upper() in {"S", "W"}:
        value = -value

    return value


def _extract_revision_date(text: str) -> datetime:
    match = re.search(
        r"Last\s+revised:\s*"
        r"(\d{1,2}:\d{2}:\d{2})\s+"
        r"(\d{1,2})/"
        r"(\d{1,2})/"
        r"(\d{2,4})",
        text,
        re.IGNORECASE,
    )

    if not match:
        return datetime.now(timezone.utc)

    clock = match.group(1)
    month = int(match.group(2))
    day = int(match.group(3))
    year = int(match.group(4))

    if year < 100:
        year += 2000

    parsed = datetime.strptime(
        f"{year:04d}-{month:02d}-{day:02d} {clock}",
        "%Y-%m-%d %H:%M:%S",
    )

    return parsed.replace(tzinfo=timezone.utc)


def _doy_to_datetime(
    doy: int,
    revision: datetime,
) -> datetime:
    year = revision.year

    revision_doy = int(
        revision.strftime("%j")
    )

    if doy > revision_doy + 30:
        year -= 1

    result = datetime.strptime(
        f"{year}-{int(doy):03d}",
        "%Y-%j",
    )

    return result.replace(
        tzinfo=timezone.utc
    )


def fetch_byu_current_icebergs(
    timeout_seconds: int = 45,
):
    headers = {
        "User-Agent":
            "ANTARCTIC-NAV-X/1.0 real-data-ingestion"
    }

    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = client.get(
            BYU_CURRENT_URL
        )

        response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    revision = _extract_revision_date(
        page_text
    )

    row_pattern = re.compile(
        r"^\s*"
        r"([A-Za-z0-9\-]+)"
        r"\s+"
        r"(\d{1,3})"
        r"\s+"
        r"(\d{1,2})"
        r"['’′]?"
        r"\s*"
        r"([EW])"
        r"\s+"
        r"(\d{1,2})"
        r"\s+"
        r"(\d{1,2})"
        r"['’′]?"
        r"\s*"
        r"([NS])"
        r"\s+"
        r"(\d{1,3})"
        r"\s*$",
        re.IGNORECASE,
    )

    results = []

    for tr in soup.find_all("tr"):
        text = " ".join(
            tr.stripped_strings
        )

        text = (
            text
            .replace("\xa0", " ")
            .replace("’", "'")
            .replace("′", "'")
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        match = row_pattern.match(text)

        if not match:
            continue

        iceberg_id = (
            match.group(1)
            .strip()
            .upper()
        )

        lon = _coordinate_to_decimal(
            match.group(2),
            match.group(3),
            match.group(4),
        )

        lat = _coordinate_to_decimal(
            match.group(5),
            match.group(6),
            match.group(7),
        )

        doy = int(
            match.group(8)
        )

        if not (
            -90 <= lat <= 0
            and
            -180 <= lon <= 180
        ):
            continue

        observed_at = _doy_to_datetime(
            doy,
            revision,
        )

        results.append(
            BYUCurrentIceberg(
                iceberg_id=iceberg_id,
                latitude=lat,
                longitude=lon,
                observed_at=observed_at,
                observed_day_of_year=doy,
                source="BYU_SCP_CURRENT",
                raw_data={
                    "source_url":
                        BYU_CURRENT_URL,
                    "sensor":
                        "ASCAT + OSCAT-2",
                    "page_last_revised":
                        revision.isoformat(),
                    "status":
                        "SUPPLEMENTAL_CURRENT",
                    "authoritative_current_source":
                        "USNIC",
                },
            )
        )

    return (
        results,
        {
            "source":
                "BYU_SCP_CURRENT",
            "source_url":
                BYU_CURRENT_URL,
            "page_last_revised":
                revision.isoformat(),
            "records":
                len(results),
            "role":
                "SUPPLEMENTAL_CURRENT",
            "authoritative_source":
                "USNIC",
        },
    )