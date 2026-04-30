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
import threading
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from scipy.ndimage import gaussian_filter

try:
    import psutil as _psutil
    _peak_rss_mb: list[float] = [0.0]
    _mem_stop = threading.Event()
    _total_ram_mb = _psutil.virtual_memory().total / 1024 ** 2

    def _memory_monitor() -> None:
        proc = _psutil.Process()
        _bail_thresh_mb = _total_ram_mb * 0.90
        while not _mem_stop.wait(5):
            rss = proc.memory_info().rss / 1024 ** 2
            if rss > _peak_rss_mb[0]:
                _peak_rss_mb[0] = rss
            if rss > _bail_thresh_mb:
                print(
                    f"\n  ✘  OOM BAIL: RSS {rss:.0f} MB exceeded 90% of system RAM "
                    f"({_total_ram_mb:.0f} MB). Stopping to prevent swap thrashing.\n"
                    "     Re-run with a smaller region (SLICE_BOUNDS) or on a machine with more RAM.",
                    flush=True,
                )
                import os as _os
                _os._exit(1)

    _mem_thread = threading.Thread(target=_memory_monitor, daemon=True)
    _mem_thread.start()
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False
    _total_ram_mb = None

# Force line-buffered stdout so progress messages stream in real time even
# when output is captured to a file (otherwise Python block-buffers and
# nothing appears until process exit).
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass  # older Python

import argparse as _argparse
import importlib.util as _imputil

# ── Config loading (--config pre-parsed before any config values are read) ────
def _load_config_module(path):
    spec = _imputil.spec_from_file_location('_map_config', os.path.abspath(path))
    mod = _imputil.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_pre = _argparse.ArgumentParser(add_help=False)
_pre.add_argument('--config', metavar='FILE')
_pre_args, _ = _pre.parse_known_args()

if _pre_args.config:
    _cfg = _load_config_module(_pre_args.config)
else:
    import config as _cfg

BOUNDS               = _cfg.BOUNDS
LAT_CENTER           = _cfg.LAT_CENTER
WALL_WIDTH_FEET      = _cfg.WALL_WIDTH_FEET
WALL_HEIGHT_FEET     = _cfg.WALL_HEIGHT_FEET
PREVIEW              = _cfg.PREVIEW
PREVIEW_DPI          = _cfg.PREVIEW_DPI
PREVIEW_WIDTH        = _cfg.PREVIEW_WIDTH
PRINT_DPI            = _cfg.PRINT_DPI
DEM_RESOLUTION_M     = _cfg.DEM_RESOLUTION_M
CONTOUR_INTERVAL_M   = _cfg.CONTOUR_INTERVAL_M
INDEX_EVERY          = _cfg.INDEX_EVERY
CONTOUR_SMOOTH       = _cfg.CONTOUR_SMOOTH
CONTOUR_LABEL_FMT    = _cfg.CONTOUR_LABEL_FMT
PALETTE              = _cfg.PALETTE
LW                   = _cfg.LW
LW_PRINT             = _cfg.LW_PRINT
HS_AZIMUTH           = _cfg.HS_AZIMUTH
HS_ALTITUDE          = _cfg.HS_ALTITUDE
HS_VERT_EXAG         = _cfg.HS_VERT_EXAG
HS_ALPHA             = _cfg.HS_ALPHA
FONT_FAMILY          = _cfg.FONT_FAMILY
FONT                 = _cfg.FONT
MAP_TITLE            = _cfg.MAP_TITLE
MAP_SUBTITLE         = _cfg.MAP_SUBTITLE
SHOW_TITLE           = _cfg.SHOW_TITLE
SHOW_LEGEND          = _cfg.SHOW_LEGEND
SHOW_GRID            = _cfg.SHOW_GRID
SLICE_BOUNDS         = _cfg.SLICE_BOUNDS
SIMPLIFY_TOLERANCE_DEG = _cfg.SIMPLIFY_TOLERANCE_DEG
DEM_PATH             = _cfg.DEM_PATH
OSM_PATH             = _cfg.OSM_PATH
DATA_DIR             = _cfg.DATA_DIR
OUTPUT_DIR           = _cfg.OUTPUT_DIR

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch
import rasterio

