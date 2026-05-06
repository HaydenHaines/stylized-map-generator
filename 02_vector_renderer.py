"""
Stylized Map Generator — Step 2: Vector Renderer
=================================================
Preprocesses raw DEM and OSM data into cached geometry files.
Run once; re-run with --force to regenerate all layers.

Outputs to cache/:
    dem_smooth.npy      gaussian-filtered DEM (input for contour + hillshade rendering)
    dem_meta.json       bounds, shape, cell sizes, elevation range
    hillshade.npy       blurred shade array flipped for contourf (y-up)
    water_bodies.parquet
    waterways.parquet
    roads.parquet
    railways.parquet
    places.parquet

Usage:
    python 02_vector_renderer.py           # skip already-cached layers
    python 02_vector_renderer.py --force   # regenerate everything
"""

import os, sys, json, time, argparse
import numpy as np
from scipy.ndimage import gaussian_filter

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

from config import (
    BOUNDS, LAT_CENTER,
    CONTOUR_SMOOTH,
    HS_AZIMUTH, HS_ALTITUDE, HS_VERT_EXAG,
    SIMPLIFY_TOLERANCE_DEG,
    DEM_PATH, OSM_PATH, CACHE_DIR,
)

os.makedirs(CACHE_DIR, exist_ok=True)

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


# ─── DEM + hillshade ──────────────────────────────────────────────────────────

def process_dem(force=False):
    dem_out  = _c('dem_smooth.npy')
    meta_out = _c('dem_meta.json')
    hs_out   = _c('hillshade.npy')

    if not force and all(os.path.exists(p) for p in (dem_out, meta_out, hs_out)):
        tick("DEM + hillshade already cached — skipping (--force to redo)")
        return

    step("Loading + reprojecting DEM …")

    if not os.path.exists(DEM_PATH):
        print(f"\n  ERROR: {DEM_PATH} not found.  Run 01_download_data.py first.")
        sys.exit(1)

    import rioxarray

    dem_ds = rioxarray.open_rasterio(DEM_PATH).squeeze()
    if str(dem_ds.rio.crs).upper() != 'EPSG:4326':
        dem_ds = dem_ds.rio.reproject('EPSG:4326')

    dem    = dem_ds.values.astype(np.float32)
    xform  = dem_ds.rio.transform()
    nodata = dem_ds.rio.nodata

    left   = float(dem_ds.x.values.min())
    right  = float(dem_ds.x.values.max())
    top    = float(dem_ds.y.values.max())
    bottom = float(dem_ds.y.values.min())

    if nodata is not None:
        dem[dem == nodata] = np.nan
    dem[dem < -500] = np.nan

    print(f"     DEM shape : {dem.shape[1]} × {dem.shape[0]} px (EPSG:4326)")
    print(f"     Elevation : {np.nanmin(dem):.0f} – {np.nanmax(dem):.0f} m")

    cos_lat  = np.cos(np.radians(LAT_CENTER))
    dx       = abs(xform[0]) * 111_320 * cos_lat   # cell width in metres
    dy       = abs(xform[4]) * 111_320              # cell height in metres

    dem_smooth = gaussian_filter(
        np.where(np.isnan(dem), np.nanmean(dem), dem),
        sigma=CONTOUR_SMOOTH,
    )

    meta = {
        'left': left, 'right': right, 'top': top, 'bottom': bottom,
        'shape': list(dem_smooth.shape),
        'dx': dx, 'dy': dy,
        'elev_min': float(np.nanmin(dem)),
        'elev_max': float(np.nanmax(dem)),
    }

    np.save(dem_out, dem_smooth)
    with open(meta_out, 'w') as f:
        json.dump(meta, f, indent=2)
    tick(f"dem_smooth.npy saved  ({dem_smooth.nbytes / 1e6:.0f} MB)")

    step("Computing hillshade …")

    from matplotlib.colors import LightSource
    ls    = LightSource(azdeg=HS_AZIMUTH, altdeg=HS_ALTITUDE)
    shade = ls.hillshade(dem_smooth, vert_exag=HS_VERT_EXAG, dx=dx, dy=dy)

    # Extra smoothing keeps contourf path count manageable at wall scale.
    # Flip rows: contourf expects y increasing upward; raster is top-to-bottom.
    shade_vec = gaussian_filter(shade, sigma=4)[::-1].astype(np.float32)

    np.save(hs_out, shade_vec)
    tick(f"hillshade.npy saved  ({shade_vec.nbytes / 1e6:.0f} MB)")


# ─── OSM layers ───────────────────────────────────────────────────────────────

OSM_LAYERS = ['water_bodies', 'waterways', 'roads', 'railways', 'places']


