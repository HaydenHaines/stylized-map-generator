"""
Stylized Map Generator — Step 3: PDF Renderer
==============================================
Renders each cached vector layer to a separate transparent-background PDF.
Each layer is a separate matplotlib figure that is closed after saving, keeping
peak memory to one layer at a time.

Outputs to output/layers/:
    hillshade.pdf
    contours.pdf
    water_bodies.pdf
    waterways.pdf
    roads.pdf
    railways.pdf
    places.pdf
    border.pdf

Usage:
    python 03_pdf_renderer.py              # skip already-rendered layers
    python 03_pdf_renderer.py --force      # re-render all layers
    python 03_pdf_renderer.py --preview    # render SLICE_BOUNDS region only
    python 03_pdf_renderer.py --layers hillshade contours  # specific layers only
"""

import os, sys, json, time, argparse, gc
import numpy as np
from scipy.ndimage import gaussian_filter

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import LightSource, LinearSegmentedColormap

from config import (
    BOUNDS, LAT_CENTER,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    PREVIEW_WIDTH, PRINT_DPI,
    CONTOUR_INTERVAL_M, INDEX_EVERY, CONTOUR_LABEL_FMT,
    PALETTE, LW_PRINT,
    HS_ALPHA,
    FONT_FAMILY, FONT,
    MAP_TITLE, MAP_SUBTITLE, SHOW_TITLE,
    SLICE_BOUNDS,
    WATER_BODY_MIN_AREA_HA,
    CACHE_DIR, OUTPUT_DIR,
)

LAYERS_DIR = os.path.join(OUTPUT_DIR, 'layers')
os.makedirs(LAYERS_DIR, exist_ok=True)

ALL_LAYERS = ['hillshade', 'contours', 'water_bodies', 'waterways',
              'roads', 'railways', 'places', 'border']

WALL_W_IN  = WALL_WIDTH_FEET  * 12
WALL_H_IN  = WALL_HEIGHT_FEET * 12
PRINT_SCALE = WALL_W_IN / PREVIEW_WIDTH   # ≈ 7.7 — scales preview-tuned font sizes to print

_t_start = time.time()

def step(msg):
    elapsed = int(time.time() - _t_start)
    mm, ss = divmod(elapsed, 60)
    print(f"\n  ▸  [{mm:02d}:{ss:02d}] {msg}", flush=True)

def tick(msg):
    elapsed = int(time.time() - _t_start)
    mm, ss = divmod(elapsed, 60)
    print(f"     [{mm:02d}:{ss:02d}] {msg}", flush=True)

def _c(name):
    return os.path.join(CACHE_DIR, name)

def _o(name):
    return os.path.join(LAYERS_DIR, name)

def lw(key):
    return LW_PRINT[key] * 72.0 / PRINT_DPI

def fs(key):
    return FONT[key]['size'] * PRINT_SCALE

def m_to_ft(m):
    return m * 3.28084


# ─── Figure factory ───────────────────────────────────────────────────────────

def _make_fig_ax(bounds):
    """
    Create a figure + axes sized to represent `bounds` at wall print scale.
    The wall dimensions already encode the correct geographic aspect ratio, so
    axes fill the figure with aspect='auto' — no set_aspect() needed.
    """
    full_dlon = BOUNDS['east']  - BOUNDS['west']
    full_dlat = BOUNDS['north'] - BOUNDS['south']
    b_dlon    = bounds['east']  - bounds['west']
    b_dlat    = bounds['north'] - bounds['south']

    fig_w = WALL_W_IN * (b_dlon / full_dlon)
    fig_h = WALL_H_IN * (b_dlat / full_dlat)

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=PRINT_DPI)
    fig.patch.set_alpha(0)

    ax = fig.add_axes([0, 0, 1, 1])
    ax.patch.set_alpha(0)
    ax.set_xlim(bounds['west'],  bounds['east'])
    ax.set_ylim(bounds['south'], bounds['north'])
    ax.set_aspect('auto')
    ax.axis('off')

    return fig, ax


def _save(fig, name):
    out = _o(f'{name}.pdf')
    tick(f"writing {name}.pdf …")
    t0 = time.time()
    fig.savefig(out, format='pdf', transparent=True,
                bbox_inches=None,
                metadata={'Creator': 'Stylized Map Generator'})
    tick(f"✓  {name}.pdf  ({os.path.getsize(out)/1e6:.1f} MB, {time.time()-t0:.1f}s)")
    plt.close(fig)


