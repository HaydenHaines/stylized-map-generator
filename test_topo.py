"""
test_topo.py — fast topo-only render
=====================================
Renders ONLY contour lines for the configured SLICE_BOUNDS (or full BOUNDS if
no slice is set). No OSM layers, no labels, no border. Fast — typically 5-10
seconds per run.

Use this to iterate on contour color, line weight, interval, smoothing
without paying the full render cost. Once the topo looks right, run the
regular pipeline (`python 02_render_map.py`) to layer it back in.

Output: output/topo_test.pdf
"""

import os
import sys
import numpy as np
import rioxarray
from scipy.ndimage import gaussian_filter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from config import (
    BOUNDS, LAT_CENTER,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    PRINT_DPI, PREVIEW_WIDTH,
    CONTOUR_INTERVAL_M, INDEX_EVERY, CONTOUR_SMOOTH, CONTOUR_LABEL_FMT,
    PALETTE, LW_PRINT,
    FONT_FAMILY, FONT,
    SLICE_BOUNDS,
    DEM_PATH, OUTPUT_DIR,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

WALL_W_IN   = WALL_WIDTH_FEET  * 12
WALL_H_IN   = WALL_HEIGHT_FEET * 12
PRINT_SCALE = WALL_W_IN / PREVIEW_WIDTH

USE_SLICE  = SLICE_BOUNDS is not None
BOUNDS_USE = SLICE_BOUNDS if USE_SLICE else BOUNDS

full_dlon  = BOUNDS['east']  - BOUNDS['west']
full_dlat  = BOUNDS['north'] - BOUNDS['south']
slice_dlon = BOUNDS_USE['east']  - BOUNDS_USE['west']
slice_dlat = BOUNDS_USE['north'] - BOUNDS_USE['south']
fig_w = WALL_W_IN * (slice_dlon / full_dlon)
fig_h = WALL_H_IN * (slice_dlat / full_dlat)

print(f"  ▸  Topo-only render")
print(f"     Bounds : ({BOUNDS_USE['west']:.3f}, {BOUNDS_USE['south']:.3f}) "
      f"to ({BOUNDS_USE['east']:.3f}, {BOUNDS_USE['north']:.3f})")
print(f"     Figure : {fig_w:.2f} × {fig_h:.2f} in @ {PRINT_DPI} DPI")

# ───────── DEM: load → reproject → clip ─────────
print("  ▸  Loading DEM …")
if not os.path.exists(DEM_PATH):
    sys.exit(f"  ERROR: {DEM_PATH} not found. Run 01_download_data.py first.")

dem_ds = rioxarray.open_rasterio(DEM_PATH).squeeze()
print(f"     Source CRS : {dem_ds.rio.crs}")
if str(dem_ds.rio.crs).upper() != 'EPSG:4326':
    print(f"     Reprojecting to EPSG:4326 …")
    dem_ds = dem_ds.rio.reproject('EPSG:4326')

if USE_SLICE:
    dem_ds = dem_ds.rio.clip_box(
        minx=BOUNDS_USE['west'],  miny=BOUNDS_USE['south'],
        maxx=BOUNDS_USE['east'],  maxy=BOUNDS_USE['north'],
    )

dem    = dem_ds.values.astype(np.float32)
nodata = dem_ds.rio.nodata
if nodata is not None:
    dem[dem == nodata] = np.nan
dem[dem < -500] = np.nan

print(f"     DEM shape : {dem.shape[1]} × {dem.shape[0]} px")
print(f"     Elevation : {np.nanmin(dem):.0f} – {np.nanmax(dem):.0f} m")

# Smooth for clean contouring
dem_smooth = gaussian_filter(
    np.where(np.isnan(dem), np.nanmean(dem), dem),
    sigma=CONTOUR_SMOOTH,
)

# Coord grid in degrees
bnd_left   = float(dem_ds.x.values.min())
bnd_right  = float(dem_ds.x.values.max())
bnd_top    = float(dem_ds.y.values.max())
bnd_bottom = float(dem_ds.y.values.min())
h, w = dem.shape
X = np.linspace(bnd_left,  bnd_right,  w)
Y = np.linspace(bnd_top,   bnd_bottom, h)
Xg, Yg = np.meshgrid(X, Y)

# Levels
elev_min = float(np.nanmin(dem_smooth))
elev_max = float(np.nanmax(dem_smooth))
first    = np.ceil(elev_min / CONTOUR_INTERVAL_M) * CONTOUR_INTERVAL_M
all_levels = np.arange(first, elev_max + CONTOUR_INTERVAL_M, CONTOUR_INTERVAL_M)
reg_levels = [l for i, l in enumerate(all_levels) if (i % INDEX_EVERY) != 0]
idx_levels = [l for i, l in enumerate(all_levels) if (i % INDEX_EVERY) == 0]
print(f"  ▸  Contours: {len(all_levels)} levels ({len(idx_levels)} index)")

# ───────── Render ─────────
fig = plt.figure(figsize=(fig_w, fig_h), dpi=PRINT_DPI, facecolor=PALETTE['paper'])
ax  = fig.add_axes([0.03, 0.04, 0.94, 0.92])
ax.set_facecolor(PALETTE['paper'])
ax.set_xlim(BOUNDS_USE['west'],  BOUNDS_USE['east'])
ax.set_ylim(BOUNDS_USE['south'], BOUNDS_USE['north'])
cos_lat = np.cos(np.radians(LAT_CENTER))
ax.set_aspect(1.0 / cos_lat)
ax.axis('off')

def lw_pt(key):
    return LW_PRINT[key] * 72.0 / PRINT_DPI

cs_reg = ax.contour(
    Xg, Yg, dem_smooth, levels=reg_levels,
    colors=[PALETTE['contour']],
    linewidths=lw_pt('contour'),
    alpha=0.5, zorder=2,
)
cs_idx = ax.contour(
    Xg, Yg, dem_smooth, levels=idx_levels,
    colors=[PALETTE['index_contour']],
    linewidths=lw_pt('index_contour'),
    zorder=3, alpha=0.75,
)
print(f"     regular segments: {sum(len(s) for s in cs_reg.allsegs):,}")
print(f"     index   segments: {sum(len(s) for s in cs_idx.allsegs):,}")

def fmt(v):
    return f"{v*3.28084:.0f}" if CONTOUR_LABEL_FMT == 'ft' else f"{v:.0f}"

ax.clabel(
    cs_idx, inline=True,
    fontsize=FONT['contour']['size'] * PRINT_SCALE,
    fmt=fmt, colors=PALETTE['index_contour'],
)

out = os.path.join(OUTPUT_DIR, 'topo_test.pdf')
fig.savefig(out, dpi=PRINT_DPI, bbox_inches='tight',
            facecolor=PALETTE['paper'], format='pdf')
plt.close(fig)
print(f"\n  ✓  Topo saved: {out}\n")
