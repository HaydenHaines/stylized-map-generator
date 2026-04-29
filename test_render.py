"""
test_render.py — smoke test with synthetic DEM data
====================================================
Generates a fake but geographically-correct DEM for the Oklahoma corridor
using a simple terrain model (ridge + plains), then runs the full render
pipeline.  Use this to verify everything works before running the real
01_download_data.py download (which requires network + ~10 min).

Output: output/map_preview_TEST.png
"""

import os
import sys
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon
import pandas as pd

os.makedirs('data', exist_ok=True)
os.makedirs('output', exist_ok=True)

from config import BOUNDS, DATA_DIR, DEM_PATH, OSM_PATH

print("Generating synthetic DEM …")

# Resolution: ~500m for fast test (real data is 30m)
res_deg = 0.005   # ~500m at 36°N
lons = np.arange(BOUNDS['west'], BOUNDS['east'],  res_deg)
lats = np.arange(BOUNDS['north'], BOUNDS['south'], -res_deg)   # N→S
W, H = len(lons), len(lats)

Xg, Yg = np.meshgrid(lons, lats)

# Synthetic terrain for the Oklahoma corridor:
# - Gently rolling plains, slightly higher in the west (OKC side)
# - A low ridge running NE–SW (mimics the Arbuckle / Cross Timbers uplift)
# - Add Perlin-style noise via overlaid sine waves

base_elev = 280  # metres (roughly correct for central OK)
west_tilt = (BOUNDS['west'] - Xg) * 15    # higher in west (Wichita Mtns direction)
ridge = 40 * np.exp(-((Xg - (-96.7))**2 / 0.3 + (Yg - 35.7)**2 / 0.4))

# Multi-scale noise
rng = np.random.default_rng(42)
noise = (
    18 * np.sin(Xg * 22 + 0.5) * np.cos(Yg * 18 - 0.3) +
    9  * np.sin(Xg * 55 - 1.2) * np.cos(Yg * 47 + 0.8) +
    5  * np.sin(Xg * 110)      * np.cos(Yg * 95)
)

dem_synth = base_elev + west_tilt + ridge + noise
dem_synth = dem_synth.astype(np.float32)

transform = from_bounds(
    BOUNDS['west'], BOUNDS['south'], BOUNDS['east'], BOUNDS['north'],
    W, H
)

with rasterio.open(
    DEM_PATH, 'w',
    driver='GTiff',
    height=H, width=W,
    count=1,
    dtype=np.float32,
    crs=CRS.from_epsg(4326),
    transform=transform,
) as dst:
    dst.write(dem_synth, 1)

print(f"  ✓  DEM written: {H}×{W} px, "
      f"{dem_synth.min():.0f}–{dem_synth.max():.0f} m")

print("Generating synthetic OSM vector data …")

import pyogrio

# ── Roads: I-40 runs roughly E–W through the corridor ──────────────────────
road_features = {
    'geometry': [
        LineString([(-97.45, 35.46), (-97.0, 35.46), (-96.5, 35.47), (-95.85, 35.50)]),  # I-40
        LineString([(-97.45, 35.85), (-97.0, 35.90), (-96.5, 35.91), (-95.85, 35.95)]),  # US-412
        LineString([(-97.0, 35.20), (-97.0, 35.65), (-97.0, 36.40)]),   # US-177 N–S
        LineString([(-96.3, 35.20), (-96.3, 36.40)]),                    # OK-99 N–S
        LineString([(-96.7, 35.50), (-96.2, 35.75), (-95.9, 36.00)]),   # diagonal road
    ],
    'highway': ['motorway', 'primary', 'primary', 'secondary', 'tertiary'],
    'name': ['Interstate 40', 'US-412', 'US-177', 'OK-99', 'OK-48'],
    'ref': ['I-40', 'US-412', 'US-177', 'OK-99', 'OK-48'],
}
roads_gdf = gpd.GeoDataFrame(road_features, crs='EPSG:4326')
roads_gdf.to_file(OSM_PATH, layer='roads', engine='pyogrio', driver='GPKG')

# ── Waterways: Cimarron + Arkansas + Canadian rivers ───────────────────────
ww_features = {
    'geometry': [
        LineString([(-97.5, 36.18), (-97.0, 36.15), (-96.5, 36.10), (-95.85, 36.05)]),  # Cimarron
        LineString([(-97.5, 35.58), (-97.0, 35.52), (-96.5, 35.48), (-95.85, 35.40)]),  # Canadian
        LineString([(-96.7, 36.40), (-96.7, 36.10), (-96.6, 35.80), (-96.5, 35.50)]),   # Deep Fork
    ],
    'waterway': ['river', 'river', 'stream'],
    'name': ['Cimarron River', 'Canadian River', 'Deep Fork'],
}
ww_gdf = gpd.GeoDataFrame(ww_features, crs='EPSG:4326')
ww_gdf.to_file(OSM_PATH, layer='waterways', engine='pyogrio', driver='GPKG', mode='a')

# ── Railways ────────────────────────────────────────────────────────────────
rail_features = {
    'geometry': [
        LineString([(-97.45, 35.52), (-97.0, 35.54), (-96.5, 35.57), (-95.85, 35.58)]),
    ],
    'railway': ['rail'],
    'name': ['BNSF Rail Corridor'],
}
rail_gdf = gpd.GeoDataFrame(rail_features, crs='EPSG:4326')
rail_gdf.to_file(OSM_PATH, layer='railways', engine='pyogrio', driver='GPKG', mode='a')

# ── Settlements ─────────────────────────────────────────────────────────────
places_data = {
    'geometry': [
        Point(-97.52, 35.47),   # OKC (just outside west edge — label bleeds in)
        Point(-95.99, 36.15),   # Tulsa
        Point(-96.68, 35.74),   # Stroud
        Point(-96.93, 35.52),   # Shawnee
        Point(-96.39, 36.12),   # Sapulpa
        Point(-96.78, 36.10),   # Guthrie
        Point(-97.09, 35.39),   # Norman
        Point(-96.11, 35.98),   # Broken Arrow
        Point(-96.55, 35.35),   # Ada
        Point(-97.44, 36.40),   # Enid
    ],
    'place': ['city', 'city', 'town', 'town', 'town', 'town', 'town', 'town', 'town', 'city'],
    'name': ['Oklahoma City', 'Tulsa', 'Stroud', 'Shawnee', 'Sapulpa',
             'Guthrie', 'Norman', 'Broken Arrow', 'Ada', 'Enid'],
    'population': [680000, 411000, 3000, 32000, 21000, 11000, 128000, 113000, 18000, 50000],
}
places_gdf = gpd.GeoDataFrame(places_data, crs='EPSG:4326')
places_gdf.to_file(OSM_PATH, layer='places', engine='pyogrio', driver='GPKG', mode='a')

print(f"  ✓  OSM layers written to {OSM_PATH}")

print("\n✓  Synthetic data ready.  Now run:  python3 02_render_map.py")
