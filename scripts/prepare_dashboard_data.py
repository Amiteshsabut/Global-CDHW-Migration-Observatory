"""
Prepare web-ready rasters for the Global CDHW Migration Observatory.

This script:
1) Reads annual Migration_TrackCount_YYYY.tif rasters for 1982-2019.
2) Builds two equal 19-year cumulative maps:
      1982-2000
      2001-2019
3) Builds a difference map: recent - early.
4) Creates lightweight web rasters for population, cropland, and pasture.
5) Writes summary.json and annual_summary.csv for the dashboard.

Edit only the PATHS section if your folders differ.

Recommended environment:
    conda create -n cdhw-dashboard python=3.11
    conda activate cdhw-dashboard
    pip install rasterio numpy pandas
"""

from __future__ import annotations

from pathlib import Path
import csv
import json
import math
import shutil
from typing import Dict, Tuple

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject


# ============================================================
# PATHS — repository-relative so GitHub Actions can run this
# ============================================================

REPO_ROOT = Path(__file__).resolve().parents[1]

MIGRATION_DIR = REPO_ROOT / "raw_data" / "migration"
POPULATION_DIR = REPO_ROOT / "raw_data" / "population"

CROPLAND_TIF = REPO_ROOT / "raw_data" / "landuse" / "Cropland2000_5m.tif"
PASTURE_TIF = REPO_ROOT / "raw_data" / "landuse" / "Pasture2000_5m.tif"

POPULATION_GLOB = "gpw_v4_population_count_rev11_2000*.tif"

OUTPUT_DIR = REPO_ROOT / "data"

# Context rasters are downsampled for fast GitHub Pages viewing.
# 0.25 degrees = ~25-30 km at the equator.
WEB_CONTEXT_RESOLUTION_DEG = 0.25

EARLY_YEARS = list(range(1982, 2001))
RECENT_YEARS = list(range(2001, 2020))
ALL_YEARS = EARLY_YEARS + RECENT_YEARS

NODATA = -9999.0


def ensure_inputs() -> Tuple[Dict[int, Path], Path]:
    if not MIGRATION_DIR.exists():
        raise FileNotFoundError(f"Migration folder not found:\n{MIGRATION_DIR}")

    migration_files: Dict[int, Path] = {}
    for path in MIGRATION_DIR.glob("Migration_TrackCount_*.tif"):
        try:
            year = int(path.stem.split("_")[-1])
        except ValueError:
            continue
        migration_files[year] = path

    missing = [y for y in ALL_YEARS if y not in migration_files]
    if missing:
        raise FileNotFoundError(
            "Missing annual migration rasters for years: " + ", ".join(map(str, missing))
        )

    pop_candidates = sorted(POPULATION_DIR.glob(POPULATION_GLOB))
    if not pop_candidates:
        raise FileNotFoundError(
            f"No population GeoTIFF matching {POPULATION_GLOB!r} found in:\n"
            f"{POPULATION_DIR}"
        )
    population_tif = pop_candidates[0]

    for p, label in [(CROPLAND_TIF, "Cropland"), (PASTURE_TIF, "Pasture")]:
        if not p.exists():
            raise FileNotFoundError(f"{label} GeoTIFF not found:\n{p}")

    return migration_files, population_tif


def read_single_band(path: Path):
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


def verify_grid(reference, other, year: int):
    ref_profile, ref_transform, ref_crs = reference
    profile, transform, crs = other

    keys = ("width", "height")
    for key in keys:
        if ref_profile[key] != profile[key]:
            raise ValueError(
                f"Grid mismatch in {year}: {key} "
                f"{profile[key]} != reference {ref_profile[key]}"
            )

    if transform != ref_transform:
        raise ValueError(f"Transform mismatch in annual migration raster {year}.")
    if crs != ref_crs:
        raise ValueError(f"CRS mismatch in annual migration raster {year}.")


def summarize_array(arr: np.ndarray):
    valid = np.isfinite(arr)
    vals = arr[valid]
    positive = vals[vals > 0]

    return {
        "sum": float(np.nansum(vals)) if vals.size else 0.0,
        "mean": float(np.nanmean(vals)) if vals.size else 0.0,
        "max": float(np.nanmax(vals)) if vals.size else 0.0,
        "positive_cells": int(positive.size),
        "valid_cells": int(vals.size),
    }


