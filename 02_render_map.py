"""
Oklahoma Topo Map — Step 2: Render
====================================
Reads the downloaded data and produces the map.

• config.PREVIEW = True   → fast PNG for style iteration  (~30 sec)
• config.PREVIEW = False  → full PDF + PNG for the print shop  (~10–20 min)

All visual tweaks (colors, line weights, font sizes, bounds, etc.) live in
config.py — no need to edit this file for style changes.

Usage:
    python 02_render_map.py
"""

import os
import sys
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from scipy.ndimage import gaussian_filter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch
import rasterio

from config import (
    BOUNDS, LAT_CENTER,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    PREVIEW, PREVIEW_DPI, PREVIEW_WIDTH, PRINT_DPI,
    DEM_RESOLUTION_M,
    CONTOUR_INTERVAL_M, INDEX_EVERY, CONTOUR_SMOOTH, CONTOUR_LABEL_FMT,
    PALETTE, LW, LW_PRINT,
    HS_AZIMUTH, HS_ALTITUDE, HS_VERT_EXAG, HS_ALPHA,
    FONT_FAMILY, FONT,
    MAP_TITLE, MAP_SUBTITLE, SHOW_TITLE, SHOW_LEGEND,
    SLICE_BOUNDS, SIMPLIFY_TOLERANCE_DEG,
    DEM_PATH, OSM_PATH, DATA_DIR, OUTPUT_DIR,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Utility ──────────────────────────────────────────────────────────────────
def step(msg):
    print(f"\n  ▸  {msg}")

def m_to_ft(m):
    return m * 3.28084

# ─── Figure size ──────────────────────────────────────────────────────────────
# In PREVIEW mode we render at a fraction of wall size so it's fast.
# In PRINT  mode we render at actual 9×8 ft which gives 16 200 × 14 400 px at 150 DPI.

WALL_W_IN = WALL_WIDTH_FEET  * 12   # 108 inches
WALL_H_IN = WALL_HEIGHT_FEET * 12   #  96 inches

# Slice mode: render a sub-region at full print specs as vector PDF.
SLICE_MODE = (PREVIEW and SLICE_BOUNDS is not None)

# Bounds actually rendered (slice or full)
BOUNDS_USE = SLICE_BOUNDS if SLICE_MODE else BOUNDS

# Print spec scale factor: FONT values in config are tuned for PREVIEW_WIDTH.
# Multiply by PRINT_SCALE to size them for the 108-inch print figure.
PRINT_SCALE = WALL_W_IN / PREVIEW_WIDTH   # ≈ 7.7

# Use true print specifications whenever we are NOT in legacy preview mode.
# Slice + final print both use LW_PRINT (in pixels-at-PRINT_DPI) and FONT × PRINT_SCALE.
USE_PRINT_SPECS = SLICE_MODE or (not PREVIEW)

if SLICE_MODE:
    # Figure dimensions = WALL × (slice fraction of full bounds).
    # This makes the PDF page 1:1 scale with the actual printed slice.
    full_dlon = BOUNDS['east'] - BOUNDS['west']
    full_dlat = BOUNDS['north'] - BOUNDS['south']
    slice_dlon = SLICE_BOUNDS['east'] - SLICE_BOUNDS['west']
    slice_dlat = SLICE_BOUNDS['north'] - SLICE_BOUNDS['south']
    fig_w = WALL_W_IN * (slice_dlon / full_dlon)
    fig_h = WALL_H_IN * (slice_dlat / full_dlat)
    dpi   = PRINT_DPI
elif PREVIEW:
    aspect_ratio = WALL_H_IN / WALL_W_IN      # ≈ 0.889
    fig_w = PREVIEW_WIDTH
    fig_h = fig_w * aspect_ratio
    dpi   = PREVIEW_DPI
else:
    fig_w = WALL_W_IN
    fig_h = WALL_H_IN
    dpi   = PRINT_DPI

SCALE = PRINT_SCALE if USE_PRINT_SPECS else 1.0

mode = 'SLICE' if SLICE_MODE else ('PREVIEW' if PREVIEW else 'PRINT')
step(f"Figure: {fig_w:.2f} × {fig_h:.2f} in @ {dpi} DPI  ({mode})")

# ─── Create figure ────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=PALETTE['paper'])

# Axes fill the figure (we handle margins manually via padding)
ax = fig.add_axes([0.03, 0.04, 0.94, 0.92])   # [left, bottom, width, height] in figure fractions
ax.set_facecolor(PALETTE['paper'])
ax.set_xlim(BOUNDS_USE['west'], BOUNDS_USE['east'])
ax.set_ylim(BOUNDS_USE['south'], BOUNDS_USE['north'])

# Correct aspect ratio so longitudes and latitudes map to true distances
# At lat θ:  1° lon ≈ cos(θ) × 1° lat  in physical distance
cos_lat = np.cos(np.radians(LAT_CENTER))
ax.set_aspect(1.0 / cos_lat)

ax.axis('off')

# ─── Scale helpers ────────────────────────────────────────────────────────────
# matplotlib line widths and font sizes are in "points" (1 pt = 1/72 inch).
# They are ABSOLUTE on output — a 1pt line is always 1/72" regardless of figure size.
# So for the large print figure we multiply config values by PRINT_SCALE (≈7.7)
# to keep lines and labels proportionally sized on the 9-foot wall.

def lw(key):
    """Return line weight in absolute points.

    Print specs (slice or full print): LW_PRINT in pixels at PRINT_DPI → pt.
    Legacy preview: LW (tuned for visibility on a 14" PNG preview).
    """
    if USE_PRINT_SPECS:
        return LW_PRINT[key] * 72.0 / PRINT_DPI
    return LW[key]

# bbox tuple for filtering OSM reads in slice mode (minx, miny, maxx, maxy)
READ_BBOX = (
    BOUNDS_USE['west'], BOUNDS_USE['south'],
    BOUNDS_USE['east'], BOUNDS_USE['north'],
) if SLICE_MODE else None

def fs(key):
    """Return font size in points, scaled for current figure size."""
    return FONT[key]['size'] * SCALE

# ═══════════════════════════════════════════════════════
#  1. DEM  →  hillshade
# ═══════════════════════════════════════════════════════
step("Loading DEM …")

if not os.path.exists(DEM_PATH):
    print(f"\n  ERROR: {DEM_PATH} not found.")
    print("  Run python 01_download_data.py first.")
    sys.exit(1)

import rioxarray  # noqa: E402

# DEM is downloaded in EPSG:5070 (NAD83 / Conus Albers, meters). Our axes are
# in EPSG:4326 (lat/lon degrees). Reproject so contour coordinates align with
# the axes — without this, every contour segment lands outside the visible
# axes box and is clipped to nothing.
dem_ds = rioxarray.open_rasterio(DEM_PATH).squeeze()
if str(dem_ds.rio.crs).upper() != 'EPSG:4326':
    dem_ds = dem_ds.rio.reproject('EPSG:4326')

# Clip to slice bounds in slice mode — keeps contour computation cheap and
# avoids the matplotlib path-clipping issue we hit with full-DEM contours.
if SLICE_MODE:
    dem_ds = dem_ds.rio.clip_box(
        minx=BOUNDS_USE['west'], miny=BOUNDS_USE['south'],
        maxx=BOUNDS_USE['east'], maxy=BOUNDS_USE['north'],
    )

dem    = dem_ds.values.astype(np.float32)
xform  = dem_ds.rio.transform()
nodata = dem_ds.rio.nodata
# Bounds in degrees
class _Bnd:
    pass
bnd = _Bnd()
bnd.left   = float(dem_ds.x.values.min())
bnd.right  = float(dem_ds.x.values.max())
bnd.top    = float(dem_ds.y.values.max())
bnd.bottom = float(dem_ds.y.values.min())

# Mask nodata
if nodata is not None:
    dem[dem == nodata] = np.nan
dem[dem < -500] = np.nan   # catch stray fill values

print(f"     DEM shape : {dem.shape[1]} × {dem.shape[0]} px (EPSG:4326)")
print(f"     Elevation : {np.nanmin(dem):.0f} – {np.nanmax(dem):.0f} m")

# Smooth for contouring (reduces pixel-grid staircasing in contour lines)
dem_smooth = gaussian_filter(np.where(np.isnan(dem), np.nanmean(dem), dem),
                             sigma=CONTOUR_SMOOTH)

# Coordinate grid (pixel centres → geographic coords)
h, w = dem.shape
X = np.linspace(bnd.left,   bnd.right,  w)
Y = np.linspace(bnd.top,    bnd.bottom, h)   # note: raster Y is top→bottom
Xg, Yg = np.meshgrid(X, Y)

step("Rendering hillshade …")

# Physical cell size in metres (for correct hillshade gradient)
cell_lon_deg = abs(xform[0])
cell_lat_deg = abs(xform[4])
dx = cell_lon_deg * 111_320 * cos_lat
dy = cell_lat_deg * 111_320

ls    = LightSource(azdeg=HS_AZIMUTH, altdeg=HS_ALTITUDE)
shade = ls.hillshade(dem_smooth, vert_exag=HS_VERT_EXAG, dx=dx, dy=dy)

# Warm-tinted hillshade: bright areas → paper color, shadow areas → warm brown
cmap_shade = LinearSegmentedColormap.from_list(
    'hs', [PALETTE['hillshade_dark'], PALETTE['paper']], N=256
)

ax.imshow(
    shade,
    cmap=cmap_shade,
    extent=[bnd.left, bnd.right, bnd.bottom, bnd.top],
    origin='upper',
    alpha=HS_ALPHA,
    zorder=1,
    interpolation='bilinear',
)

# ═══════════════════════════════════════════════════════
#  2. Contour lines
# ═══════════════════════════════════════════════════════
step("Generating contour lines …")

elev_min = np.nanmin(dem_smooth)
elev_max = np.nanmax(dem_smooth)

first = np.ceil(elev_min / CONTOUR_INTERVAL_M) * CONTOUR_INTERVAL_M
all_levels = np.arange(first, elev_max + CONTOUR_INTERVAL_M, CONTOUR_INTERVAL_M)

# Split into regular vs. index
reg_levels = [l for i, l in enumerate(all_levels) if (i % INDEX_EVERY) != 0]
idx_levels = [l for i, l in enumerate(all_levels) if (i % INDEX_EVERY) == 0]

print(f"     {len(all_levels)} levels total  ({len(idx_levels)} index contours)")

# Regular contours (thin, unlabelled)
ax.contour(
    Xg, Yg, dem_smooth,
    levels=reg_levels,
    colors=[PALETTE['contour']],
    linewidths=lw('contour'),
    zorder=2,
    alpha=0.5,
)

# Index contours (thicker, labelled)
cs_idx = ax.contour(
    Xg, Yg, dem_smooth,
    levels=idx_levels,
    colors=[PALETTE['index_contour']],
    linewidths=lw('index_contour'),
    zorder=3,
)

# Labels (elevation in feet or metres, user-controlled)
def fmt_elev(v):
    return f"{m_to_ft(v):.0f}" if CONTOUR_LABEL_FMT == 'ft' else f"{v:.0f}"

ax.clabel(
    cs_idx,
    inline=True,
    fontsize=fs('contour'),
    fmt=fmt_elev,
    inline_spacing=2,
    use_clabeltext=True,
    colors=PALETTE['index_contour'],
)

# ═══════════════════════════════════════════════════════
#  3. OSM vector layers
# ═══════════════════════════════════════════════════════
step("Loading OSM layers …")

if not os.path.exists(OSM_PATH):
    print(f"     WARNING: {OSM_PATH} not found — vector layers skipped.")
else:
    import geopandas as gpd
    try:
        import pyogrio
        available = [name for name, _ in pyogrio.list_layers(OSM_PATH)]
    except Exception:
        available = []
    print(f"     Available layers: {available}")

    # Parallel data prep: read each layer + apply Douglas-Peucker simplification
    # in worker threads. pyogrio reads and shapely simplify both release the GIL,
    # so threads scale across cores. Plotting must remain serial (matplotlib is
    # not thread-safe).
    LAYER_NAMES = ['water_bodies', 'waterways', 'roads', 'railways', 'places']

    def _load_and_simplify(name):
        if name not in available:
            return None
        gdf = gpd.read_file(OSM_PATH, layer=name, engine='pyogrio', bbox=READ_BBOX)
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(gdf):
            # Skip simplification on Point geometries (no-op but wastes cycles)
            if not (gdf.geometry.geom_type == 'Point').all():
                gdf.geometry = gdf.geometry.simplify(
                    SIMPLIFY_TOLERANCE_DEG, preserve_topology=True,
                )
        return gdf

    t_load = time.time()
    with ThreadPoolExecutor(max_workers=len(LAYER_NAMES)) as _ex:
        layers = dict(zip(LAYER_NAMES, _ex.map(_load_and_simplify, LAYER_NAMES)))
    print(f"     ✓  Loaded + simplified all layers in {time.time()-t_load:.1f}s")

    # ── Water bodies (polygons — rendered behind waterways) ──────────────────
    wb = layers['water_bodies']
    if wb is not None:
        wb.plot(ax=ax,
                color=PALETTE['water_fill'],
                edgecolor=PALETTE['water_line'],
                linewidth=lw('river_minor'),
                zorder=3, alpha=0.95)
        print(f"     ✓  Water bodies: {len(wb)}")

    # ── Waterways (lines) ────────────────────────────────────────────────────
    ww = layers['waterways']
    if ww is not None:
        is_river = ww.get('waterway', '').isin(['river', 'canal']) if 'waterway' in ww.columns \
                   else ww.index.isin([])

        major_ww = ww[is_river]
        minor_ww = ww[~is_river]

        if len(major_ww):
            major_ww.plot(ax=ax, color=PALETTE['water_line'],
                          linewidth=lw('river_major'), zorder=4)
        if len(minor_ww):
            minor_ww.plot(ax=ax, color=PALETTE['water_line'],
                          linewidth=lw('river_minor'), zorder=4, alpha=0.7)
        print(f"     ✓  Waterways: {len(ww)} ({len(major_ww)} major)")

    # ── Roads ─────────────────────────────────────────────────────────────────
    roads = layers['roads']
    if roads is not None:
        # Stacking order, bottom → top:
        #   topo (1-2) → water_bodies (3) → waterways (4) → minor (5)
        #   → major (6) → railway (7) → highway (8) → labels (11)
        road_hierarchy = [
            # (highway tag,    lw key,        color key,       zorder)
            ('motorway',       'highway',     'highway',       8),
            ('trunk',          'highway',     'highway',       8),
            ('primary',        'major_road',  'major_road',    6),
            ('secondary',      'major_road',  'major_road',    6),
            ('tertiary',       'minor_road',  'minor_road',    5),
            ('residential',    'minor_road',  'minor_road',    5),
            ('unclassified',   'minor_road',  'minor_road',    5),
        ]

        if 'highway' in roads.columns:
            for htype, lw_key, color_key, zord in road_hierarchy:
                mask = roads['highway'].astype(str).str.lower() == htype
                subset = roads[mask]
                if len(subset):
                    subset.plot(ax=ax,
                                color=PALETTE[color_key],
                                linewidth=lw(lw_key),
                                zorder=zord)
        else:
            roads.plot(ax=ax, color=PALETTE['minor_road'],
                       linewidth=lw('minor_road'), zorder=5)

        print(f"     ✓  Roads: {len(roads)}")

    # ── Railways ──────────────────────────────────────────────────────────────
    rail = layers['railways']
    if rail is not None:
        # Thin dashed line — classic rail symbol
        rail.plot(ax=ax, color=PALETTE['railroad'],
                  linewidth=lw('railroad') * 0.7, zorder=7,
                  linestyle=(0, (5, 4)))
        print(f"     ✓  Railways: {len(rail)}")

    # ── Places ────────────────────────────────────────────────────────────────
    places = layers['places']
    if places is not None:
        place_config = {
            'city':    FONT['city'],
            'town':    FONT['town'],
            'village': FONT['village'],
            'hamlet':  FONT['hamlet'],
        }

        if 'place' not in places.columns:
            places['place'] = 'town'

        for ptype, fspec in place_config.items():
            subset = places[places['place'] == ptype]
            if len(subset) == 0:
                continue

            # Label
            if 'name' in subset.columns:
                for _, row in subset.iterrows():
                    name = row.get('name')
                    if not name or (isinstance(name, float) and np.isnan(name)):
                        continue
                    # OSM multi-name convention: "Primary;Alternate" — keep primary only.
                    # Also drops trailing alt-script spellings (e.g. Osage) that the
                    # default font can't render.
                    name = str(name).split(';', 1)[0].strip()
                    ax.annotate(
                        name,
                        xy=(row.geometry.x, row.geometry.y),
                        xytext=(0, 2 * SCALE),
                        textcoords='offset points',
                        ha='center', va='bottom',
                        fontsize=fs(ptype if ptype in FONT else 'town'),
                        fontfamily=FONT_FAMILY,
                        fontweight=fspec['weight'],
                        fontstyle=fspec.get('style', 'normal'),
                        color=PALETTE['town_label'],
                        zorder=11,
                    )

        print(f"     ✓  Places: {len(places)}")

# ═══════════════════════════════════════════════════════
#  4. Neatline / border
# ═══════════════════════════════════════════════════════
step("Drawing border …")

# Double-line neatline (outer thick + inner thin)
for spine in ax.spines.values():
    spine.set_visible(False)

dlon = BOUNDS_USE['east'] - BOUNDS_USE['west']
dlat = BOUNDS_USE['north'] - BOUNDS_USE['south']

# Skip the neatline in slice mode — a slice should look like a section of the
# larger print, not a self-contained mini-map.
if not SLICE_MODE:
    outer = plt.Rectangle(
        (BOUNDS_USE['west'], BOUNDS_USE['south']), dlon, dlat,
        linewidth=lw('border'), edgecolor=PALETTE['border'],
        facecolor='none', transform=ax.transData, zorder=20,
    )
    ax.add_patch(outer)

# ── Lat/lon tick grid (subtle) ──────────────────────────────────────────────
for lon in np.arange(np.ceil(BOUNDS_USE['west']), BOUNDS_USE['east'] + 0.5, 0.5):
    ax.axvline(lon, color=PALETTE['grid'],
               linewidth=0.3 * SCALE, zorder=0, alpha=0.5)
for lat in np.arange(np.ceil(BOUNDS_USE['south']), BOUNDS_USE['north'] + 0.5, 0.5):
    ax.axhline(lat, color=PALETTE['grid'],
               linewidth=0.3 * SCALE, zorder=0, alpha=0.5)

# ═══════════════════════════════════════════════════════
#  5. Title block
# ═══════════════════════════════════════════════════════
if SHOW_TITLE:
    step("Adding title …")
    # Place title in bottom-left corner (matching reference map style)
    tx = BOUNDS['west'] + dlon * 0.02
    ty = BOUNDS['south'] + dlat * 0.06

    ax.text(tx, ty + dlat * 0.04,
            MAP_TITLE.upper(),
            fontsize=fs('title'), fontfamily=FONT_FAMILY,
            fontweight='bold', color=PALETTE['border'],
            transform=ax.transData, zorder=22,
            verticalalignment='bottom',
            path_effects=[pe.withStroke(linewidth=3, foreground=PALETTE['paper'])],
            )
    ax.text(tx, ty,
            MAP_SUBTITLE,
            fontsize=fs('subtitle'), fontfamily=FONT_FAMILY,
            fontstyle='italic', color=PALETTE['border'],
            transform=ax.transData, zorder=22,
            verticalalignment='top',
            path_effects=[pe.withStroke(linewidth=2, foreground=PALETTE['paper'])],
            )

# ═══════════════════════════════════════════════════════
#  6. Export
# ═══════════════════════════════════════════════════════
step("Exporting …")

# Always vector PDF; raster PNG is dropped (open the PDF to verify hair-thin
# line widths at true print scale).
if SLICE_MODE:
    out_pdf = os.path.join(OUTPUT_DIR, 'slice_preview.pdf')
    label = 'Slice preview'
elif PREVIEW:
    out_pdf = os.path.join(OUTPUT_DIR, 'map_preview.pdf')
    label = 'Full-bounds preview'
else:
    out_pdf = os.path.join(OUTPUT_DIR, 'map_PRINT.pdf')
    label = 'Print PDF'

fig.savefig(out_pdf, dpi=dpi, bbox_inches='tight',
            facecolor=PALETTE['paper'], format='pdf',
            metadata={'Creator': 'Stylized Map Generator'})
print(f"\n  ✓  {label} saved:  {out_pdf}")
print(f"     Page size: {fig_w:.2f} × {fig_h:.2f} in (1:1 with print at this slice / scale)\n")

plt.close(fig)
print("  Done.\n")
