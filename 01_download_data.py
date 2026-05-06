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
from pathlib import Path

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

import py3dep
import osmnx as ox
import geopandas as gpd
import pyogrio        # replaces fiona for reading/writing GeoPackage

from render_config import RenderJob, RenderPaths, job_from_config

# ── Helper ───────────────────────────────────────────────────────────────────
def section(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")

def run(job: RenderJob, paths: RenderPaths):
    """Download DEM + OSM data into paths.data_dir. Skips if files already exist."""
    paths.makedirs()
    BOUNDS           = job.bounds.to_dict()
    DEM_PATH         = str(paths.dem_path)
    OSM_PATH         = str(paths.osm_path)
    DEM_RESOLUTION_M = job.dem_resolution_m

    # ── 1. DEM ────────────────────────────────────────────────────────────────
    section("1 / 2  Downloading elevation data (USGS 3DEP)")
    print(f"  Bounds : {BOUNDS['south']:.2f}°N – {BOUNDS['north']:.2f}°N, "
          f"{abs(BOUNDS['east']):.2f}°W – {abs(BOUNDS['west']):.2f}°W")
    print(f"  Resolution : {DEM_RESOLUTION_M} m")
    print("  This may take 2–5 minutes depending on your connection …\n")

    bbox = (BOUNDS['west'], BOUNDS['south'], BOUNDS['east'], BOUNDS['north'])
    try:
        dem = py3dep.get_dem(bbox, resolution=DEM_RESOLUTION_M, crs="EPSG:4326")
        dem.rio.to_raster(DEM_PATH)
        print(f"  ✓  DEM saved → {DEM_PATH}")
        print(f"     Shape : {dem.shape[1]} × {dem.shape[0]} px")
        print(f"     Elevation range : {float(dem.min()):.0f} – {float(dem.max()):.0f} m")
    except Exception as e:
        print(f"\n  ERROR downloading DEM: {e}")
        raise

    # ── 2. OSM ────────────────────────────────────────────────────────────────
    section("2 / 2  Downloading OpenStreetMap data")
    N, S, E, W = BOUNDS['north'], BOUNDS['south'], BOUNDS['east'], BOUNDS['west']
    BBOX = (W, S, E, N)
    layers_saved = []

    print("  Roads …")
    try:
        G = ox.graph_from_bbox(BBOX, network_type='drive', retain_all=True, simplify=True)
        nodes, edges = ox.graph_to_gdfs(G)
        roads = edges[['geometry', 'highway', 'name', 'ref']].copy()
        roads['highway'] = roads['highway'].apply(
            lambda x: x[0] if isinstance(x, list) else x
        )
        roads.to_file(OSM_PATH, layer='roads', engine='pyogrio', driver='GPKG')
        layers_saved.append('roads')
        print(f"     ✓  {len(roads):,} road segments")
    except Exception as e:
        print(f"     ⚠  Roads failed: {e}")

    print("  Waterways …")
    try:
        ww = ox.features_from_bbox(BBOX, tags={'waterway': ['river', 'stream', 'canal', 'drain']})
        ww = ww[ww.geometry.geom_type.isin(['LineString', 'MultiLineString'])].copy()
        keep_cols = [c for c in ['geometry', 'waterway', 'name'] if c in ww.columns]
        ww[keep_cols].to_file(OSM_PATH, layer='waterways', engine='pyogrio', driver='GPKG', mode='a')
        layers_saved.append('waterways')
        print(f"     ✓  {len(ww):,} waterway segments")
    except Exception as e:
        print(f"     ⚠  Waterways failed: {e}")

    print("  Water bodies …")
    try:
        wb = ox.features_from_bbox(BBOX, tags={'natural': 'water'})
        wb = wb[wb.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])].copy()
        if len(wb) > 0:
            keep_cols = [c for c in ['geometry', 'water', 'name'] if c in wb.columns]
            wb[keep_cols].to_file(OSM_PATH, layer='water_bodies', engine='pyogrio', driver='GPKG', mode='a')
            layers_saved.append('water_bodies')
            print(f"     ✓  {len(wb):,} water bodies")
        else:
            print("     ·  No water bodies found")
    except Exception as e:
        print(f"     ⚠  Water bodies failed: {e}")

    print("  Railways …")
    try:
        rail = ox.features_from_bbox(BBOX, tags={'railway': ['rail', 'narrow_gauge', 'preserved']})
        rail = rail[rail.geometry.geom_type.isin(['LineString', 'MultiLineString'])].copy()
        keep_cols = [c for c in ['geometry', 'railway', 'name'] if c in rail.columns]
        rail[keep_cols].to_file(OSM_PATH, layer='railways', engine='pyogrio', driver='GPKG', mode='a')
        layers_saved.append('railways')
        print(f"     ✓  {len(rail):,} railway segments")
    except Exception as e:
        print(f"     ⚠  Railways failed: {e}")

    print("  Settlements …")
    try:
        places = ox.features_from_bbox(BBOX, tags={'place': ['city', 'town', 'village', 'hamlet']})
        places = places[places.geometry.geom_type == 'Point'].copy()
        keep_cols = [c for c in ['geometry', 'place', 'name', 'population'] if c in places.columns]
        places[keep_cols].to_file(OSM_PATH, layer='places', engine='pyogrio', driver='GPKG', mode='a')
        layers_saved.append('places')
        print(f"     ✓  {len(places):,} settlements")
    except Exception as e:
        print(f"     ⚠  Settlements failed: {e}")

    print(f"\n{'═' * 55}")
    print(f"  Download complete.")
    print(f"  DEM  → {DEM_PATH}")
    print(f"  OSM  → {OSM_PATH}  (layers: {', '.join(layers_saved)})")
    print(f"{'═' * 55}")


if __name__ == '__main__':
    run(job_from_config(), RenderPaths(Path('.')))
