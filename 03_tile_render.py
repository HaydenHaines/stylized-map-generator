"""
Tile renderer for large-format print output.

Divides the full map bounds into a grid of tiles, renders each tile at high
DPI using 02_render_map.py's slice mode, then combines all tiles into a single
full-size PDF page using PyMuPDF (preserves vector content).

Usage:
    python 03_tile_render.py                    # default: 3×3 grid at 900 DPI
    python 03_tile_render.py --cols 3 --rows 3 --dpi 900
    python 03_tile_render.py --cols 1 --rows 9  # 9 horizontal strips
"""

import argparse
import importlib.util
import math
import os
import subprocess
import sys
import time

# ── CLI ──────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(description='Tile-render the map and combine into one PDF')
ap.add_argument('--cols',    type=int, default=3,   help='Number of tile columns (default 3)')
ap.add_argument('--rows',    type=int, default=3,   help='Number of tile rows    (default 3)')
ap.add_argument('--dpi',     type=int, default=900, help='DPI per tile           (default 900)')
ap.add_argument('--config',  metavar='FILE',        help='Alternate config.py')
ap.add_argument('--output',  metavar='FILE',        help='Combined output PDF   (default output/map_tiled_{dpi}dpi.pdf)')
args = ap.parse_args()

# ── Load config ───────────────────────────────────────────────────────────────
_cfg_path = args.config or 'config.py'
_spec = importlib.util.spec_from_file_location('_cfg', os.path.abspath(_cfg_path))
_cfg  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cfg)

BOUNDS       = _cfg.BOUNDS
WALL_W_FEET  = _cfg.WALL_WIDTH_FEET
WALL_H_FEET  = _cfg.WALL_HEIGHT_FEET

COLS = args.cols
ROWS = args.rows
DPI  = args.dpi
N    = COLS * ROWS

output_pdf = args.output or f'output/map_tiled_{DPI}dpi.pdf'

# ── Compute tile bounds ───────────────────────────────────────────────────────
dlon_total = BOUNDS['east']  - BOUNDS['west']
dlat_total = BOUNDS['north'] - BOUNDS['south']
dlon_tile  = dlon_total / COLS
dlat_tile  = dlat_total / ROWS

tiles = []
for row in range(ROWS):          # row 0 = north-most
    for col in range(COLS):      # col 0 = west-most
        w = BOUNDS['west']  + col       * dlon_tile
        e = BOUNDS['west']  + (col + 1) * dlon_tile
        n = BOUNDS['north'] - row       * dlat_tile
        s = BOUNDS['north'] - (row + 1) * dlat_tile
        tiles.append({'row': row, 'col': col, 'w': w, 's': s, 'e': e, 'n': n})

tiles_dir = 'output/tiles'
os.makedirs(tiles_dir, exist_ok=True)
os.makedirs('output', exist_ok=True)

# ── Render each tile ──────────────────────────────────────────────────────────
t_start = time.time()
print(f'\nTile render: {ROWS}×{COLS} grid ({N} tiles) at {DPI} DPI')
print(f'Full wall:   {WALL_W_FEET:.3f} × {WALL_H_FEET:.3f} ft')
tile_w = WALL_W_FEET * 12 / COLS
tile_h = WALL_H_FEET * 12 / ROWS
print(f'Each tile:   {tile_w:.1f} × {tile_h:.1f} in @ {DPI} DPI')
cos_lat = math.cos(math.radians((BOUNDS['north'] + BOUNDS['south']) / 2))
est_px_w = tile_w * DPI
est_px_h = tile_h * DPI
est_gb   = est_px_w * est_px_h * 4 / 1e9  # rough RGBA buffer
print(f'             ≈ {est_px_w:.0f}×{est_px_h:.0f} px, ~{est_gb:.1f} GB hillshade buffer\n')

tile_pdfs = []
for i, tile in enumerate(tiles):
    row, col = tile['row'], tile['col']
    out_dir  = os.path.join(tiles_dir, f'r{row}c{col}')
    os.makedirs(out_dir, exist_ok=True)
    dest_pdf = os.path.join(tiles_dir, f'tile_{i+1:02d}_r{row}c{col}.pdf')

    print(f'── Tile {i+1}/{N}  (row={row}, col={col}) ──────────────────')
    print(f'   bounds: W={tile["w"]:.4f} S={tile["s"]:.4f} E={tile["e"]:.4f} N={tile["n"]:.4f}')

    cmd = [
        sys.executable, '02_render_map.py',
        '--preview',                    # enables SLICE_MODE when --slice is set
        '--slice', f'{tile["w"]},{tile["s"]},{tile["e"]},{tile["n"]}',
        '--dpi',    str(DPI),
        '--wall-w', str(WALL_W_FEET),   # full wall dims so slice scaling is correct
        '--wall-h', str(WALL_H_FEET),
        '--output-dir', out_dir,
    ]
    if args.config:
        cmd += ['--config', args.config]

    t0 = time.time()
    result = subprocess.run(cmd, check=False)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f'\n  ✘  Tile {i+1} FAILED (exit {result.returncode}) — aborting.')
        sys.exit(1)

    src = os.path.join(out_dir, 'slice_preview.pdf')
    if not os.path.exists(src):
        print(f'\n  ✘  Expected output not found: {src}')
        sys.exit(1)

    os.rename(src, dest_pdf)
    tile_pdfs.append(dest_pdf)
    print(f'   ✓  saved to {dest_pdf}  ({elapsed/60:.1f} min)\n')

# ── Combine tiles into a single full-size PDF page ────────────────────────────
print(f'── Combining {N} tiles into {output_pdf} …')
try:
    import fitz   # PyMuPDF

    # Page size in points (1 pt = 1/72 inch)
    page_w_pt = WALL_W_FEET * 12 * 72
    page_h_pt = WALL_H_FEET * 12 * 72
    tile_w_pt = page_w_pt / COLS
    tile_h_pt = page_h_pt / ROWS

    combined = fitz.open()
    page = combined.new_page(width=page_w_pt, height=page_h_pt)

    for i, (tile_path, tile) in enumerate(zip(tile_pdfs, tiles)):
        row, col = tile['row'], tile['col']
        x0 = col       * tile_w_pt
        y0 = row       * tile_h_pt   # PyMuPDF: y=0 is top
        x1 = x0 + tile_w_pt
        y1 = y0 + tile_h_pt
        rect = fitz.Rect(x0, y0, x1, y1)

        src = fitz.open(tile_path)
        page.show_pdf_page(rect, src, 0)
        src.close()
        print(f'   placed tile {i+1}/{N}  @ ({x0:.0f},{y0:.0f})–({x1:.0f},{y1:.0f}) pt')

    combined.save(output_pdf, garbage=4, deflate=True)
    combined.close()
    print(f'\n✓  Combined PDF: {output_pdf}')
    print(f'   Page size: {WALL_W_FEET*12:.2f} × {WALL_H_FEET*12:.2f} in')

except ImportError:
    # Fallback: multi-page PDF (one page per tile)
    fallback = output_pdf.replace('.pdf', '_pages.pdf')
    try:
        from pypdf import PdfWriter
        writer = PdfWriter()
        for p in tile_pdfs:
            from pypdf import PdfReader
            writer.append(PdfReader(p))
        with open(fallback, 'wb') as f:
            writer.write(f)
        print(f'\n✓  Multi-page PDF (PyMuPDF not available): {fallback}')
    except ImportError:
        print('\n⚠  No PDF combiner available. Individual tiles saved to:')
        for p in tile_pdfs:
            print(f'   {p}')

total = time.time() - t_start
print(f'\nDone.  Total wall: {total/60:.1f} min')
