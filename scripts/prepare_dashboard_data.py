"""
Prepare data for the revised Global CDHW Migration Observatory.

Required raw files
------------------
raw_data/migration/
    Migration_TrackCount_1982.tif ... Migration_TrackCount_2019.tif

raw_data/events/
    tracks.geojson

raw_data/landuse/
    Cropland2000_5m.tif
    Pasture2000_5m.tif

Scientific handling
-------------------
- Event trajectories come from a public, minimized GeoJSON containing only
  each event's start year and its ordered centroid coordinates.
- 1982–2000 and 2001–2019 raster statistics use the ORIGINAL annual raster grid.
- Bilinear interpolation is used ONLY to make smoother web-display rasters.
- Cropland and pasture are NOT plotted as map overlays.
- Cropland/pasture are regridded to the native migration grid only for summary statistics.
- Population is not used.
"""

from __future__ import annotations

from pathlib import Path
import csv
import json
import re

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject


REPO_ROOT = Path(__file__).resolve().parents[1]

MIGRATION_DIR = REPO_ROOT / "raw_data" / "migration"
PUBLIC_TRACKS_FILE = REPO_ROOT / "raw_data" / "events" / "tracks.geojson"

LANDUSE_DIR = REPO_ROOT / "raw_data" / "landuse"
CROPLAND_TIF = LANDUSE_DIR / "Cropland2000_5m.tif"
PASTURE_TIF = LANDUSE_DIR / "Pasture2000_5m.tif"

OUTPUT_DIR = REPO_ROOT / "data"

EARLY_YEARS = range(1982, 2001)
RECENT_YEARS = range(2001, 2020)
ALL_YEARS = range(1982, 2020)

# Display only. Change to 0.125 for a smoother but larger web raster.
DISPLAY_RES_DEG = 0.25

# Leave None for automatic robust limits.
# Example:
# DENSITY_COLOR_MAX = 20
# CHANGE_COLOR_ABS_MAX = 15
DENSITY_COLOR_MAX = None
CHANGE_COLOR_ABS_MAX = None

NODATA = -9999.0


