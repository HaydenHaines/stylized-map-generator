"""
_render_layer.py — Per-layer render functions for parallel full render.

Each function receives an Axes and renders only its own content.
Called from render_full_parallel.py — not intended for direct use.
"""

from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter

from config import (
    BOUNDS, LAT_CENTER, PRINT_DPI,
    CONTOUR_INTERVAL_M, INDEX_EVERY, CONTOUR_SMOOTH, CONTOUR_LABEL_FMT,
    PALETTE, LW_PRINT,
    HS_AZIMUTH, HS_ALTITUDE, HS_VERT_EXAG, HS_ALPHA,
    FONT_FAMILY, FONT,
    SIMPLIFY_TOLERANCE_DEG,
    DEM_PATH, OSM_PATH,
    WALL_WIDTH_FEET,
    PREVIEW_WIDTH,
)

WALL_W_IN   = WALL_WIDTH_FEET * 12
PRINT_SCALE = WALL_W_IN / PREVIEW_WIDTH
cos_lat     = np.cos(np.radians(LAT_CENTER))


def _lw(key: str) -> float:
    return LW_PRINT[key] * 72.0 / PRINT_DPI


def _fs(key: str) -> float:
    return FONT[key]['size'] * PRINT_SCALE


def _load_dem():
    import rioxarray
    dem_ds = rioxarray.open_rasterio(DEM_PATH).squeeze()
    if str(dem_ds.rio.crs).upper() != 'EPSG:4326':
        dem_ds = dem_ds.rio.reproject('EPSG:4326')
    dem = dem_ds.values.astype(np.float32)
    nodata = dem_ds.rio.nodata
    if nodata is not None:
        dem[dem == nodata] = np.nan
    dem[dem < -500] = np.nan
    bnd_left   = float(dem_ds.x.values.min())
    bnd_right  = float(dem_ds.x.values.max())
    bnd_top    = float(dem_ds.y.values.max())
    bnd_bottom = float(dem_ds.y.values.min())
    h, w = dem.shape
    X  = np.linspace(bnd_left,  bnd_right, w)
    Y  = np.linspace(bnd_top,   bnd_bottom, h)
    Xg, Yg = np.meshgrid(X, Y)
    return dem, Xg, Yg, bnd_left, bnd_right, bnd_top, bnd_bottom, dem_ds.rio.transform()


def render_hillshade(ax) -> None:
    if HS_ALPHA <= 0:
        return  # hillshade disabled in config — skip raster allocation entirely
    from matplotlib.colors import LightSource, LinearSegmentedColormap
    dem, Xg, Yg, bl, br, bt, bb, xform = _load_dem()
    dx = abs(xform[0]) * 111_320 * cos_lat
    dy = abs(xform[4]) * 111_320
    dem_s = gaussian_filter(np.where(np.isnan(dem), np.nanmean(dem), dem), CONTOUR_SMOOTH)
    ls    = LightSource(azdeg=HS_AZIMUTH, altdeg=HS_ALTITUDE)
    shade = ls.hillshade(dem_s, vert_exag=HS_VERT_EXAG, dx=dx, dy=dy)
    cmap  = LinearSegmentedColormap.from_list('hs', [PALETTE['hillshade_dark'], PALETTE['paper']])
    # Embed at DEM native resolution, not print DPI — the gradient doesn't need 900 DPI
    ax.imshow(shade, cmap=cmap, extent=[bl, br, bb, bt],
              origin='upper', alpha=HS_ALPHA, zorder=1, interpolation='bilinear')


def render_contours(ax) -> None:
    dem, Xg, Yg, *_ = _load_dem()
    dem_s    = gaussian_filter(np.where(np.isnan(dem), np.nanmean(dem), dem), CONTOUR_SMOOTH)
    first    = np.ceil(np.nanmin(dem_s) / CONTOUR_INTERVAL_M) * CONTOUR_INTERVAL_M
    all_lvls = np.arange(first, np.nanmax(dem_s) + CONTOUR_INTERVAL_M, CONTOUR_INTERVAL_M)
    reg_lvls = [l for i, l in enumerate(all_lvls) if (i % INDEX_EVERY) != 0]
    idx_lvls = [l for i, l in enumerate(all_lvls) if (i % INDEX_EVERY) == 0]
    ax.contour(Xg, Yg, dem_s, levels=reg_lvls,
               colors=[PALETTE['contour']], linewidths=_lw('contour'), zorder=2, alpha=0.5)
    cs = ax.contour(Xg, Yg, dem_s, levels=idx_lvls,
                    colors=[PALETTE['index_contour']], linewidths=_lw('index_contour'),
                    zorder=3, alpha=0.75)
    fmt = (lambda v: f"{v*3.28084:.0f}") if CONTOUR_LABEL_FMT == 'ft' else (lambda v: f"{v:.0f}")
    ax.clabel(cs, inline=True, fontsize=_fs('contour'), fmt=fmt,
              inline_spacing=2, use_clabeltext=True, colors=PALETTE['index_contour'])


