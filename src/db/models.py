from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IcebergObservation(Base):
    __tablename__ = "iceberg_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iceberg_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    observed_label: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    length_nm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    width_nm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_sqkm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="USNIC")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("iceberg_id", "observed_label", "source", name="uq_iceberg_observation"),
    )


class VesselPosition(Base):
    __tablename__ = "vessel_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mmsi: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    sog_knots: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cog_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    imo: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    call_sign: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    freshness: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "mmsi", "received_at", name="uq_vessel_position"),
    )


class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "dataset_type", "checksum_sha256", name="uq_dataset_snapshot_checksum"),
    )


class ProviderFetch(Base):
    __tablename__ = "provider_fetches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    job_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SchedulerState(Base):
    __tablename__ = "scheduler_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    last_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEVER_RUN")
    last_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BuoyObservation(Base):
    __tablename__ = "buoy_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="NOAA_NDBC")
    station_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    wind_direction_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wind_speed_mps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gust_mps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wave_height_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pressure_hpa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    air_temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    water_temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "station_id", "observed_at", name="uq_buoy_observation"),
    )


class SatelliteScene(Base):
    __tablename__ = "satellite_scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="COPERNICUS_DATA_SPACE")
    collection: Mapped[str] = mapped_column(String(100), nullable=False, default="sentinel-1-grd")
    scene_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    bbox_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    geometry_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    catalogue_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("provider", "scene_id", name="uq_satellite_scene"),
    )
