"""
test_render.py — synthetic data generator + smoke test
=======================================================
When run directly (python test_render.py) it writes a synthetic DEM and OSM
dataset to the standard data paths so you can validate the pipeline without a
network round-trip.

When collected by pytest it exposes `make_synthetic_data` and a
`synth_data` fixture used by other test modules.  The module-level data
generation is **not** run during collection — real downloaded data is never
clobbered by the test suite.

Output (standalone run): output/map_preview_TEST.pdf
"""

from __future__ import annotations

import os
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, Point


def make_synthetic_data(dem_path: str, osm_path: str, bounds: dict) -> None:
    """Write a synthetic DEM + OSM GeoPackage to *dem_path* / *osm_path*."""
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS

    os.makedirs(os.path.dirname(dem_path) or '.', exist_ok=True)
    os.makedirs(os.path.dirname(osm_path) or '.', exist_ok=True)

    # ── DEM: ~500 m resolution synthetic terrain ──────────────────────────────
    res_deg = 0.005
    lons = np.arange(bounds['west'],  bounds['east'],   res_deg)
    lats = np.arange(bounds['north'], bounds['south'], -res_deg)
    W, H = len(lons), len(lats)
    Xg, Yg = np.meshgrid(lons, lats)

    base_elev = 280
    west_tilt = (bounds['west'] - Xg) * 15
    ridge = 40 * np.exp(-((Xg - (-96.7))**2 / 0.3 + (Yg - 35.7)**2 / 0.4))
    noise = (
        18 * np.sin(Xg * 22 + 0.5) * np.cos(Yg * 18 - 0.3) +
        9  * np.sin(Xg * 55 - 1.2) * np.cos(Yg * 47 + 0.8) +
        5  * np.sin(Xg * 110)      * np.cos(Yg * 95)
    )
    dem_synth = (base_elev + west_tilt + ridge + noise).astype(np.float32)

    transform = from_bounds(
        bounds['west'], bounds['south'], bounds['east'], bounds['north'], W, H,
    )
    with rasterio.open(
        dem_path, 'w', driver='GTiff',
        height=H, width=W, count=1, dtype=np.float32,
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(dem_synth, 1)

    print(f"  ✓  DEM written: {H}×{W} px, "
          f"{dem_synth.min():.0f}–{dem_synth.max():.0f} m")

    # ── OSM roads ──────────────────────────────────────────────────────────────
    W_, E_, S_, N_ = bounds['west'], bounds['east'], bounds['south'], bounds['north']
    mid_lon = (W_ + E_) / 2
    mid_lat = (S_ + N_) / 2

    roads_gdf = gpd.GeoDataFrame({
        'geometry': [
            LineString([(W_ + 0.45, S_ + 0.36), (mid_lon, S_ + 0.36),
                        (mid_lon + 0.5, S_ + 0.37), (E_ - 0.15, S_ + 0.40)]),
            LineString([(W_ + 0.45, mid_lat + 0.05), (mid_lon, mid_lat + 0.1),
                        (E_ - 0.15, mid_lat + 0.11)]),
            LineString([(mid_lon, S_ + 0.10), (mid_lon, mid_lat), (mid_lon, N_ - 0.15)]),
            LineString([(mid_lon + 0.65, S_ + 0.10), (mid_lon + 0.65, N_ - 0.15)]),
            LineString([(mid_lon + 0.25, S_ + 0.40), (mid_lon + 0.75, mid_lat + 0.05),
                        (E_ - 0.05, N_ - 0.55)]),
        ],
        'highway': ['motorway', 'primary', 'primary', 'secondary', 'tertiary'],
        'name':    ['Interstate 40', 'US-412', 'US-177', 'OK-99', 'OK-48'],
        'ref':     ['I-40', 'US-412', 'US-177', 'OK-99', 'OK-48'],
    }, crs='EPSG:4326')
    roads_gdf.to_file(osm_path, layer='roads', engine='pyogrio', driver='GPKG')

    # ── waterways ─────────────────────────────────────────────────────────────
    ww_gdf = gpd.GeoDataFrame({
        'geometry': [
            LineString([(W_ - 0.0, N_ - 0.37), (mid_lon, N_ - 0.40),
                        (mid_lon + 0.5, N_ - 0.45), (E_ - 0.15, N_ - 0.50)]),
            LineString([(W_ - 0.0, S_ + 0.48), (mid_lon, S_ + 0.42),
                        (E_ - 0.15, S_ + 0.30)]),
            LineString([(mid_lon + 0.2, N_ - 0.15), (mid_lon + 0.1, mid_lat),
                        (mid_lon, S_ + 0.40)]),
        ],
        'waterway': ['river', 'river', 'stream'],
        'name':     ['Cimarron River', 'Canadian River', 'Deep Fork'],
    }, crs='EPSG:4326')
    ww_gdf.to_file(osm_path, layer='waterways', engine='pyogrio', driver='GPKG', mode='a')

    # ── railways ──────────────────────────────────────────────────────────────
    rail_gdf = gpd.GeoDataFrame({
        'geometry': [
            LineString([(W_ + 0.45, S_ + 0.42), (mid_lon, S_ + 0.44),
                        (mid_lon + 0.5, S_ + 0.47), (E_ - 0.15, S_ + 0.48)]),
        ],
        'railway': ['rail'],
        'name':    ['BNSF Rail Corridor'],
    }, crs='EPSG:4326')
    rail_gdf.to_file(osm_path, layer='railways', engine='pyogrio', driver='GPKG', mode='a')

    # ── water bodies ──────────────────────────────────────────────────────────
    from shapely.geometry import Polygon
    wb_gdf = gpd.GeoDataFrame({
        'geometry': [
            Polygon([(mid_lon + 0.6, mid_lat + 0.5),
                     (mid_lon + 0.9, mid_lat + 0.5),
                     (mid_lon + 0.9, mid_lat + 0.7),
                     (mid_lon + 0.6, mid_lat + 0.7)]),
        ],
        'water': ['reservoir'],
        'name':  ['Keystone Lake'],
    }, crs='EPSG:4326')
    wb_gdf.to_file(osm_path, layer='water_bodies', engine='pyogrio', driver='GPKG', mode='a')

    # ── settlements ───────────────────────────────────────────────────────────
    places_gdf = gpd.GeoDataFrame({
        'geometry': [
            Point(W_ + 0.38, S_ + 0.37),
            Point(E_ - 0.01, N_ - 0.40),
            Point(mid_lon + 0.32, mid_lat + 0.24),
            Point(mid_lon - 0.07, S_ + 0.22),
            Point(mid_lon + 0.61, S_ + 0.62),
        ],
        'place': ['city', 'city', 'town', 'town', 'town'],
        'name':  ['Oklahoma City', 'Tulsa', 'Stroud', 'Shawnee', 'Sapulpa'],
        'population': [680000, 411000, 3000, 32000, 21000],
    }, crs='EPSG:4326')
    places_gdf.to_file(osm_path, layer='places', engine='pyogrio', driver='GPKG', mode='a')

    print(f"  ✓  OSM layers written to {osm_path}")


# ── Standalone entry point ────────────────────────────────────────────────────
# Running `python test_render.py` generates synthetic data at the standard
# data paths and then kicks off a preview render.
# pytest collection does NOT run this block, so real downloaded data is safe.

if __name__ == '__main__':
    import sys
    from config import BOUNDS, DEM_PATH, OSM_PATH

    os.makedirs('data',   exist_ok=True)
    os.makedirs('output', exist_ok=True)

    print("Generating synthetic DEM …")
    make_synthetic_data(DEM_PATH, OSM_PATH, BOUNDS)
    print("\n✓  Synthetic data ready.  Now run:  python3 02_render_map.py")
