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
import numpy as np
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
    PALETTE, LW,
    HS_AZIMUTH, HS_ALTITUDE, HS_VERT_EXAG, HS_ALPHA,
    FONT_FAMILY, FONT,
    MAP_TITLE, MAP_SUBTITLE, SHOW_TITLE, SHOW_LEGEND,
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

if PREVIEW:
    aspect_ratio = WALL_H_IN / WALL_W_IN      # ≈ 0.889
    fig_w = PREVIEW_WIDTH
    fig_h = fig_w * aspect_ratio
    dpi   = PREVIEW_DPI
else:
    fig_w = WALL_W_IN
    fig_h = WALL_H_IN
    dpi   = PRINT_DPI

# Scale factor: LW and FONT values in config are tuned for PREVIEW_WIDTH.
# For print, we multiply by PRINT_SCALE to fill the 108-inch figure.
PRINT_SCALE = WALL_W_IN / PREVIEW_WIDTH   # ≈ 7.7
SCALE = 1.0 if PREVIEW else PRINT_SCALE

step(f"Figure: {fig_w:.1f} × {fig_h:.1f} in @ {dpi} DPI  ({'PREVIEW' if PREVIEW else 'PRINT'})")

# ─── Create figure ────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=PALETTE['paper'])

# Axes fill the figure (we handle margins manually via padding)
ax = fig.add_axes([0.03, 0.04, 0.94, 0.92])   # [left, bottom, width, height] in figure fractions
ax.set_facecolor(PALETTE['paper'])
ax.set_xlim(BOUNDS['west'], BOUNDS['east'])
ax.set_ylim(BOUNDS['south'], BOUNDS['north'])

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
    """Return line weight in points, scaled for current figure size."""
    return LW[key] * SCALE

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

with rasterio.open(DEM_PATH) as src:
    dem   = src.read(1).astype(np.float32)
    bnd   = src.bounds
    xform = src.transform
    nodata = src.nodata

# Mask nodata
if nodata is not None:
    dem[dem == nodata] = np.nan
dem[dem < -500] = np.nan   # catch stray fill values

print(f"     DEM shape : {dem.shape[1]} × {dem.shape[0]} px")
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
    alpha=0.75,
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

    # ── Water bodies (polygons — rendered behind waterways) ──────────────────
    if 'water_bodies' in available:
        wb = gpd.read_file(OSM_PATH, layer='water_bodies', engine='pyogrio')
        wb.plot(ax=ax,
                color=PALETTE['water_fill'],
                edgecolor=PALETTE['water_line'],
                linewidth=lw('river_minor'),
                zorder=4, alpha=0.95)
        print(f"     ✓  Water bodies: {len(wb)}")

    # ── Waterways (lines) ────────────────────────────────────────────────────
    if 'waterways' in available:
        ww = gpd.read_file(OSM_PATH, layer='waterways', engine='pyogrio')
        is_river = ww.get('waterway', '').isin(['river', 'canal']) if 'waterway' in ww.columns \
                   else ww.index.isin([])

        major_ww = ww[is_river]
        minor_ww = ww[~is_river]

        if len(major_ww):
            major_ww.plot(ax=ax, color=PALETTE['water_line'],
                          linewidth=lw('river_major'), zorder=5)
        if len(minor_ww):
            minor_ww.plot(ax=ax, color=PALETTE['water_line'],
                          linewidth=lw('river_minor'), zorder=5, alpha=0.7)
        print(f"     ✓  Waterways: {len(ww)} ({len(major_ww)} major)")

    # ── Roads ─────────────────────────────────────────────────────────────────
    if 'roads' in available:
        roads = gpd.read_file(OSM_PATH, layer='roads', engine='pyogrio')

        road_hierarchy = [
            # (highway tag substring,    linewidth key,   color key)
            ('motorway',                 'highway',       'highway'),
            ('trunk',                    'highway',       'highway'),
            ('primary',                  'major_road',    'major_road'),
            ('secondary',                'major_road',    'major_road'),
            ('tertiary',                 'minor_road',    'minor_road'),
            ('residential',              'minor_road',    'minor_road'),
            ('unclassified',             'minor_road',    'minor_road'),
        ]

        if 'highway' in roads.columns:
            for htype, lw_key, color_key in road_hierarchy:
                mask = roads['highway'].astype(str).str.lower() == htype
                subset = roads[mask]
                if len(subset):
                    subset.plot(ax=ax,
                                color=PALETTE[color_key],
                                linewidth=lw(lw_key),
                                zorder=6)
        else:
            roads.plot(ax=ax, color=PALETTE['minor_road'],
                       linewidth=lw('minor_road'), zorder=6)

        print(f"     ✓  Roads: {len(roads)}")

    # ── Railways ──────────────────────────────────────────────────────────────
    if 'railways' in available:
        rail = gpd.read_file(OSM_PATH, layer='railways', engine='pyogrio')
        # Thin black dashed line — classic rail symbol
        rail.plot(ax=ax, color=PALETTE['railroad'],
                  linewidth=lw('railroad') * 0.7, zorder=7,
                  linestyle=(0, (5, 4)))
        print(f"     ✓  Railways: {len(rail)}")

    # ── Places ────────────────────────────────────────────────────────────────
    if 'places' in available:
        places = gpd.read_file(OSM_PATH, layer='places', engine='pyogrio')

        # Scatter marker size is in points² — scale with figure
        place_config = {
            'city':    ('o', (7  * SCALE) ** 2, FONT['city']),
            'town':    ('o', (4  * SCALE) ** 2, FONT['town']),
            'village': ('o', (2.5 * SCALE) ** 2, FONT['village']),
            'hamlet':  ('.', (1.5 * SCALE) ** 2, FONT['hamlet']),
        }

        if 'place' not in places.columns:
            places['place'] = 'town'

        for ptype, (marker, msize, fspec) in place_config.items():
            subset = places[places['place'] == ptype]
            if len(subset) == 0:
                continue

            # Dot
            ax.scatter(
                subset.geometry.x,
                subset.geometry.y,
                s=msize,
                color=PALETTE['town_dot'],
                zorder=10,
                marker=marker,
                linewidths=0,
            )

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
                        xytext=(4, 4),
                        textcoords='offset points',
                        fontsize=fs(ptype if ptype in FONT else 'town'),
                        fontfamily=FONT_FAMILY,
                        fontweight=fspec['weight'],
                        fontstyle=fspec.get('style', 'normal'),
                        color=PALETTE['town_label'],
                        zorder=11,
                        path_effects=[
                            pe.withStroke(linewidth=max(1.5, 2.5 * SCALE),
                                          foreground=PALETTE['label_halo'])
                        ],
                    )

        print(f"     ✓  Places: {len(places)}")

