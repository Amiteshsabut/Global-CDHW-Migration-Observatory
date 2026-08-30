"""Create a minimized public tracks GeoJSON from the private event workbook.

Run this script locally. Do not place the source Excel workbook in the public
repository. The output stores only each event's start year and its ordered
centroid coordinates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "raw_data" / "events" / "tracks.geojson"


def find_column(df, candidates):
    lookup = {str(column).strip().lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise KeyError(
        f"Could not find any of {candidates}. "
        f"Available columns: {list(df.columns)}"
    )


def split_dateline(coordinates):
    """Split a track at the dateline while preserving valid line segments."""
    if len(coordinates) < 2:
        return [coordinates]

    parts = [[coordinates[0]]]

    for current in coordinates[1:]:
        previous = parts[-1][-1]
        lon0, lat0 = previous
        lon1, lat1 = current
        delta = lon1 - lon0

        if delta > 180.0:
            unwrapped_lon1 = lon1 - 360.0
            fraction = (-180.0 - lon0) / (unwrapped_lon1 - lon0)
            crossing_lat = lat0 + fraction * (lat1 - lat0)
            parts[-1].append([-180.0, crossing_lat])
            parts.append([[180.0, crossing_lat], current])
        elif delta < -180.0:
            unwrapped_lon1 = lon1 + 360.0
            fraction = (180.0 - lon0) / (unwrapped_lon1 - lon0)
            crossing_lat = lat0 + fraction * (lat1 - lat0)
            parts[-1].append([180.0, crossing_lat])
            parts.append([[-180.0, crossing_lat], current])
        else:
            parts[-1].append(current)

    return parts


def build_public_tracks(input_path, output_path):
    df = pd.read_excel(input_path)

    date_column = find_column(df, ["Date"])
    event_column = find_column(
        df,
        ["Event ID", "Event_ID", "EventID", "event_id"],
    )
    lon_column = find_column(df, ["Longitude", "Lon"])
    lat_column = find_column(df, ["Latitude", "Lat"])

    events = df[[date_column, event_column, lon_column, lat_column]].copy()
    events.columns = ["date", "event_id", "lon", "lat"]
    events["date"] = pd.to_datetime(events["date"], errors="coerce")
    events["lon"] = pd.to_numeric(events["lon"], errors="coerce")
    events["lat"] = pd.to_numeric(events["lat"], errors="coerce")
    events = events.dropna(subset=["date", "event_id", "lon", "lat"])
    events["lon"] = ((events["lon"] + 180.0) % 360.0) - 180.0
    events = events[events["lat"].between(-90.0, 90.0)]

    features = []

    for _, event in events.groupby("event_id", sort=False):
        event = event.sort_values("date")
        coordinates = event[["lon", "lat"]].astype(float).values.tolist()
        start_year = int(event["date"].iloc[0].year)
        parts = split_dateline(coordinates)

        if len(coordinates) == 1:
            geometry = {
                "type": "Point",
                "coordinates": coordinates[0],
            }
        elif len(parts) == 1:
            geometry = {
                "type": "LineString",
                "coordinates": parts[0],
            }
        else:
            geometry = {
                "type": "MultiLineString",
                "coordinates": parts,
            }

        features.append({
            "type": "Feature",
            "properties": {"start_year": start_year},
            "geometry": geometry,
        })

    output = {
        "type": "FeatureCollection",
        "features": features,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"Created {len(features)} public tracks: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert a private CDHW event workbook to public tracks GeoJSON."
    )
    parser.add_argument("input_xlsx", type=Path, help="Private source Excel file")
    parser.add_argument(
        "output_geojson",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    build_public_tracks(args.input_xlsx, args.output_geojson)


if __name__ == "__main__":
    main()
