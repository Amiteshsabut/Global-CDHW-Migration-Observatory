# Global Compound Drought–Heatwave Migration

An interactive web dashboard for exploring the spatial evolution of observed compound drought–heatwave (CDHW) migration events worldwide during 1982–2019.

The dashboard compares two equal observational periods, **1982–2000** and **2001–2019**, and provides interactive views of migration trajectories, migration-track density, and changes in spatial occurrence.

## Dashboard

The interactive interface provides three complementary views:

- **Tracks** — observed CDHW migration trajectories reconstructed from daily event locations.
- **Density** — cumulative migration-track occurrence during 1982–2000 and 2001–2019.
- **Change** — spatial difference in migration-track occurrence between the recent and early periods.

A draggable map divider enables direct comparison between the two observational periods.

## Trajectory Visualization

Migration trajectories are colored according to the start year of each event using eight temporal classes:

```text
1980–1985
1985–1990
1990–1995
1995–2000
2000–2005
2005–2010
2010–2015
2015–2020
```

Dateline-crossing trajectories are separated during preprocessing to prevent artificial lines across the global map.

## Public trajectory data

The public repository uses `raw_data/events/tracks.geojson`. Each GeoJSON
feature represents one event and contains only:

- `start_year`
- ordered centroid coordinates in a `LineString` or `MultiLineString`

Exact dates, event identifiers, duration, severity, and voxel attributes are
not published. The detailed Excel workbook should remain outside the public
repository.

To recreate the minimized file locally, run:

```bash
python scripts/create_public_tracks.py "path/to/Daily_Summary_CDHW_Events.xlsx"
```

This writes `raw_data/events/tracks.geojson`. The normal GitHub Actions build
then validates and copies that minimized file into the deployed dashboard.

## Spatial Visualization

All numerical calculations are performed using the original migration-track grid.

For web visualization, cumulative and change rasters are bilinearly resampled to a finer display grid to improve visual continuity:

```text
Native migration grid
        ↓
Bilinear resampling
        ↓
Web-display raster
```

The interpolation is applied only for visualization and does not modify the underlying migration-track statistics.