def normalize_position(position, feature_number):
    if not isinstance(position, list) or len(position) < 2:
        raise ValueError(
            f"Feature {feature_number} contains an invalid coordinate."
        )

    try:
        lon = float(position[0])
        lat = float(position[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Feature {feature_number} contains a nonnumeric coordinate."
        ) from exc

    if not np.isfinite(lon) or not np.isfinite(lat):
        raise ValueError(
            f"Feature {feature_number} contains a nonfinite coordinate."
        )

    if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
        raise ValueError(
            f"Feature {feature_number} contains a coordinate outside "
            "valid longitude/latitude bounds."
        )

    return [lon, lat]


def normalize_geometry(geometry, feature_number):
    if not isinstance(geometry, dict):
        raise ValueError(f"Feature {feature_number} has no valid geometry.")

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Point":
        normalized = normalize_position(coordinates, feature_number)
    elif geometry_type == "LineString":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError(
                f"Feature {feature_number} has an invalid LineString."
            )
        normalized = [
            normalize_position(position, feature_number)
            for position in coordinates
        ]
    elif geometry_type == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError(
                f"Feature {feature_number} has an invalid MultiLineString."
            )
        normalized = []
        for line in coordinates:
            if not isinstance(line, list) or len(line) < 2:
                raise ValueError(
                    f"Feature {feature_number} has an invalid line segment."
                )
            normalized.append([
                normalize_position(position, feature_number)
                for position in line
            ])
    else:
        raise ValueError(
            f"Feature {feature_number} uses unsupported geometry "
            f"{geometry_type!r}."
        )

    return {
        "type": geometry_type,
        "coordinates": normalized,
    }


def load_public_tracks():
    if not PUBLIC_TRACKS_FILE.exists():
        raise FileNotFoundError(
            f"Missing:\n{PUBLIC_TRACKS_FILE}\n\n"
            "Upload the minimized public tracks.geojson file to "
            "raw_data/events/."
        )

    with PUBLIC_TRACKS_FILE.open("r", encoding="utf-8") as f:
        source = json.load(f)

    if source.get("type") != "FeatureCollection":
        raise ValueError("tracks.geojson must be a GeoJSON FeatureCollection.")

    features = []
    start_years = []

    for feature_number, feature in enumerate(source.get("features", []), start=1):
        properties = feature.get("properties") or {}
        try:
            start_year = int(properties["start_year"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Feature {feature_number} has no valid start_year."
            ) from exc

        if start_year not in ALL_YEARS:
            raise ValueError(
                f"Feature {feature_number} has start_year {start_year}; "
                "expected 1982 through 2019."
            )

        features.append({
            "type": "Feature",
            "properties": {"start_year": start_year},
            "geometry": normalize_geometry(
                feature.get("geometry"),
                feature_number,
            ),
        })
        start_years.append(start_year)

    if not features:
        raise ValueError("tracks.geojson contains no track features.")

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    with (OUTPUT_DIR / "tracks.geojson").open("w", encoding="utf-8") as f:
        json.dump(geojson, f, separators=(",", ":"))

    annual = [
        {
            "year": year,
            "events": start_years.count(year),
        }
        for year in ALL_YEARS
    ]

    return {
        "early_count": sum(year <= 2000 for year in start_years),
        "recent_count": sum(year >= 2001 for year in start_years),
        "annual": annual,
    }


def find_migration_files():
    files = {}

    for p in MIGRATION_DIR.glob("Migration_TrackCount_*.tif"):
        m = re.search(r"(\d{4})$", p.stem)
        if m:
            files[int(m.group(1))] = p

    missing = [year for year in ALL_YEARS if year not in files]

    if missing:
        raise FileNotFoundError(
            "Missing annual migration rasters: "
            + ", ".join(map(str, missing))
        )

    return files


def read_raster(path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float64")
        profile = src.profile.copy()
        transform = src.transform
        crs = src.crs
        nodata = src.nodata

    valid = np.isfinite(arr)

    if nodata is not None and np.isfinite(nodata):
        valid &= arr != nodata

    arr = np.where(valid, arr, np.nan)

    return arr, profile, transform, crs


def check_same_grid(reference, current, year):
    rp, rt, rc = reference
    p, t, c = current

    if p["width"] != rp["width"] or p["height"] != rp["height"]:
        raise ValueError(f"Raster dimensions differ in {year}.")

    if t != rt:
        raise ValueError(f"Raster transform differs in {year}.")

    if c != rc:
        raise ValueError(f"Raster CRS differs in {year}.")


def stats(arr):
    vals = arr[np.isfinite(arr)]

    if vals.size == 0:
        return {
            "sum": 0.0,
            "mean": 0.0,
            "max": 0.0,
            "positive_cells": 0,
        }

    return {
        "sum": float(vals.sum()),
        "mean": float(vals.mean()),
        "max": float(vals.max()),
        "positive_cells": int((vals > 0).sum()),
    }


def build_period_rasters(files):
    early = []
    recent = []
    reference = None

    for year in ALL_YEARS:
        arr, profile, transform, crs = read_raster(files[year])

        if reference is None:
            reference = (profile, transform, crs)
        else:
            check_same_grid(
                reference,
                (profile, transform, crs),
                year,
            )

        if year <= 2000:
            early.append(arr)
        else:
            recent.append(arr)

    early_stack = np.stack(early)
    recent_stack = np.stack(recent)

    early_sum = np.nansum(early_stack, axis=0)
    recent_sum = np.nansum(recent_stack, axis=0)

    early_sum[np.all(~np.isfinite(early_stack), axis=0)] = np.nan
    recent_sum[np.all(~np.isfinite(recent_stack), axis=0)] = np.nan

    change = recent_sum - early_sum

    return {
        "early": early_sum,
        "recent": recent_sum,
        "change": change,
        "profile": reference[0],
        "transform": reference[1],
        "crs": reference[2],
    }


def display_grid():
    width = int(round(360.0 / DISPLAY_RES_DEG))
    height = int(round(180.0 / DISPLAY_RES_DEG))
    transform = from_origin(
        -180.0,
        90.0,
        DISPLAY_RES_DEG,
        DISPLAY_RES_DEG,
    )
    return transform, width, height


def reproject_for_display(src_array, src_transform, src_crs):
    dst_transform, width, height = display_grid()

    dst = np.full(
        (height, width),
        NODATA,
        dtype="float32",
    )

    src = np.where(
        np.isfinite(src_array),
        src_array,
        NODATA,
    ).astype("float32")

    reproject(
        source=src,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=NODATA,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        dst_nodata=NODATA,
        resampling=Resampling.bilinear,
    )

    dst = np.where(dst == NODATA, np.nan, dst)

    return dst, dst_transform


def write_display_tif(path, array, transform):
    arr = np.where(
        np.isfinite(array),
        array,
        NODATA,
    ).astype("float32")

    profile = {
        "driver": "GTiff",
        "height": arr.shape[0],
        "width": arr.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": NODATA,
        "compress": "DEFLATE",
        "predictor": 2,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)


def regrid_landuse_to_native(path, dst_shape, dst_transform, dst_crs):
    if not path.exists():
        raise FileNotFoundError(f"Missing land-use file:\n{path}")

    dst = np.full(
        dst_shape,
        NODATA,
        dtype="float32",
    )

    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=NODATA,
            resampling=Resampling.average,
        )

    return np.where(dst == NODATA, np.nan, dst).astype("float64")


def summarize_landuse(track, weights):
    valid = (
        np.isfinite(track)
        & np.isfinite(weights)
        & (weights > 0)
    )

    if not valid.any():
        return {
            "weighted_mean": 0.0,
            "overlap_pct": 0.0,
        }

    t = track[valid]
    w = weights[valid]

    denom = float(w.sum())

    weighted_mean = (
        float(np.sum(t * w) / denom)
        if denom > 0
        else 0.0
    )

    overlap_pct = (
        float(100.0 * w[t > 0].sum() / denom)
        if denom > 0
        else 0.0
    )

    return {
        "weighted_mean": weighted_mean,
        "overlap_pct": overlap_pct,
    }


def robust_limits(early, recent, change):
    positive = np.concatenate([
        early[np.isfinite(early) & (early > 0)],
        recent[np.isfinite(recent) & (recent > 0)],
    ])

    if DENSITY_COLOR_MAX is not None:
        density_max = float(DENSITY_COLOR_MAX)
    elif positive.size:
        density_max = float(np.nanpercentile(positive, 99))
    else:
        density_max = 1.0

    absolute_change = np.abs(change[np.isfinite(change)])

    if CHANGE_COLOR_ABS_MAX is not None:
        change_max = float(CHANGE_COLOR_ABS_MAX)
    elif absolute_change.size:
        change_max = float(np.nanpercentile(absolute_change, 99))
    else:
        change_max = 1.0

    return max(density_max, 1e-9), max(change_max, 1e-9)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("1/5 Reading minimized public tracks.geojson...")
    event_summary = load_public_tracks()

    print("2/5 Building native 1982-2000 and 2001-2019 migration rasters...")
    files = find_migration_files()
    native = build_period_rasters(files)

    print("3/5 Making smooth web-display rasters...")
    early_display, display_transform = reproject_for_display(
        native["early"],
        native["transform"],
        native["crs"],
    )
    recent_display, _ = reproject_for_display(
        native["recent"],
        native["transform"],
        native["crs"],
    )
    change_display, _ = reproject_for_display(
        native["change"],
        native["transform"],
        native["crs"],
    )

    write_display_tif(
        OUTPUT_DIR / "density_1982_2000_display.tif",
        early_display,
        display_transform,
    )
    write_display_tif(
        OUTPUT_DIR / "density_2001_2019_display.tif",
        recent_display,
        display_transform,
    )
    write_display_tif(
        OUTPUT_DIR / "change_2001_2019_minus_1982_2000_display.tif",
        change_display,
        display_transform,
    )

    print("4/5 Calculating cropland/pasture summaries...")
    crop = regrid_landuse_to_native(
        CROPLAND_TIF,
        native["early"].shape,
        native["transform"],
        native["crs"],
    )
    pasture = regrid_landuse_to_native(
        PASTURE_TIF,
        native["early"].shape,
        native["transform"],
        native["crs"],
    )

    crop_early = summarize_landuse(native["early"], crop)
    crop_recent = summarize_landuse(native["recent"], crop)

    pasture_early = summarize_landuse(native["early"], pasture)
    pasture_recent = summarize_landuse(native["recent"], pasture)

    density_max, change_max = robust_limits(
        native["early"],
        native["recent"],
        native["change"],
    )

    print("5/5 Writing summary.json...")
    summary = {
        "periods": {
            "early": "1982–2000",
            "recent": "2001–2019",
        },
        "events": event_summary,
        "native_stats": {
            "early": stats(native["early"]),
            "recent": stats(native["recent"]),
            "change": stats(native["change"]),
        },
        "landuse": {
            "cropland": {
                "early_weighted_mean": crop_early["weighted_mean"],
                "recent_weighted_mean": crop_recent["weighted_mean"],
                "early_overlap_pct": crop_early["overlap_pct"],
                "recent_overlap_pct": crop_recent["overlap_pct"],
            },
            "pasture": {
                "early_weighted_mean": pasture_early["weighted_mean"],
                "recent_weighted_mean": pasture_recent["weighted_mean"],
                "early_overlap_pct": pasture_early["overlap_pct"],
                "recent_overlap_pct": pasture_recent["overlap_pct"],
            },
        },
        "display": {
            "density_color_max": density_max,
            "change_color_abs_max": change_max,
            "display_resolution_deg": DISPLAY_RES_DEG,
            "interpolation": "bilinear display only",
        },
        "files": {
            "early_density": "data/density_1982_2000_display.tif",
            "recent_density": "data/density_2001_2019_display.tif",
            "change_density": "data/change_2001_2019_minus_1982_2000_display.tif",
            "tracks": "data/tracks.geojson",
        },
    }

    with (OUTPUT_DIR / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with (OUTPUT_DIR / "annual_event_counts.csv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=["year", "events"])
        writer.writeheader()
        writer.writerows(event_summary["annual"])

    print("\nDONE")
    print("Early events:", event_summary["early_count"])
    print("Recent events:", event_summary["recent_count"])
    print("Density color max:", density_max)
    print("Change color abs max:", change_max)


if __name__ == "__main__":
    main()
