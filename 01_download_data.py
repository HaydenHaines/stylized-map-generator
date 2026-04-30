"""
Oklahoma Topo Map — Step 1: Download Data
==========================================
Run this once to pull all geographic data.  After it completes,
run 02_render_map.py as many times as you like (no re-download needed).

Data sources used (all free, no API keys required):
  • USGS 3DEP  – Digital elevation model via py3dep
  • OpenStreetMap – Roads, rivers, rails, towns via osmnx

Usage:
    cd oklahoma_topo_map
    pip install -r requirements.txt
    python 01_download_data.py
"""

import os
import sys

# ── Confirm libraries before doing anything ──────────────────────────────────
missing = []
for pkg in ['py3dep', 'rioxarray', 'osmnx', 'geopandas', 'rasterio', 'pyogrio']:
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)

if missing:
    print("ERROR: Missing packages:", ', '.join(missing))
    print("Fix:   pip install -r requirements.txt")
    sys.exit(1)

import argparse
import importlib.util as _imputil
import py3dep
import osmnx as ox
import geopandas as gpd
import pyogrio        # replaces fiona for reading/writing GeoPackage

# ── Config loading (--config pre-parsed before any config values are read) ────
def _load_config_module(path):
    spec = _imputil.spec_from_file_location('_map_config', os.path.abspath(path))
    mod = _imputil.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument('--config', metavar='FILE')
_pre_args, _ = _pre.parse_known_args()

if _pre_args.config:
    _cfg = _load_config_module(_pre_args.config)
else:
    import config as _cfg

BOUNDS              = _cfg.BOUNDS
DEM_PATH            = _cfg.DEM_PATH
OSM_PATH            = _cfg.OSM_PATH
DATA_DIR            = _cfg.DATA_DIR
DEM_RESOLUTION_M    = _cfg.DEM_RESOLUTION_M
MIN_WATER_BODY_AREA_M2 = _cfg.MIN_WATER_BODY_AREA_M2