def process_osm_layer(name, available, force=False):
    out_path = _c(f'{name}.parquet')

    if not force and os.path.exists(out_path):
        tick(f"{name}.parquet already cached — skipping")
        return

    if name not in available:
        tick(f"{name} not in OSM file — skipping")
        return

    import geopandas as gpd

    gdf = gpd.read_file(OSM_PATH, layer=name, engine='pyogrio')
    n_raw = len(gdf)

    if SIMPLIFY_TOLERANCE_DEG > 0 and len(gdf):
        if not (gdf.geometry.geom_type == 'Point').all():
            gdf.geometry = gdf.geometry.simplify(
                SIMPLIFY_TOLERANCE_DEG, preserve_topology=True,
            )

    # Dissolve by type so the renderer receives one MultiLineString per category
    # instead of hundreds of thousands of individual segments.  This eliminates
    # the connectivity-breaking length-filter approach and keeps peak render
    # memory proportional to road/waterway types (~7–15), not segment count.
    if name == 'roads' and 'highway' in gdf.columns:
        gdf['highway'] = gdf['highway'].astype(str).str.lower()
        gdf = gdf[['highway', 'geometry']].dissolve(by='highway', as_index=False)
        tick(f"roads: {n_raw:,} segments → {len(gdf)} dissolved types")

    if name == 'waterways' and 'waterway' in gdf.columns:
        gdf['waterway'] = gdf['waterway'].astype(str).str.lower()
        # Apply type-specific simplification: minor features (drains, ditches) are
        # often rectilinear ag channels with redundant collinear points — a looser
        # tolerance cuts path complexity substantially without visual impact at wall scale.
        WATERWAY_SIMPLIFY = {
            'river':   5e-5,   # ~5.5 m — preserve meander detail
            'canal':   5e-5,
            'stream':  2e-4,   # ~22 m — still very fine
            'creek':   2e-4,
            'drain':   5e-4,   # ~55 m — straight ag channels
            'ditch':   5e-4,
        }
        DEFAULT_WW_SIMPLIFY = 2e-4
        def _simplify_row(row):
            tol = WATERWAY_SIMPLIFY.get(row['waterway'], DEFAULT_WW_SIMPLIFY)
            return row.geometry.simplify(tol, preserve_topology=True)
        gdf.geometry = gdf.apply(_simplify_row, axis=1)
        gdf = gdf[['waterway', 'geometry']].dissolve(by='waterway', as_index=False)
        tick(f"waterways: {n_raw:,} segments → {len(gdf)} dissolved types")

    if name == 'railways':
        # Drop short segments (yard sidings, spurs) before dissolving.
        # Mainline segments between OSM junctions are typically several km;
        # yard/siding tracks are short and create solid-black patches at wall scale.
        # 0.005° ≈ 550 m at this latitude.
        MIN_RAIL_DEG = 0.005
        n_before = len(gdf)
        gdf = gdf[gdf.geometry.length >= MIN_RAIL_DEG].copy()
        tick(f"railways: {n_before:,} segments → {len(gdf)} after dropping < {MIN_RAIL_DEG}°")
        if 'railway' in gdf.columns:
            gdf['railway'] = gdf['railway'].astype(str).str.lower()
            gdf = gdf[['railway', 'geometry']].dissolve(by='railway', as_index=False)
            tick(f"railways: dissolved to {len(gdf)} types")

    gdf.to_parquet(out_path)
    tick(f"{name}.parquet  ({len(gdf)} features, {os.path.getsize(out_path)/1e6:.1f} MB)")


def process_osm(force=False):
    step("Processing OSM layers …")

    if not os.path.exists(OSM_PATH):
        print(f"     WARNING: {OSM_PATH} not found — all OSM layers skipped.")
        return

    try:
        import pyogrio
        available = [n for n, _ in pyogrio.list_layers(OSM_PATH)]
        print(f"     Available layers: {available}")
    except Exception:
        available = []

    for name in OSM_LAYERS:
        process_osm_layer(name, available, force=force)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Preprocess DEM and OSM data to cache.')
    parser.add_argument('--force', action='store_true',
                        help='Regenerate all cached files even if they already exist')
    args = parser.parse_args()

    print(f"\n  Vector Renderer → {CACHE_DIR}/")
    if args.force:
        print("  --force: all layers will be regenerated")

    process_dem(force=args.force)
    process_osm(force=args.force)

    total = int(time.time() - _t_start)
    mm, ss = divmod(total, 60)
    print(f"\n  ✓  Done.  Total wall: {mm:02d}:{ss:02d}\n")


if __name__ == '__main__':
    main()
