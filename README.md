# Global Compound Drought–Heatwave Migration Observatory

An interactive web dashboard for exploring the spatial evolution of observed compound drought–heatwave (CDHW) migration events worldwide during 1982–2019.

The dashboard compares two equal observational periods, **1982–2000** and **2001–2019**, and provides interactive views of migration trajectories, migration-track density, and changes in spatial occurrence.

## Dashboard

The interactive interface provides three complementary views:

- **Tracks** — observed CDHW migration trajectories reconstructed from daily event locations.
- **Density** — cumulative migration-track occurrence during 1982–2000 and 2001–2019.
- **Change** — spatial difference in migration-track occurrence between the recent and early periods.

A draggable map divider enables direct comparison between the two observational periods.

## Data

The dashboard is based on observed CDHW event tracking for 1982–2019.

### Migration Trajectories

Daily event trajectories are derived from:

```text
Daily_Summary_CDHW_Events.xlsx
```

The trajectory dataset contains event-level daily spatial information, including:

```text
Event ID
Date
Latitude
Longitude
```

These daily coordinates are used to reconstruct individual CDHW migration paths.

### Migration-Track Rasters

Annual migration-track counts are stored as:

```text
Migration_TrackCount_1982.tif
Migration_TrackCount_1983.tif
...
Migration_TrackCount_2019.tif
```

The annual rasters are aggregated into two equal 19-year periods:

```text
Early period  = 1982–2000
Recent period = 2001–2019
```

The spatial change layer is calculated as:

```text
Change = (2001–2019) − (1982–2000)
```

Positive values indicate increased migration-track occurrence during the recent period, whereas negative values indicate decreased occurrence.

## Land-Use Context

Cropland and pasture data for 2000 are used to summarize migration-track occurrence over agricultural land:

```text
Cropland2000_5m.tif
Pasture2000_5m.tif
```

These datasets are used for summary statistics only and are not displayed as background map layers.

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

## Author

**Amitesh Sabut**  
Zachry Department of Civil and Environmental Engineering  
Texas A&M University