# ── CLI overrides (all default to config.py values) ──────────────────────────
_ap = argparse.ArgumentParser(
    description='Download DEM + OSM data for stylized-map-generator',
    # Allow interspersed args so negative numbers aren't parsed as flags
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
_ap.add_argument('--config', metavar='FILE',
                 help='Path to an alternate config.py (replaces the default config.py)')
_ap.add_argument('--bounds', metavar='W,S,E,N',
                 help='Bounding box as west,south,east,north decimal degrees '
                      '(overrides config.BOUNDS). Use = syntax with negatives: '
                      '--bounds=-97.0,35.0,-96.0,36.0)')
_ap.add_argument('--resolution', type=int,
                 help='DEM resolution in metres (overrides config.DEM_RESOLUTION_M)')
_ap.add_argument('--output-dir', metavar='DIR',
                 help='Directory for downloaded data (overrides config.DATA_DIR)')
_cli = _ap.parse_args()

if _cli.bounds:
    _w, _s, _e, _n = map(float, _cli.bounds.split(','))
    BOUNDS = {'west': _w, 'south': _s, 'east': _e, 'north': _n}
if _cli.resolution:
    DEM_RESOLUTION_M = _cli.resolution
if _cli.output_dir:
    DATA_DIR = _cli.output_dir
    DEM_PATH = f'{DATA_DIR}/dem.tif'
    OSM_PATH = f'{DATA_DIR}/osm_data.gpkg'

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs('output', exist_ok=True)

# Remove stale GPKG so real download always starts from a clean slate.
# Without this, test_render.py synthetic data contaminates the place layer.
if os.path.exists(OSM_PATH):
    os.remove(OSM_PATH)
    print(f"  · Removed stale {OSM_PATH} (fresh download)")

# ── Helper ───────────────────────────────────────────────────────────────────
def section(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")

# ═══════════════════════════════════════════════════════
#  1. DIGITAL ELEVATION MODEL (DEM)
# ═══════════════════════════════════════════════════════
section("1 / 2  Downloading elevation data (USGS 3DEP)")

print(f"  Bounds : {BOUNDS['south']:.2f}°N – {BOUNDS['north']:.2f}°N, "
      f"{abs(BOUNDS['east']):.2f}°W – {abs(BOUNDS['west']):.2f}°W")
print(f"  Resolution : {DEM_RESOLUTION_M} m")
print("  This may take 2–5 minutes depending on your connection …\n")

bbox = (BOUNDS['west'], BOUNDS['south'], BOUNDS['east'], BOUNDS['north'])

try:
    dem = py3dep.get_dem(bbox, resolution=DEM_RESOLUTION_M, crs="EPSG:4326")
    dem.rio.to_raster(DEM_PATH)
    # Verify on-disk dimensions match in-memory (py3dep cache can silently return
    # a coarser previously-cached raster if the TIFF write doesn't overwrite cleanly)
    import rasterio as _rio
    with _rio.open(DEM_PATH) as _r:
        disk_w, disk_h = _r.width, _r.height
    mem_w, mem_h = dem.shape[1], dem.shape[0]
    if disk_w != mem_w or disk_h != mem_h:
        print(f"\n  WARNING: on-disk DEM ({disk_w}×{disk_h}) differs from in-memory "
              f"({mem_w}×{mem_h}). Deleting and re-saving …")
        os.remove(DEM_PATH)
        dem.rio.to_raster(DEM_PATH)
    print(f"  ✓  DEM saved → {DEM_PATH}")
    print(f"     Shape : {mem_w} × {mem_h} px")
    print(f"     Elevation range : {float(dem.min()):.0f} – {float(dem.max()):.0f} m")
except Exception as e:
    print(f"\n  ERROR downloading DEM: {e}")
    print("  Check your internet connection and try again.")
    sys.exit(1)

# ═══════════════════════════════════════════════════════
#  2. OPENSTREETMAP VECTOR DATA
# ═══════════════════════════════════════════════════════
section("2 / 2  Downloading OpenStreetMap data")

N, S, E, W = BOUNDS['north'], BOUNDS['south'], BOUNDS['east'], BOUNDS['west']
# osmnx 2.x: bbox = (left, bottom, right, top) = (west, south, east, north)
BBOX = (W, S, E, N)

layers_saved = []

# ── 2a. Road network ─────────────────────────────────────────────────────────
print("  Roads …")
try:
    G = ox.graph_from_bbox(
        BBOX,
        network_type='drive',
        retain_all=True,
        simplify=True,
    )
    nodes, edges = ox.graph_to_gdfs(G)
    roads = edges[['geometry', 'highway', 'name', 'ref']].copy()
    # Flatten any list-type values in 'highway' (OSM sometimes returns lists)
    roads['highway'] = roads['highway'].apply(
        lambda x: x[0] if isinstance(x, list) else x
    )
    roads.to_file(OSM_PATH, layer='roads', engine='pyogrio', driver='GPKG')
    layers_saved.append('roads')
    print(f"     ✓  {len(roads):,} road segments")
except Exception as e:
    print(f"     ⚠  Roads failed: {e}")

# ── 2b. Waterways (rivers, creeks, streams) ───────────────────────────────────
print("  Waterways …")
try:
    ww = ox.features_from_bbox(
        BBOX,
        tags={'waterway': ['river', 'stream', 'canal', 'drain']},
    )
    # osmnx v2: MultiIndex (element_type, osmid). Keep only 'way' elements —
    # 'relation' elements are route relations with simplified straight geometry.
    if hasattr(ww.index, 'get_level_values'):
        ww = ww[ww.index.get_level_values(0) == 'way'].copy()
    ww.reset_index(drop=True, inplace=True)
    ww = ww[ww.geometry.geom_type.isin(['LineString', 'MultiLineString'])].copy()
    keep_cols = [c for c in ['geometry', 'waterway', 'name'] if c in ww.columns]
    ww[keep_cols].to_file(OSM_PATH, layer='waterways', engine='pyogrio', driver='GPKG', mode='a')
    layers_saved.append('waterways')
    print(f"     ✓  {len(ww):,} waterway segments")
except Exception as e:
    print(f"     ⚠  Waterways failed: {e}")

# ── 2c. Water bodies (lakes, reservoirs, ponds) ───────────────────────────────
print("  Water bodies …")
try:
    wb = ox.features_from_bbox(
        BBOX,
        tags={'natural': 'water'},
    )
    # Keep only 'way'/'relation' polygon elements; drop 'node' points
    if hasattr(wb.index, 'get_level_values'):
        wb = wb[wb.index.get_level_values(0).isin(['way', 'relation'])].copy()
    wb.reset_index(drop=True, inplace=True)
    wb = wb[wb.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])].copy()
    if MIN_WATER_BODY_AREA_M2 > 0 and len(wb) > 0:
        before = len(wb)
        wb = wb[wb.to_crs(epsg=5070).geometry.area >= MIN_WATER_BODY_AREA_M2].copy()
        print(f"     · area filter: {before:,} → {len(wb):,} polygons "
              f"(kept ≥ {MIN_WATER_BODY_AREA_M2/1e4:.0f} ha)")
    if len(wb) > 0:
        keep_cols = [c for c in ['geometry', 'water', 'name'] if c in wb.columns]
        wb[keep_cols].to_file(OSM_PATH, layer='water_bodies', engine='pyogrio', driver='GPKG', mode='a')
        layers_saved.append('water_bodies')
        print(f"     ✓  {len(wb):,} water bodies")
    else:
        print("     ·  No water bodies found")