# ── CLI overrides (all default to config.py values) ──────────────────────────
_ap = _argparse.ArgumentParser(
    description='Render stylized map PDF',
    formatter_class=_argparse.ArgumentDefaultsHelpFormatter,
    # Use --flag=value syntax for negative numbers: --bounds=-97.0,35.0,-96.0,36.0
)
_ap.add_argument('--config', metavar='FILE',
                 help='Path to an alternate config.py (replaces the default config.py)')
_ap.add_argument('--bounds', metavar='W,S,E,N',
                 help='Override config.BOUNDS (west,south,east,north)')
_ap.add_argument('--slice', metavar='W,S,E,N',
                 help='Override config.SLICE_BOUNDS (west,south,east,north)')
_ap.add_argument('--wall-w', type=float, metavar='FEET',
                 help='Wall width in feet (overrides config.WALL_WIDTH_FEET)')
_ap.add_argument('--wall-h', type=float, metavar='FEET',
                 help='Wall height in feet (overrides config.WALL_HEIGHT_FEET)')
_ap.add_argument('--dpi', type=int,
                 help='Override PRINT_DPI')
_ap.add_argument('--simplify', type=float, metavar='DEG',
                 help='Douglas-Peucker tolerance in degrees (overrides config)')
_ap.add_argument('--output-dir', metavar='DIR',
                 help='Output directory (overrides config.OUTPUT_DIR)')
_mode = _ap.add_mutually_exclusive_group()
_mode.add_argument('--preview', action='store_true', default=False,
                   help='Force preview mode (PREVIEW=True)')
_mode.add_argument('--print', dest='full_print', action='store_true', default=False,
                   help='Force full print mode (PREVIEW=False)')
_cli = _ap.parse_args()

if _cli.bounds:
    _w, _s, _e, _n = map(float, _cli.bounds.split(','))
    BOUNDS = {'west': _w, 'south': _s, 'east': _e, 'north': _n}
    LAT_CENTER = (BOUNDS['north'] + BOUNDS['south']) / 2
if _cli.slice:
    _w, _s, _e, _n = map(float, _cli.slice.split(','))
    SLICE_BOUNDS = {'west': _w, 'south': _s, 'east': _e, 'north': _n}
if _cli.wall_w:
    WALL_WIDTH_FEET = _cli.wall_w
if _cli.wall_h:
    WALL_HEIGHT_FEET = _cli.wall_h
if _cli.dpi:
    PRINT_DPI = _cli.dpi
if _cli.simplify is not None:
    SIMPLIFY_TOLERANCE_DEG = _cli.simplify
if _cli.output_dir:
    OUTPUT_DIR = _cli.output_dir
if _cli.preview:
    PREVIEW = True
if _cli.full_print:
    PREVIEW = False

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Utility ──────────────────────────────────────────────────────────────────
_t_start = time.time()
_t_phase = _t_start

def step(msg):
    """Print a phase header with elapsed-since-start and time-since-prev-step."""
    global _t_phase
    now = time.time()
    if _t_phase != _t_start:
        print(f"     · prev phase took {now - _t_phase:.1f}s", flush=True)
    elapsed = int(now - _t_start)
    mm, ss = divmod(elapsed, 60)
    _t_phase = now
    print(f"\n  ▸  [{mm:02d}:{ss:02d}] {msg}", flush=True)

def tick(msg):
    """Inline progress message (no phase change). Use for sub-steps."""
    elapsed = int(time.time() - _t_start)
    mm, ss = divmod(elapsed, 60)
    print(f"     [{mm:02d}:{ss:02d}] {msg}", flush=True)

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

