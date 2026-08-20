"""
Stylized Map Generator — Step 3: Tile Render
=============================================
Divides BOUNDS into a TILE_ROWS × TILE_COLS grid and renders each tile as an
independent PDF at full 900 DPI print specs using 02_render_map.py.

Tiles overlap by TILE_OVERLAP_DEG on each edge to prevent seam gaps when panels
are assembled.  Each tile is rendered in its own subprocess; up to TILE_MAX_WORKERS
run in parallel.

Output:
    output/tiles/tile_R_C.pdf   — one PDF per tile (R = row, C = col)
    output/tiles/tile_R_C.log   — stdout/stderr log for that tile

Usage:
    python 03_tile_render.py
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    BOUNDS,
    TILE_COLS, TILE_ROWS, TILE_OVERLAP_DEG, TILE_MAX_WORKERS,
    OUTPUT_DIR,
)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TILES_DIR   = os.path.join(OUTPUT_DIR, 'tiles')
os.makedirs(TILES_DIR, exist_ok=True)


def compute_tile_bounds():
    """Return [(row, col, bounds_dict), ...] for each tile, top-left origin."""
    west  = BOUNDS['west']
    east  = BOUNDS['east']
    south = BOUNDS['south']
    north = BOUNDS['north']

    tile_dlon = (east  - west)  / TILE_COLS
    tile_dlat = (north - south) / TILE_ROWS

    tiles = []
    for row in range(TILE_ROWS):
        for col in range(TILE_COLS):
            # Tile core edges (row 0 = northernmost)
            t_north = north - row       * tile_dlat
            t_south = north - (row + 1) * tile_dlat
            t_west  = west  + col       * tile_dlon
            t_east  = west  + (col + 1) * tile_dlon

            # Expand by overlap bleed; clamp to full bounds
            t_north = min(north, t_north + TILE_OVERLAP_DEG)
            t_south = max(south, t_south - TILE_OVERLAP_DEG)
            t_west  = max(west,  t_west  - TILE_OVERLAP_DEG)
            t_east  = min(east,  t_east  + TILE_OVERLAP_DEG)

            tiles.append((row, col, {
                'west': round(t_west,  6),
                'east': round(t_east,  6),
                'south': round(t_south, 6),
                'north': round(t_north, 6),
            }))
    return tiles


def render_tile(row, col, bounds):
    out_pdf = os.path.join(TILES_DIR, f'tile_{row}_{col}.pdf')
    log_path = os.path.join(TILES_DIR, f'tile_{row}_{col}.log')

    cmd = [
        sys.executable, '02_render_map.py',
        '--tile-bounds', json.dumps(bounds),
        '--tile-output',  out_pdf,
    ]

    t0 = time.time()
    with open(log_path, 'w') as log:
        result = subprocess.run(cmd, stdout=log, stderr=log, cwd=PROJECT_DIR)
    elapsed = time.time() - t0
    mm, ss = divmod(int(elapsed), 60)

    return row, col, result.returncode, out_pdf, f'{mm:02d}:{ss:02d}'


def main():
    tiles = compute_tile_bounds()
    total = len(tiles)

    print(f"\nTile render — {TILE_ROWS}×{TILE_COLS} grid, {len(tiles)} tiles total")
    print(f"Max parallel workers : {TILE_MAX_WORKERS}")
    print(f"Output               : {TILES_DIR}/\n")

    for row, col, b in tiles:
        print(f"  tile ({row},{col})  "
              f"lon [{b['west']:.4f} → {b['east']:.4f}]  "
              f"lat [{b['south']:.4f} → {b['north']:.4f}]")
    print()

    t_wall = time.time()
    completed = 0
    failed    = 0

    skipped = [(r, c) for r, c, _ in tiles
               if os.path.exists(os.path.join(TILES_DIR, f'tile_{r}_{c}.pdf'))]
    pending = [(r, c, b) for r, c, b in tiles
               if not os.path.exists(os.path.join(TILES_DIR, f'tile_{r}_{c}.pdf'))]

    for r, c in skipped:
        print(f"  –  tile ({r},{c}) already exists, skipping.")
    if skipped:
        print()

    total = len(pending)
    if total == 0:
        print("  All tiles already rendered.\n")
        return

    with ThreadPoolExecutor(max_workers=TILE_MAX_WORKERS) as ex:
        futures = {
            ex.submit(render_tile, r, c, b): (r, c)
            for r, c, b in pending
        }
        print(f"  [{time.strftime('%H:%M:%S')}] All {total} tiles submitted.\n")

        for fut in as_completed(futures):
            row, col, rc, path, elapsed = fut.result()
            completed += 1
            if rc == 0:
                print(f"  ✓  [{time.strftime('%H:%M:%S')}] tile ({row},{col}) done in {elapsed}  →  {path}")
            else:
                failed += 1
                log_path = path.replace('.pdf', '.log')
                print(f"  ✗  [{time.strftime('%H:%M:%S')}] tile ({row},{col}) FAILED (exit {rc}) — see {log_path}")

    wall = time.time() - t_wall
    wm, ws = divmod(int(wall), 60)
    print(f"\n  {completed - failed}/{total} tiles succeeded in {wm:02d}:{ws:02d} wall time.\n")
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