def write_float_geotiff(
    out_path: Path,
    array: np.ndarray,
    reference_profile: dict,
    transform,
    crs,
):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out = np.where(np.isfinite(array), array, NODATA).astype("float32")

    profile = reference_profile.copy()
    profile.update(
        driver="GTiff",
        dtype="float32",
        count=1,
        nodata=NODATA,
        compress="DEFLATE",
        predictor=2,
        BIGTIFF="IF_SAFER",
        transform=transform,
        crs=crs,
    )

    # Tiling is valuable for medium/large rasters but can be invalid for very
    # small grids. Only enable it when both dimensions are at least 256 px.
    if profile["width"] >= 256 and profile["height"] >= 256:
        profile.update(
            tiled=True,
            blockxsize=256,
            blockysize=256,
        )
    else:
        profile.pop("tiled", None)
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(out, 1)


def build_migration_products(migration_files: Dict[int, Path]):
    annual_rows = []
    early_stack = []
    recent_stack = []

    reference_profile = None
    reference_transform = None
    reference_crs = None

    for year in ALL_YEARS:
        path = migration_files[year]
        arr, profile, transform, crs = read_single_band(path)

        if reference_profile is None:
            reference_profile = profile
            reference_transform = transform
            reference_crs = crs
        else:
            verify_grid(
                (reference_profile, reference_transform, reference_crs),
                (profile, transform, crs),
                year,
            )

        stats = summarize_array(arr)
        annual_rows.append({"year": year, **stats})

        if year in EARLY_YEARS:
            early_stack.append(arr)
        else:
            recent_stack.append(arr)

    early = np.nansum(np.stack(early_stack, axis=0), axis=0)
    recent = np.nansum(np.stack(recent_stack, axis=0), axis=0)

    # Preserve pixels that are missing for every year within each period.
    early_all_missing = np.all(~np.isfinite(np.stack(early_stack, axis=0)), axis=0)
    recent_all_missing = np.all(~np.isfinite(np.stack(recent_stack, axis=0)), axis=0)
    early[early_all_missing] = np.nan
    recent[recent_all_missing] = np.nan

    change = recent - early

    early_file = OUTPUT_DIR / "migration_1982_2000.tif"
    recent_file = OUTPUT_DIR / "migration_2001_2019.tif"
    change_file = OUTPUT_DIR / "migration_change_recent_minus_early.tif"

    write_float_geotiff(
        early_file, early, reference_profile, reference_transform, reference_crs
    )
    write_float_geotiff(
        recent_file, recent, reference_profile, reference_transform, reference_crs
    )
    write_float_geotiff(
        change_file, change, reference_profile, reference_transform, reference_crs
    )

    early_stats = summarize_array(early)
    recent_stats = summarize_array(recent)
    change_stats = summarize_array(change)

    pooled = np.concatenate([
        early[np.isfinite(early) & (early > 0)].ravel(),
        recent[np.isfinite(recent) & (recent > 0)].ravel(),
    ])
    if pooled.size:
        migration_color_max = float(np.nanpercentile(pooled, 99))
        if migration_color_max <= 0:
            migration_color_max = float(np.nanmax(pooled))
    else:
        migration_color_max = 1.0

    abs_change = np.abs(change[np.isfinite(change)])
    if abs_change.size:
        change_color_abs_max = float(np.nanpercentile(abs_change, 99))
        if change_color_abs_max <= 0:
            change_color_abs_max = float(np.nanmax(abs_change))
    else:
        change_color_abs_max = 1.0

    return {
        "annual_rows": annual_rows,
        "early_stats": early_stats,
        "recent_stats": recent_stats,
        "change_stats": change_stats,
        "migration_color_max": migration_color_max,
        "change_color_abs_max": change_color_abs_max,
    }


def reproject_context(
    source_path: Path,
    output_path: Path,
    resampling: Resampling,
):
    """
    Reproject/downsample context raster to EPSG:4326 for fast browser rendering.

    Population uses Resampling.sum because values are counts.
    Cropland/pasture use Resampling.average because the 5 arc-minute maps are
    normally interpreted as fractional/continuous land-use surfaces.
    """
    with rasterio.open(source_path) as src:
        if src.crs is None:
            raise ValueError(f"Raster has no CRS: {source_path}")

        transform, width, height = calculate_default_transform(
            src.crs,
            "EPSG:4326",
            src.width,
            src.height,
            *src.bounds,
            resolution=WEB_CONTEXT_RESOLUTION_DEG,
        )

        dst_array = np.full((height, width), NODATA, dtype="float32")

        reproject(
            source=rasterio.band(src, 1),
            destination=dst_array,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            dst_nodata=NODATA,
            resampling=resampling,
        )

        profile = src.profile.copy()
        profile.update(
            width=width,
            height=height,
            transform=transform,
            crs="EPSG:4326",
            dtype="float32",
            count=1,
            nodata=NODATA,
        )

    array = np.where(dst_array == NODATA, np.nan, dst_array).astype("float64")
    write_float_geotiff(output_path, array, profile, transform, "EPSG:4326")

    valid = array[np.isfinite(array)]
    if valid.size:
        vmin = float(np.nanpercentile(valid, 1))
        vmax = float(np.nanpercentile(valid, 99))
    else:
        vmin, vmax = 0.0, 1.0

    return {
        "min": float(np.nanmin(valid)) if valid.size else 0.0,
        "max": float(np.nanmax(valid)) if valid.size else 0.0,
        "display_min": vmin,
        "display_max": vmax,
    }


