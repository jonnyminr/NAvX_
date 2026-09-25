"""Real-data ocean/land and sea-ice surface checks for ANTARCTIC NAV-X.

The routing engine must never invent coastlines or infer land from hand-drawn
polygons. This module uses two datasets already shipped/ingested by the project:

* CMEMS surface currents: finite u/v cells are ocean; NaN cells are land/grounded
  shelf or otherwise non-ocean in the source grid.

* NSIDC/NOAA G02135 Antarctic sea-ice GeoTIFF: concentration values 0..1000 are
  ocean/ice pixels (scaled 0..100%), while the documented special-value range
  >= 2500 is non-concentration metadata such as coast/land/no-data.

The class is read-only and lazy. It does not synthesize missing data.

Named coastal/land reference locations may request a separate marine routing
anchor. The original reference coordinate is preserved. A routing anchor is
returned only when a nearby cell is independently validated by both CMEMS and
NSIDC.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np


class RealOceanSurface:
    """Fast in-memory navigation surface backed by genuine CMEMS + NSIDC data."""

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)

        self.cmems_file: Optional[Path] = None
        self.nsidc_file: Optional[Path] = None

        self._cmems_lat = None
        self._cmems_lon = None
        self._cmems_valid = None

        self._nsidc_array = None
        self._nsidc_transform = None
        self._nsidc_width = 0
        self._nsidc_height = 0
        self._to_nsidc = None

        self._load_cmems()
        self._load_nsidc()

    @property
    def available(self) -> bool:
        """True only when both genuine navigation datasets are available."""

        # Verified route generation requires both parts of the navigation
        # surface:
        #
        # 1. CMEMS must identify an ocean/current cell.
        # 2. NSIDC must provide a genuine concentration/ocean pixel.
        #
        # An OR fallback would silently treat missing environmental
        # information as if it were safe.
        return (
            self._cmems_valid is not None
            and self._nsidc_array is not None
        )

    @property
    def sources(self) -> list[str]:
        """Return the real scientific sources currently loaded."""

        out = []

        if self._cmems_valid is not None:
            out.append(
                "CMEMS surface-current ocean mask"
            )

        if self._nsidc_array is not None:
            out.append(
                "NSIDC/NOAA G02135 sea-ice grid"
            )

        return out

    def _load_cmems(self) -> None:
        """Load genuine CMEMS surface-current data."""

        candidates = [
            self.data_root
            / "raw"
            / "ocean_currents_offline.nc",

            self.data_root
            / "processed"
            / "ocean_combined_processed.nc",
        ]

        path = next(
            (
                p
                for p in candidates
                if p.exists()
            ),
            None,
        )

        if path is None:
            return

        try:
            import xarray as xr

            with xr.open_dataset(path) as ds:

                lat_name = (
                    "latitude"
                    if "latitude" in ds.coords
                    else "lat"
                )

                lon_name = (
                    "longitude"
                    if "longitude" in ds.coords
                    else "lon"
                )

                u_name = (
                    "uo"
                    if "uo" in ds.data_vars
                    else "ocean_u"
                )

                v_name = (
                    "vo"
                    if "vo" in ds.data_vars
                    else "ocean_v"
                )

                if (
                    lat_name not in ds.coords
                    or lon_name not in ds.coords
                    or u_name not in ds
                    or v_name not in ds
                ):
                    return

                lat = np.asarray(
                    ds[lat_name].values,
                    dtype=float,
                )

                lon = np.asarray(
                    ds[lon_name].values,
                    dtype=float,
                )

                u = np.asarray(
                    ds[u_name].values
                )

                v = np.asarray(
                    ds[v_name].values
                )

                while u.ndim > 2:
                    u = u[0]

                while v.ndim > 2:
                    v = v[0]

                if (
                    u.shape
                    != (len(lat), len(lon))
                    or
                    v.shape
                    != (len(lat), len(lon))
                ):
                    return

                self._cmems_lat = lat
                self._cmems_lon = lon

                self._cmems_valid = (
                    np.isfinite(u)
                    &
                    np.isfinite(v)
                )

                self.cmems_file = path

        except Exception:

            # Some lightweight deployments may have h5py available before
            # the optional NetCDF backend used by xarray.
            #
            # Read the exact same genuine CMEMS NetCDF4/HDF5 bytes directly
            # rather than dropping the source or substituting synthetic data.
            try:
                import h5py

                with h5py.File(
                    path,
                    "r",
                ) as h5:

                    lat_key = (
                        "latitude"
                        if "latitude" in h5
                        else "lat"
                    )

                    lon_key = (
                        "longitude"
                        if "longitude" in h5
                        else "lon"
                    )

                    u_key = (
                        "uo"
                        if "uo" in h5
                        else "ocean_u"
                    )

                    v_key = (
                        "vo"
                        if "vo" in h5
                        else "ocean_v"
                    )

                    if not all(
                        k in h5
                        for k in (
                            lat_key,
                            lon_key,
                            u_key,
                            v_key,
                        )
                    ):
                        raise KeyError(
                            "CMEMS coordinate/current variables are missing"
                        )

                    lat = np.asarray(
                        h5[lat_key][...],
                        dtype=float,
                    )

                    lon = np.asarray(
                        h5[lon_key][...],
                        dtype=float,
                    )

                    u_ds = h5[u_key]
                    v_ds = h5[v_key]

                    u = np.asarray(
                        u_ds[...],
                        dtype=float,
                    )

                    v = np.asarray(
                        v_ds[...],
                        dtype=float,
                    )

                    for arr, ds_var in (
                        (u, u_ds),
                        (v, v_ds),
                    ):

                        fill = ds_var.attrs.get(
                            "_FillValue"
                        )

                        if fill is not None:

                            fill_value = float(
                                np.asarray(
                                    fill
                                ).reshape(-1)[0]
                            )

                            arr[
                                arr == fill_value
                            ] = np.nan

                    while u.ndim > 2:
                        u = u[0]

                    while v.ndim > 2:
                        v = v[0]

                    if (
                        u.shape
                        != (len(lat), len(lon))
                        or
                        v.shape
                        != (len(lat), len(lon))
                    ):
                        raise ValueError(
                            "CMEMS current grid shape "
                            "does not match coordinates"
                        )

                    self._cmems_lat = lat
                    self._cmems_lon = lon

                    self._cmems_valid = (
                        np.isfinite(u)
                        &
                        np.isfinite(v)
                    )

                    self.cmems_file = path

            except Exception:

                # Fail closed. Do not fabricate an ocean surface.
                self._cmems_lat = None
                self._cmems_lon = None
                self._cmems_valid = None

    def _load_nsidc(self) -> None:
        """Load the newest genuine NSIDC Antarctic concentration grid."""

        candidates = sorted(
            (
                self.data_root
                / "raw"
            ).glob(
                "S_*_concentration_v4.0.tif"
            ),
            reverse=True,
        )

        if not candidates:

            candidates = sorted(
                (
                    self.data_root
                    / "raw"
                ).glob(
                    "S_*concentration*.tif"
                ),
                reverse=True,
            )

        if not candidates:
            return

        path = candidates[0]

        try:
            import rasterio
            from pyproj import Transformer

            with rasterio.open(path) as src:

                self._nsidc_array = (
                    src.read(1)
                )

                self._nsidc_transform = (
                    src.transform
                )

                self._nsidc_width = (
                    src.width
                )

                self._nsidc_height = (
                    src.height
                )

                self._to_nsidc = (
                    Transformer.from_crs(
                        "EPSG:4326",
                        src.crs,
                        always_xy=True,
                    )
                )

                self.nsidc_file = path

        except Exception:

            self._nsidc_array = None
            self._nsidc_transform = None
            self._nsidc_width = 0
            self._nsidc_height = 0
            self._to_nsidc = None

    @staticmethod
    def _norm_lon(
        lon: float
    ) -> float:
        """Normalize longitude into [-180, 180]."""

        x = float(lon)

        while x > 180:
            x -= 360

        while x < -180:
            x += 360

        return x

    @staticmethod
    def _nearest_index(
        values: np.ndarray,
        target: float,
    ) -> int:
        """Return nearest index in an ascending coordinate array."""

        idx = int(
            np.searchsorted(
                values,
                target,
            )
        )

        if idx <= 0:
            return 0

        if idx >= len(values):
            return len(values) - 1

        return (
            idx
            if abs(
                values[idx]
                - target
            )
            <
            abs(
                values[idx - 1]
                - target
            )
            else idx - 1
        )

    @staticmethod
    def _haversine_km(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Great-circle distance in kilometres."""

        earth_radius_km = 6371.0088

        phi1 = math.radians(
            float(lat1)
        )

        phi2 = math.radians(
            float(lat2)
        )

        dphi = math.radians(
            float(lat2)
            - float(lat1)
        )

        dlon_deg = (
            (
                float(lon2)
                - float(lon1)
                + 180.0
            )
            % 360.0
        ) - 180.0

        dlambda = math.radians(
            dlon_deg
        )

        a = (
            math.sin(
                dphi / 2.0
            ) ** 2
            +
            math.cos(phi1)
            * math.cos(phi2)
            * math.sin(
                dlambda / 2.0
            ) ** 2
        )

        return (
            2.0
            * earth_radius_km
            * math.asin(
                min(
                    1.0,
                    math.sqrt(a),
                )
            )
        )

    def _cmems_ocean(
        self,
        lat: float,
        lon: float,
    ) -> Optional[bool]:
        """Check whether the nearest genuine CMEMS grid cell is ocean."""

        if self._cmems_valid is None:
            return None

        if (
            lat
            < float(
                self._cmems_lat.min()
            )
            or
            lat
            > float(
                self._cmems_lat.max()
            )
        ):
            return None

        lon = self._norm_lon(
            lon
        )

        if (
            lon
            < float(
                self._cmems_lon.min()
            )
            or
            lon
            > float(
                self._cmems_lon.max()
            )
        ):
            return None

        iy = self._nearest_index(
            self._cmems_lat,
            lat,
        )

        ix = self._nearest_index(
            self._cmems_lon,
            lon,
        )

        return bool(
            self._cmems_valid[
                iy,
                ix,
            ]
        )

    def _nsidc_value(
        self,
        lat: float,
        lon: float,
    ) -> Optional[int]:
        """Read the genuine NSIDC grid value at the supplied WGS84 point."""

        if (
            self._nsidc_array is None
            or
            self._to_nsidc is None
        ):
            return None

        try:
            x, y = (
                self._to_nsidc.transform(
                    self._norm_lon(
                        lon
                    ),
                    float(lat),
                )
            )

            from rasterio.transform import (
                rowcol,
            )

            row, col = rowcol(
                self._nsidc_transform,
                x,
                y,
                op=math.floor,
            )

            row = int(row)
            col = int(col)

            if not (
                0
                <= row
                < self._nsidc_height
                and
                0
                <= col
                < self._nsidc_width
            ):
                return None

            return int(
                self._nsidc_array[
                    row,
                    col,
                ]
            )

        except Exception:
            return None

    def is_navigable(
        self,
        lat: float,
        lon: float,
    ) -> bool:
        """Return True only when both real sources validate the point.

        A valid marine routing cell must have:

        * a finite CMEMS current cell; and
        * a genuine NSIDC concentration pixel from 0..1000.

        Land/coast/special NSIDC values, CMEMS NaNs, and missing/no-data
        combinations are rejected.

        This deliberately fails closed instead of assuming missing data means
        zero sea ice or navigable water.
        """

        try:
            lat = float(lat)
            lon = float(lon)

        except (
            TypeError,
            ValueError,
        ):
            return False

        if not (
            -90.0
            <= lat
            <= -45.0
            and
            -180.0
            <= lon
            <= 180.0
        ):
            return False

        if not self.available:
            return False

        val = self._nsidc_value(
            lat,
            lon,
        )

        cmems = self._cmems_ocean(
            lat,
            lon,
        )

        return bool(
            cmems is True
            and
            val is not None
            and
            0 <= val <= 1000
        )

    def nearest_navigable_point(
        self,
        lat: float,
        lon: float,
        max_radius_km: float = 150.0,
    ) -> Optional[dict]:
        """Return the nearest verified marine routing cell.

        This function is intended for named Antarctic stations/reference
        locations whose published coordinate may lie on land or immediately
        inland from the coast.

        IMPORTANT:
        The supplied/reference coordinate is never changed or reclassified.
        Instead, this returns a separate marine routing anchor.

        A candidate is accepted only when:

        * the CMEMS surface-current cell contains finite u/v data;
        * the NSIDC pixel contains a genuine concentration value 0..1000;
        * the candidate lies within max_radius_km.

        No synthetic coastline, interpolated water cell, or hand-written
        fallback is used.
        """

        try:
            lat = float(lat)

            lon = self._norm_lon(
                float(lon)
            )

            max_radius_km = float(
                max_radius_km
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if max_radius_km <= 0:
            return None

        if not (
            -90.0
            <= lat
            <= -45.0
            and
            -180.0
            <= lon
            <= 180.0
        ):
            return None

        if not self.available:
            return None

        # If the published/reference coordinate is already validated marine
        # water, it can be used directly.
        if self.is_navigable(
            lat,
            lon,
        ):

            concentration = (
                self.sea_ice_concentration_percent(
                    lat,
                    lon,
                )
            )

            return {
                "lat":
                    lat,

                "lon":
                    lon,

                "distance_km":
                    0.0,

                "sea_ice_concentration_percent":
                    concentration,

                "source":
                    "CMEMS + NSIDC RealOceanSurface",

                "cmems_source_file":
                    (
                        str(
                            self.cmems_file
                        )
                        if self.cmems_file
                        else None
                    ),

                "nsidc_source_file":
                    (
                        str(
                            self.nsidc_file
                        )
                        if self.nsidc_file
                        else None
                    ),
            }

        cmems_lat = np.asarray(
            self._cmems_lat,
            dtype=float,
        )

        cmems_lon = np.asarray(
            self._cmems_lon,
            dtype=float,
        )

        valid_mask = np.asarray(
            self._cmems_valid,
            dtype=bool,
        )

        if (
            cmems_lat.ndim != 1
            or cmems_lon.ndim != 1
            or valid_mask.ndim != 2
        ):
            return None

        # Approximate coordinate bounds used only to reduce the search region.
        # Final acceptance is based on true great-circle distance.
        latitude_radius = (
            max_radius_km
            / 111.0
        ) + 0.25

        cos_lat = abs(
            math.cos(
                math.radians(
                    lat
                )
            )
        )

        cos_lat = max(
            cos_lat,
            0.03,
        )

        longitude_radius = min(
            180.0,
            (
                max_radius_km
                /
                (
                    111.0
                    * cos_lat
                )
            )
            + 0.5,
        )

        lat_indices = np.where(
            np.abs(
                cmems_lat
                - lat
            )
            <= latitude_radius
        )[0]

        if len(lat_indices) == 0:
            return None

        # Use wrapped angular longitude difference so the search works around
        # ±180 degrees as well.
        longitude_delta = (
            (
                cmems_lon
                - lon
                + 180.0
            )
            % 360.0
        ) - 180.0

        lon_indices = np.where(
            np.abs(
                longitude_delta
            )
            <= longitude_radius
        )[0]

        if len(lon_indices) == 0:
            return None

        candidate_rows = []

        for iy in lat_indices:

            valid_lon_indices = (
                lon_indices[
                    valid_mask[
                        iy,
                        lon_indices,
                    ]
                ]
            )

            if len(
                valid_lon_indices
            ) == 0:
                continue

            candidate_lat = float(
                cmems_lat[iy]
            )

            for ix in valid_lon_indices:

                candidate_lon = (
                    self._norm_lon(
                        float(
                            cmems_lon[ix]
                        )
                    )
                )

                distance_km = (
                    self._haversine_km(
                        lat,
                        lon,
                        candidate_lat,
                        candidate_lon,
                    )
                )

                if (
                    distance_km
                    <= max_radius_km
                ):

                    candidate_rows.append(
                        (
                            distance_km,
                            candidate_lat,
                            candidate_lon,
                        )
                    )

        if not candidate_rows:
            return None

        # Closest genuine CMEMS ocean cells first.
        candidate_rows.sort(
            key=lambda item:
                item[0]
        )

        # A finite CMEMS cell alone is not enough.
        # Confirm every candidate against the genuine NSIDC grid as well.
        for (
            distance_km,
            candidate_lat,
            candidate_lon,
        ) in candidate_rows:

            nsidc_value = (
                self._nsidc_value(
                    candidate_lat,
                    candidate_lon,
                )
            )

            if (
                nsidc_value is None
                or
                not (
                    0
                    <= nsidc_value
                    <= 1000
                )
            ):
                continue

            # Final defensive confirmation through the same routing predicate
            # used elsewhere in NAV-X.
            if not self.is_navigable(
                candidate_lat,
                candidate_lon,
            ):
                continue

            concentration = (
                max(
                    0.0,
                    min(
                        100.0,
                        float(
                            nsidc_value
                        )
                        / 10.0,
                    ),
                )
            )

            return {
                "lat":
                    float(
                        candidate_lat
                    ),

                "lon":
                    float(
                        candidate_lon
                    ),

                "distance_km":
                    round(
                        float(
                            distance_km
                        ),
                        2,
                    ),

                "sea_ice_concentration_percent":
                    round(
                        concentration,
                        1,
                    ),

                "source":
                    "CMEMS + NSIDC RealOceanSurface",

                "cmems_source_file":
                    (
                        str(
                            self.cmems_file
                        )
                        if self.cmems_file
                        else None
                    ),

                "nsidc_source_file":
                    (
                        str(
                            self.nsidc_file
                        )
                        if self.nsidc_file
                        else None
                    ),
            }

        # No candidate passed both genuine datasets.
        return None

    def sea_ice_concentration_percent(
        self,
        lat: float,
        lon: float,
    ) -> Optional[float]:
        """Return genuine NSIDC concentration percent, or None when unavailable."""

        val = self._nsidc_value(
            float(lat),
            float(lon),
        )

        if (
            val is None
            or
            not (
                0
                <= val
                <= 1000
            )
        ):
            return None

        return max(
            0.0,
            min(
                100.0,
                val / 10.0,
            ),
        )

    def describe_point(
        self,
        lat: float,
        lon: float,
    ) -> dict:
        """Describe source-backed navigability for one coordinate."""

        cmems = self._cmems_ocean(
            float(lat),
            float(lon),
        )

        nsidc = self._nsidc_value(
            float(lat),
            float(lon),
        )

        concentration = (
            None
            if (
                nsidc is None
                or nsidc > 1000
            )
            else nsidc / 10.0
        )

        return {
            "navigable":
                self.is_navigable(
                    lat,
                    lon,
                ),

            "cmems_ocean_cell":
                cmems,

            "nsidc_raw_value":
                nsidc,

            "sea_ice_concentration_percent":
                concentration,

            "sources":
                self.sources,

            "cmems_source_file":
                (
                    str(
                        self.cmems_file
                    )
                    if self.cmems_file
                    else None
                ),

            "nsidc_source_file":
                (
                    str(
                        self.nsidc_file
                    )
                    if self.nsidc_file
                    else None
                ),
        }