# ─── Hillshade ────────────────────────────────────────────────────────────────

def render_hillshade(bounds, force=False):
    if not force and os.path.exists(_o('hillshade.pdf')):
        tick("hillshade.pdf exists — skipping")
        return

    step("Rendering hillshade …")

    hs_path   = _c('hillshade.npy')
    meta_path = _c('dem_meta.json')
    if not os.path.exists(hs_path):
        print("  ERROR: cache/hillshade.npy not found.  Run 02_vector_renderer.py first.")
        sys.exit(1)

    with open(meta_path) as f:
        meta = json.load(f)

    shade_vec = np.load(hs_path)   # shape (h, w), y-up, full-bounds

    # Crop to render bounds by slicing the array
    h, w      = shade_vec.shape
    left, right, bottom, top = meta['left'], meta['right'], meta['bottom'], meta['top']

    x_all = np.linspace(left,   right,  w)
    y_all = np.linspace(bottom, top,    h)

    xi = np.searchsorted(x_all, [bounds['west'],  bounds['east']])
    yi = np.searchsorted(y_all, [bounds['south'], bounds['north']])
    xi[1] = min(xi[1] + 1, w)
    yi[1] = min(yi[1] + 1, h)

    x_hs = x_all[xi[0]:xi[1]]
    y_hs = y_all[yi[0]:yi[1]]
    sv   = shade_vec[yi[0]:yi[1], xi[0]:xi[1]]

    # Downsample to keep contourf path count manageable at wall scale.
    # Target ~3000 px on the long axis — indistinguishable at 9-foot print scale
    # for a smooth shading gradient, and avoids hundreds of MB of vector paths.
    max_dim = 3000
    ds = max(1, max(sv.shape[0], sv.shape[1]) // max_dim)
    if ds > 1:
        sv    = sv[::ds, ::ds]
        x_hs  = x_hs[::ds]
        y_hs  = y_hs[::ds]

    cmap_shade = LinearSegmentedColormap.from_list(
        'hs', [PALETTE['hillshade_dark'], PALETTE['paper']], N=256,
    )
    levels_hs = np.linspace(sv.min(), sv.max(), 17)   # 16 bands — enough for smooth gradient

    tick(f"hillshade grid: {sv.shape[1]}×{sv.shape[0]} px, {len(levels_hs)-1} bands")
    fig, ax = _make_fig_ax(bounds)
    ax.contourf(x_hs, y_hs, sv,
                levels=levels_hs, cmap=cmap_shade,
                alpha=HS_ALPHA, zorder=1, antialiased=False)
    _save(fig, 'hillshade')


# ─── Contours ────────────────────────────────────────────────────────────────

def render_contours(bounds, force=False):
    if not force and os.path.exists(_o('contours.pdf')):
        tick("contours.pdf exists — skipping")
        return

    step("Rendering contours …")

    dem_path  = _c('dem_smooth.npy')
    meta_path = _c('dem_meta.json')
    if not os.path.exists(dem_path):
        print("  ERROR: cache/dem_smooth.npy not found.  Run 02_vector_renderer.py first.")
        sys.exit(1)

    with open(meta_path) as f:
        meta = json.load(f)

    dem_smooth = np.load(dem_path)
    h, w       = dem_smooth.shape
    left, right, top_m, bottom = meta['left'], meta['right'], meta['top'], meta['bottom']

    # 1-D coordinate arrays — matplotlib.contour accepts these directly,
    # avoiding a 2× ~830 MB meshgrid allocation for the full-state DEM.
    X = np.linspace(left,   right,  w)   # longitude, shape (w,)
    Y = np.linspace(top_m,  bottom, h)   # latitude top→bottom, shape (h,)

    # Clip to render bounds
    xi        = np.searchsorted(X,  [bounds['west'],   bounds['east']])
    yi_raster = np.searchsorted(-Y, [-bounds['north'], -bounds['south']])  # Y is descending
    xi[1]        = min(xi[1] + 1,        w)
    yi_raster[1] = min(yi_raster[1] + 1, h)

    X_c   = X[xi[0]:xi[1]]
    Y_c   = Y[yi_raster[0]:yi_raster[1]]
    dem_c = dem_smooth[yi_raster[0]:yi_raster[1], xi[0]:xi[1]]

    # Downsample to keep contour computation tractable for the full state.
    # Target ~4000 px on the long axis — contour paths are already smoothed by
    # the gaussian filter, so sub-pixel precision at this scale is redundant.
    max_dim = 4000
    ds = max(1, max(dem_c.shape[0], dem_c.shape[1]) // max_dim)
    if ds > 1:
        dem_c = dem_c[::ds, ::ds]
        X_c   = X_c[::ds]
        Y_c   = Y_c[::ds]
    print(f"     contour grid: {dem_c.shape[1]}×{dem_c.shape[0]} px (ds={ds})")

    elev_min   = np.nanmin(dem_c)
    elev_max   = np.nanmax(dem_c)
    first      = np.ceil(elev_min / CONTOUR_INTERVAL_M) * CONTOUR_INTERVAL_M
    all_levels = np.arange(first, elev_max + CONTOUR_INTERVAL_M, CONTOUR_INTERVAL_M)

    reg_levels = [l for i, l in enumerate(all_levels) if (i % INDEX_EVERY) != 0]
    idx_levels = [l for i, l in enumerate(all_levels) if (i % INDEX_EVERY) == 0]
    print(f"     {len(all_levels)} levels  ({len(idx_levels)} index contours)")

    def fmt_elev(v):
        return f"{m_to_ft(v):.0f}" if CONTOUR_LABEL_FMT == 'ft' else f"{v:.0f}"

    fig, ax = _make_fig_ax(bounds)

    ax.contour(X_c, Y_c, dem_c,
               levels=reg_levels,
               colors=[PALETTE['contour']],
               linewidths=lw('contour'),
               zorder=2, alpha=0.5)

    cs_idx = ax.contour(X_c, Y_c, dem_c,
                        levels=idx_levels,
                        colors=[PALETTE['index_contour']],
                        linewidths=lw('index_contour'),
                        zorder=3, alpha=0.75)

    ax.clabel(cs_idx, inline=True, fontsize=fs('contour'),
              fmt=fmt_elev, inline_spacing=2,
              use_clabeltext=True, colors=PALETTE['index_contour'])

    _save(fig, 'contours')


# ─── Water bodies ─────────────────────────────────────────────────────────────

def render_water_bodies(bounds, force=False):
    if not force and os.path.exists(_o('water_bodies.pdf')):
        tick("water_bodies.pdf exists — skipping")
        return

    step("Rendering water bodies …")

    wb_path = _c('water_bodies.parquet')
    if not os.path.exists(wb_path):
        tick("water_bodies.parquet not found — skipping")
        return

    import geopandas as gpd
    wb = gpd.read_parquet(wb_path)

    # Clip to render bounds
    from shapely.geometry import box
    clip_box = box(bounds['west'], bounds['south'], bounds['east'], bounds['north'])
    wb = wb[wb.geometry.intersects(clip_box)]

    cos_lat = np.cos(np.radians(LAT_CENTER))
    min_area = WATER_BODY_MIN_AREA_HA / (111 * 111 * cos_lat * 100)
    wb = wb[wb.area > min_area]
    tick(f"plotting {len(wb):,} water bodies …")

    fig, ax = _make_fig_ax(bounds)
    if len(wb):
        wb.plot(ax=ax, color=PALETTE['water_fill'],
                edgecolor=PALETTE['water_line'],
                linewidth=lw('river_minor'), zorder=3, alpha=0.95)
    _save(fig, 'water_bodies')


# ─── Waterways ───────────────────────────────────────────────────────────────

def render_waterways(bounds, force=False):
    if not force and os.path.exists(_o('waterways.pdf')):
        tick("waterways.pdf exists — skipping")
        return

    step("Rendering waterways …")

    ww_path = _c('waterways.parquet')
    if not os.path.exists(ww_path):
        tick("waterways.parquet not found — skipping")
        return

    import geopandas as gpd
    from shapely.geometry import box
    ww = gpd.read_parquet(ww_path)
    clip_box = box(bounds['west'], bounds['south'], bounds['east'], bounds['north'])
    ww = ww[ww.geometry.intersects(clip_box)]

    is_river  = ww.get('waterway', '').isin(['river', 'canal']) \
                if 'waterway' in ww.columns else ww.index.isin([])
    major_ww  = ww[is_river]
    minor_ww  = ww[~is_river]
    tick(f"plotting {len(major_ww):,} major + {len(minor_ww):,} minor waterways …")

    fig, ax = _make_fig_ax(bounds)
    if len(major_ww):
        major_ww.plot(ax=ax, color=PALETTE['water_line'],
                      linewidth=lw('river_major'), zorder=4)
    if len(minor_ww):
        minor_ww.plot(ax=ax, color=PALETTE['water_line'],
                      linewidth=lw('river_minor'), zorder=4, alpha=0.7)
    _save(fig, 'waterways')


# ─── Roads ───────────────────────────────────────────────────────────────────

ROAD_HIERARCHY = [
    ('motorway',     'highway',    'highway',    8),
    ('trunk',        'highway',    'highway',    8),
    ('primary',      'major_road', 'major_road', 6),
    ('secondary',    'major_road', 'major_road', 6),
    ('tertiary',     'minor_road', 'minor_road', 5),
    ('residential',  'minor_road', 'minor_road', 5),
    ('unclassified', 'minor_road', 'minor_road', 5),
]


def render_roads(bounds, force=False):
    if not force and os.path.exists(_o('roads.pdf')):
        tick("roads.pdf exists — skipping")
        return

    step("Rendering roads …")

    roads_path = _c('roads.parquet')
    if not os.path.exists(roads_path):
        tick("roads.parquet not found — skipping")
        return

    import geopandas as gpd
    from shapely.geometry import box
    roads = gpd.read_parquet(roads_path)
    clip_box = box(bounds['west'], bounds['south'], bounds['east'], bounds['north'])
    roads = roads[roads.geometry.intersects(clip_box)]

    fig, ax = _make_fig_ax(bounds)

    if 'highway' in roads.columns:
        for htype, lw_key, color_key, zord in ROAD_HIERARCHY:
            mask   = roads['highway'].astype(str).str.lower() == htype
            subset = roads[mask]
            if len(subset):
                tick(f"plotting {len(subset):,} {htype} roads …")
                subset.plot(ax=ax, color=PALETTE[color_key],
                            linewidth=lw(lw_key), zorder=zord)
    else:
        roads.plot(ax=ax, color=PALETTE['minor_road'],
                   linewidth=lw('minor_road'), zorder=5)

    tick(f"✓  {len(roads):,} roads total")
    _save(fig, 'roads')


# ─── Railways ────────────────────────────────────────────────────────────────

def render_railways(bounds, force=False):
    if not force and os.path.exists(_o('railways.pdf')):
        tick("railways.pdf exists — skipping")
        return

    step("Rendering railways …")

    rail_path = _c('railways.parquet')
    if not os.path.exists(rail_path):
        tick("railways.parquet not found — skipping")
        return

    import geopandas as gpd
    from shapely.geometry import box
    rail = gpd.read_parquet(rail_path)
    clip_box = box(bounds['west'], bounds['south'], bounds['east'], bounds['north'])
    rail = rail[rail.geometry.intersects(clip_box)]

    fig, ax = _make_fig_ax(bounds)
    if len(rail):
        rail.plot(ax=ax, color=PALETTE['railroad'],
                  linewidth=lw('railroad') * 0.7, zorder=7,
                  linestyle=(0, (5, 4)))
    tick(f"✓  {len(rail):,} railway segments")
    _save(fig, 'railways')


# ─── Places ──────────────────────────────────────────────────────────────────

def render_places(bounds, force=False):
    if not force and os.path.exists(_o('places.pdf')):
        tick("places.pdf exists — skipping")
        return

    step("Rendering places …")

    places_path = _c('places.parquet')
    if not os.path.exists(places_path):
        tick("places.parquet not found — skipping")
        return

    import geopandas as gpd
    from shapely.geometry import box
    places = gpd.read_parquet(places_path)
    clip_box = box(bounds['west'], bounds['south'], bounds['east'], bounds['north'])
    places = places[places.geometry.intersects(clip_box)]

    if 'place' not in places.columns:
        places = places.copy()
        places['place'] = 'town'

    place_config = {
        'city':    FONT['city'],
        'town':    FONT['town'],
        'village': FONT['village'],
        'hamlet':  FONT['hamlet'],
    }

    fig, ax = _make_fig_ax(bounds)

    for ptype, fspec in place_config.items():
        subset = places[places['place'] == ptype]
        if len(subset) == 0:
            continue
        if 'name' not in subset.columns:
            continue
        for _, row in subset.iterrows():
            name = row.get('name')
            if not name or (isinstance(name, float) and np.isnan(name)):
                continue
            name = str(name).split(';', 1)[0].strip()
            ax.annotate(
                name,
                xy=(row.geometry.x, row.geometry.y),
                xytext=(0, 2 * PRINT_SCALE),
                textcoords='offset points',
                ha='center', va='bottom',
                fontsize=fs(ptype if ptype in FONT else 'town'),
                fontfamily=FONT_FAMILY,
                fontweight=fspec['weight'],
                fontstyle=fspec.get('style', 'normal'),
                color=PALETTE['town_label'],
                zorder=11,
            )

    tick(f"✓  {len(places):,} places labelled")
    _save(fig, 'places')


# ─── Border + grid ────────────────────────────────────────────────────────────

def render_border(bounds, force=False):
    if not force and os.path.exists(_o('border.pdf')):
        tick("border.pdf exists — skipping")
        return

    step("Rendering border + grid …")

    fig, ax = _make_fig_ax(bounds)

    dlon = bounds['east']  - bounds['west']
    dlat = bounds['north'] - bounds['south']

    # Lat/lon grid
    for lon in np.arange(np.ceil(bounds['west']),  bounds['east']  + 0.5, 0.5):
        ax.axvline(lon, color=PALETTE['grid'],
                   linewidth=0.3 * PRINT_SCALE, zorder=0, alpha=0.5)
    for lat in np.arange(np.ceil(bounds['south']), bounds['north'] + 0.5, 0.5):
        ax.axhline(lat, color=PALETTE['grid'],
                   linewidth=0.3 * PRINT_SCALE, zorder=0, alpha=0.5)

    # Neatline (omitted in preview/slice mode — border layer always includes it)
    outer = plt.Rectangle(
        (bounds['west'], bounds['south']), dlon, dlat,
        linewidth=lw('border'), edgecolor=PALETTE['border'],
        facecolor='none', transform=ax.transData, zorder=20,
    )
    ax.add_patch(outer)

    # Title block
    if SHOW_TITLE:
        tx = bounds['west'] + dlon * 0.02
        ty = bounds['south'] + dlat * 0.06
        ax.text(tx, ty + dlat * 0.04, MAP_TITLE.upper(),
                fontsize=fs('title'), fontfamily=FONT_FAMILY,
                fontweight='bold', color=PALETTE['border'],
                transform=ax.transData, zorder=22, verticalalignment='bottom',
                path_effects=[pe.withStroke(linewidth=3, foreground=PALETTE['paper'])])
        ax.text(tx, ty, MAP_SUBTITLE,
                fontsize=fs('subtitle'), fontfamily=FONT_FAMILY,
                fontstyle='italic', color=PALETTE['border'],
                transform=ax.transData, zorder=22, verticalalignment='top',
                path_effects=[pe.withStroke(linewidth=2, foreground=PALETTE['paper'])])

    _save(fig, 'border')


# ─── Dispatch ─────────────────────────────────────────────────────────────────

_RENDER_FNS = {
    'hillshade':    render_hillshade,
    'contours':     render_contours,
    'water_bodies': render_water_bodies,
    'waterways':    render_waterways,
    'roads':        render_roads,
    'railways':     render_railways,
    'places':       render_places,
    'border':       render_border,
}


def main():
    parser = argparse.ArgumentParser(description='Render cached layers to per-layer PDFs.')
    parser.add_argument('--force', action='store_true',
                        help='Re-render layers even if PDFs already exist')
    parser.add_argument('--preview', action='store_true',
                        help='Render SLICE_BOUNDS region instead of full BOUNDS')
    parser.add_argument('--layers', nargs='+', choices=ALL_LAYERS,
                        help='Render only these layers (default: all)')
    args = parser.parse_args()

    bounds = SLICE_BOUNDS if (args.preview and SLICE_BOUNDS) else BOUNDS
    layers = args.layers or ALL_LAYERS

    region = 'SLICE_BOUNDS' if bounds is not BOUNDS else 'BOUNDS'
    print(f"\n  PDF Renderer → {LAYERS_DIR}/")
    print(f"  Region: {region}   Layers: {layers}")
    if args.force:
        print("  --force: existing layer PDFs will be overwritten")

    for name in layers:
        _RENDER_FNS[name](bounds, force=args.force)
        gc.collect()

    total = int(time.time() - _t_start)
    mm, ss = divmod(total, 60)
    print(f"\n  ✓  Done.  Total wall: {mm:02d}:{ss:02d}\n")


if __name__ == '__main__':
    main()