def render_water_bodies(ax) -> None:
    import os, geopandas as gpd
    if not os.path.exists(OSM_PATH):
        return
    try:
        gdf = gpd.read_file(OSM_PATH, layer='water_bodies', engine='pyogrio')
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(gdf):
            gdf.geometry = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        gdf.plot(ax=ax, color=PALETTE['water_fill'], edgecolor=PALETTE['water_line'],
                 linewidth=_lw('river_minor'), zorder=3, alpha=0.95)
    except Exception:
        pass


def render_waterways(ax) -> None:
    import os, geopandas as gpd
    if not os.path.exists(OSM_PATH):
        return
    try:
        ww = gpd.read_file(OSM_PATH, layer='waterways', engine='pyogrio')
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(ww):
            ww.geometry = ww.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        is_river = ww['waterway'].isin(['river', 'canal']) if 'waterway' in ww.columns \
                   else ww.index.isin([])
        major = ww[is_river]
        minor = ww[~is_river]
        if len(major):
            major.plot(ax=ax, color=PALETTE['water_line'], linewidth=_lw('river_major'), zorder=4)
        if len(minor):
            minor.plot(ax=ax, color=PALETTE['water_line'], linewidth=_lw('river_minor'),
                       zorder=4, alpha=0.7)
    except Exception:
        pass


def render_roads(ax) -> None:
    import os, geopandas as gpd
    if not os.path.exists(OSM_PATH):
        return
    try:
        roads = gpd.read_file(OSM_PATH, layer='roads', engine='pyogrio')
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(roads):
            roads.geometry = roads.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        hierarchy = [
            ('motorway',     'highway',    'highway',    8),
            ('trunk',        'highway',    'highway',    8),
            ('primary',      'major_road', 'major_road', 6),
            ('secondary',    'major_road', 'major_road', 6),
            ('tertiary',     'minor_road', 'minor_road', 5),
            ('residential',  'minor_road', 'minor_road', 5),
            ('unclassified', 'minor_road', 'minor_road', 5),
        ]
        if 'highway' in roads.columns:
            for htype, lw_key, color_key, zord in hierarchy:
                subset = roads[roads['highway'].astype(str).str.lower() == htype]
                if len(subset):
                    subset.plot(ax=ax, color=PALETTE[color_key],
                                linewidth=_lw(lw_key), zorder=zord)
        else:
            roads.plot(ax=ax, color=PALETTE['minor_road'], linewidth=_lw('minor_road'), zorder=5)
    except Exception:
        pass


def render_railways(ax) -> None:
    import os, geopandas as gpd
    if not os.path.exists(OSM_PATH):
        return
    try:
        rail = gpd.read_file(OSM_PATH, layer='railways', engine='pyogrio')
        if len(rail):
            rail.plot(ax=ax, color=PALETTE['railroad'],
                      linewidth=_lw('railroad') * 0.7, zorder=7, linestyle=(0, (5, 4)))
    except Exception:
        pass


def render_labels(ax) -> None:
    import os, geopandas as gpd
    if not os.path.exists(OSM_PATH):
        return
    try:
        places = gpd.read_file(OSM_PATH, layer='places', engine='pyogrio')
        if 'place' not in places.columns:
            places['place'] = 'town'
        for ptype in ('city', 'town', 'village', 'hamlet'):
            if ptype not in FONT:
                continue
            fspec  = FONT[ptype]
            subset = places[places['place'] == ptype]
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
                    fontsize=_fs(ptype),
                    fontfamily=FONT_FAMILY,
                    fontweight=fspec['weight'],
                    fontstyle=fspec.get('style', 'normal'),
                    color=PALETTE['town_label'],
                    zorder=11,
                )
    except Exception:
        pass


def render_border(ax) -> None:
    import matplotlib.pyplot as plt
    dlon = BOUNDS['east']  - BOUNDS['west']
    dlat = BOUNDS['north'] - BOUNDS['south']
    outer = plt.Rectangle(
        (BOUNDS['west'], BOUNDS['south']), dlon, dlat,
        linewidth=_lw('border'), edgecolor=PALETTE['border'],
        facecolor='none', transform=ax.transData, zorder=20,
    )
    ax.add_patch(outer)
    for lon in np.arange(np.ceil(BOUNDS['west']), BOUNDS['east'] + 0.5, 0.5):
        ax.axvline(lon, color=PALETTE['grid'], linewidth=0.3 * PRINT_SCALE, zorder=0, alpha=0.5)
    for lat in np.arange(np.ceil(BOUNDS['south']), BOUNDS['north'] + 0.5, 0.5):
        ax.axhline(lat, color=PALETTE['grid'], linewidth=0.3 * PRINT_SCALE, zorder=0, alpha=0.5)