except Exception as e:
    print(f"     ⚠  Water bodies failed: {e}")

# ── 2d. Railways ──────────────────────────────────────────────────────────────
print("  Railways …")
try:
    rail = ox.features_from_bbox(
        BBOX,
        tags={'railway': ['rail', 'narrow_gauge', 'preserved']},
    )
    # osmnx v2: MultiIndex (element_type, osmid). Keep only 'way' elements —
    # 'relation' elements are route corridors with simplified straight geometry.
    if hasattr(rail.index, 'get_level_values'):
        rail = rail[rail.index.get_level_values(0) == 'way'].copy()
    rail.reset_index(drop=True, inplace=True)
    rail = rail[rail.geometry.geom_type.isin(['LineString', 'MultiLineString'])].copy()
    keep_cols = [c for c in ['geometry', 'railway', 'name'] if c in rail.columns]
    rail[keep_cols].to_file(OSM_PATH, layer='railways', engine='pyogrio', driver='GPKG', mode='a')
    layers_saved.append('railways')
    print(f"     ✓  {len(rail):,} railway segments")
except Exception as e:
    print(f"     ⚠  Railways failed: {e}")

# ── 2e. Settlements (cities, towns, villages, hamlets) ────────────────────────
print("  Settlements …")
try:
    places = ox.features_from_bbox(
        BBOX,
        tags={'place': ['city', 'town', 'village', 'hamlet']},
    )
    # Keep only point geometries (polygon admin boundaries also match 'place' tags)
    places = places[places.geometry.geom_type == 'Point'].copy()

    # osmnx v2 returns a MultiIndex (element_type, osmid). Reset before any
    # column access so the 'element' index level can't overwrite 'place'.
    places.reset_index(drop=True, inplace=True)

    # Only keep rows where 'place' is a recognised settlement type.
    PLACE_TYPES = {'city', 'town', 'village', 'hamlet'}
    if 'place' in places.columns:
        # If the column already has the right values, keep them; otherwise try
        # to pull the value from the index or drop rows we can't classify.
        bad_mask = ~places['place'].isin(PLACE_TYPES)
        if bad_mask.any():
            # Attempt to recover from MultiIndex level 0 (element_type is not
            # a place type either, so these rows are unclassifiable — drop them)
            places = places[~bad_mask].copy()
    else:
        # 'place' tag not exposed as a column; reconstruct from index if possible
        places = places.copy()
        places['place'] = 'town'   # fallback — render as town tier

    # Only keep named settlements
    if 'name' in places.columns:
        places = places[places['name'].notna() & (places['name'] != '')].copy()

    keep_cols = [c for c in ['geometry', 'place', 'name', 'population'] if c in places.columns]
    if len(places) > 0:
        places[keep_cols].to_file(OSM_PATH, layer='places', engine='pyogrio', driver='GPKG', mode='a')
        layers_saved.append('places')
    print(f"     ✓  {len(places):,} settlements")
except Exception as e:
    print(f"     ⚠  Settlements failed: {e}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═' * 55}")
print(f"  Download complete.")
print(f"  DEM  → {DEM_PATH}")
print(f"  OSM  → {OSM_PATH}  (layers: {', '.join(layers_saved)})")
print(f"{'═' * 55}")
print("\nNext step:  python 02_render_map.py")