if _HAS_PSUTIL:
    _avail_mb = _psutil.virtual_memory().available / 1024 ** 2
    _min_mb = 8 * 1024 if (SLICE_MODE or PREVIEW) else 16 * 1024
    _mode_label = 'slice/preview' if (SLICE_MODE or PREVIEW) else 'full-bounds'
    if _avail_mb < _min_mb:
        print(
            f"  ⚠  LOW RAM: {_avail_mb / 1024:.1f} GB available; "
            f"{_mode_label} renders need ≥ {_min_mb // 1024} GB.\n"
            "     The render may be killed by the OOM monitor before completion.",
            flush=True,
        )

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
    alpha=0.75,
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
        tick(f"plotting {len(wb):,} water bodies …")
        wb.plot(ax=ax,
                color=PALETTE['water_fill'],
                edgecolor=PALETTE['water_line'],
                linewidth=lw('river_minor'),
                zorder=3, alpha=0.95)
        tick(f"✓  water bodies done")

    # ── Waterways (lines) ────────────────────────────────────────────────────
    ww = layers['waterways']
    if ww is not None:
        is_river = ww.get('waterway', '').isin(['river', 'canal']) if 'waterway' in ww.columns \
                   else ww.index.isin([])

        major_ww = ww[is_river]
        minor_ww = ww[~is_river]

        tick(f"plotting {len(major_ww):,} major + {len(minor_ww):,} minor waterways …")
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
                    tick(f"plotting {len(subset):,} {htype} roads …")
                    subset.plot(ax=ax,
                                color=PALETTE[color_key],
                                linewidth=lw(lw_key),
                                zorder=zord)
        else:
            roads.plot(ax=ax, color=PALETTE['minor_road'],
                       linewidth=lw('minor_road'), zorder=5)

        tick(f"✓  all {len(roads):,} roads plotted")

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
if SHOW_GRID:
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

tick(f"writing PDF (this is the slow part — encoding ~all paths) …")
t_save = time.time()
fig.savefig(out_pdf, dpi=dpi, bbox_inches='tight',
            facecolor=PALETTE['paper'], format='pdf',
            metadata={'Creator': 'Stylized Map Generator'})
tick(f"✓  PDF written in {time.time()-t_save:.1f}s")

print(f"\n  ✓  {label} saved:  {out_pdf}")
print(f"     Page size: {fig_w:.2f} × {fig_h:.2f} in (1:1 with print at this slice / scale)")

# Auto-convert to CMYK if an ICC profile is configured (print mode only)
_CMYK_ICC = getattr(_cfg, 'CMYK_ICC_PROFILE', None)
if not PREVIEW and _CMYK_ICC:
    import subprocess as _sp
    from pathlib import Path as _Path
    cmyk_path = str(_Path(out_pdf).with_stem(_Path(out_pdf).stem + '_CMYK'))
    tick("Converting to CMYK via Ghostscript …")
    try:
        _sp.run([
            'gs', '-sDEVICE=pdfwrite', '-dNOPAUSE', '-dBATCH', '-dQUIET',
            '-sColorConversionStrategy=CMYK', '-sProcessColorModel=DeviceCMYK',
            f'-sOutputICCProfile={_CMYK_ICC}', f'-sOutputFile={cmyk_path}', out_pdf,
        ], check=True)
        tick(f"✓  CMYK PDF: {cmyk_path}")
    except Exception as _e:
        tick(f"⚠  CMYK conversion failed: {_e} — RGB PDF still valid")

plt.close(fig)
total = int(time.time() - _t_start)
mm, ss = divmod(total, 60)
if _HAS_PSUTIL:
    _mem_stop.set()
    _mem_thread.join(timeout=6)
    print(f"\n  Done.  Total wall: {mm:02d}:{ss:02d}  |  Peak RSS: {_peak_rss_mb[0]:.0f} MB\n")
else:
    print(f"\n  Done.  Total wall: {mm:02d}:{ss:02d}\n")