def write_annual_csv(rows):
    out = OUTPUT_DIR / "annual_summary.csv"
    fieldnames = ["year", "sum", "mean", "max", "positive_cells", "valid_cells"]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def web_path(path: Path) -> str:
    # index.html is at repository root, so web files are referenced as data/...
    return "data/" + path.name


def main():
    print("=" * 72)
    print("Global CDHW Migration Observatory — data preparation")
    print("=" * 72)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    migration_files, population_tif = ensure_inputs()

    print(f"Migration rasters: {len(migration_files)} years")
    print(f"Population raster: {population_tif.name}")
    print(f"Cropland raster:   {CROPLAND_TIF.name}")
    print(f"Pasture raster:    {PASTURE_TIF.name}")

    print("\n[1/4] Building 1982-2000 and 2001-2019 migration products...")
    migration = build_migration_products(migration_files)

    print("[2/4] Preparing population context raster...")
    pop_out = OUTPUT_DIR / "population_2000_web.tif"
    pop_stats = reproject_context(
        population_tif, pop_out, Resampling.sum
    )

    print("[3/4] Preparing cropland and pasture context rasters...")
    crop_out = OUTPUT_DIR / "cropland_2000_web.tif"
    pasture_out = OUTPUT_DIR / "pasture_2000_web.tif"

    crop_stats = reproject_context(
        CROPLAND_TIF, crop_out, Resampling.average
    )
    pasture_stats = reproject_context(
        PASTURE_TIF, pasture_out, Resampling.average
    )

    print("[4/4] Writing summary.json and annual_summary.csv...")
    write_annual_csv(migration["annual_rows"])

    summary = {
        "project": {
            "title": "Global Compound Drought–Heatwave Migration Observatory",
            "observation_period": "1982–2019",
            "description": (
                "Observed cumulative migration-track counts compared across "
                "two equal 19-year windows."
            ),
        },
        "periods": {
            "early": {
                "label": "1982–2000",
                "years": EARLY_YEARS,
                "file": "data/migration_1982_2000.tif",
                "stats": migration["early_stats"],
            },
            "recent": {
                "label": "2001–2019",
                "years": RECENT_YEARS,
                "file": "data/migration_2001_2019.tif",
                "stats": migration["recent_stats"],
            },
        },
        "change": {
            "label": "2001–2019 minus 1982–2000",
            "file": "data/migration_change_recent_minus_early.tif",
            "stats": migration["change_stats"],
        },
        "display": {
            "migration_color_max": migration["migration_color_max"],
            "change_color_abs_max": migration["change_color_abs_max"],
        },
        "context": {
            "population": {
                "label": "Population count (2000)",
                "file": web_path(pop_out),
                "transform": "log1p",
                **pop_stats,
            },
            "cropland": {
                "label": "Cropland (2000)",
                "file": web_path(crop_out),
                "transform": "linear",
                **crop_stats,
            },
            "pasture": {
                "label": "Pasture (2000)",
                "file": web_path(pasture_out),
                "transform": "linear",
                **pasture_stats,
            },
        },
        "annual": migration["annual_rows"],
    }

    with (OUTPUT_DIR / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nDONE.")
    print(f"Dashboard data written to:\n{OUTPUT_DIR}")
    print("\nFiles created:")
    for p in sorted(OUTPUT_DIR.iterdir()):
        if p.is_file():
            print(f"  - {p.name} ({p.stat().st_size / 1024:.1f} KB)")

    print("\nNext:")
    print("  1) From the dashboard folder run: python -m http.server 8000")
    print("  2) Open: http://localhost:8000")
    print("  3) Commit this repository to GitHub and enable GitHub Pages.")


if __name__ == "__main__":
    main()