# ═══════════════════════════════════════════════════════
#  4. Neatline / border
# ═══════════════════════════════════════════════════════
step("Drawing border …")

# Double-line neatline (outer thick + inner thin)
for spine in ax.spines.values():
    spine.set_visible(False)

dlon = BOUNDS['east'] - BOUNDS['west']
dlat = BOUNDS['north'] - BOUNDS['south']

outer = plt.Rectangle(
    (BOUNDS['west'], BOUNDS['south']), dlon, dlat,
    linewidth=lw('border'), edgecolor=PALETTE['border'],
    facecolor='none', transform=ax.transData, zorder=20,
)
ax.add_patch(outer)

# ── Lat/lon tick grid (subtle) ──────────────────────────────────────────────
for lon in np.arange(np.ceil(BOUNDS['west']), BOUNDS['east'] + 0.5, 0.5):
    ax.axvline(lon, color=PALETTE['grid'],
               linewidth=0.3 * SCALE, zorder=0, alpha=0.5)
for lat in np.arange(np.ceil(BOUNDS['south']), BOUNDS['north'] + 0.5, 0.5):
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

if PREVIEW:
    out_png = os.path.join(OUTPUT_DIR, 'map_preview.png')
    fig.savefig(out_png, dpi=dpi, bbox_inches='tight',
                facecolor=PALETTE['paper'], format='png')
    print(f"\n  ✓  Preview saved:  {out_png}")
    print("     Open that file to review.  Adjust config.py and re-run.")
    print("     When happy, set PREVIEW = False for the print-quality export.\n")
else:
    # PDF (vector — preferred by most print shops)
    out_pdf = os.path.join(OUTPUT_DIR, 'oklahoma_topo_PRINT.pdf')
    fig.savefig(out_pdf, dpi=dpi, bbox_inches='tight',
                facecolor=PALETTE['paper'], format='pdf',
                metadata={'Creator': 'Oklahoma Topo Map Pipeline'})
    print(f"  ✓  PDF  saved:  {out_pdf}")

    # High-res PNG for Photoshop finishing (texture, color grading)
    out_png = os.path.join(OUTPUT_DIR, 'oklahoma_topo_PRINT.png')
    fig.savefig(out_png, dpi=dpi, bbox_inches='tight',
                facecolor=PALETTE['paper'], format='png')
    print(f"  ✓  PNG  saved:  {out_png}")
    print(f"\n  Print PNG dimensions: ~{int(fig_w * dpi):,} × {int(fig_h * dpi):,} px")

plt.close(fig)
print("\n  Done.\n")
