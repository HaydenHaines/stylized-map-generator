"""
Stylized Map Generator — Step 4: Assemble Tiles
================================================
Crops the 3×3 tile PDFs to their geographic core (removing overlap bleed) and
assembles them into a single-page vector PDF at wall scale.

Each tile was rendered with TILE_OVERLAP_DEG of bleed on every interior edge so
that features crossing a tile boundary (rivers, roads, contours) are present in
both adjacent tiles.  Seam positions are computed by projecting the geographic
core boundary into each tile's PDF coordinate space.  Because the tiles share
the same linear geographic→point mapping (matplotlib axes fill the page after
bbox_inches='tight'), these positions are accurate to ~4 pt (~0.05 in), which
is invisible on a 9-foot wall map.

Output:
    output/assembled_map.pdf   — single-page vector PDF, 110 × 98 in

Original tile PDFs are never modified.

Usage:
    python 04_assemble_tiles.py
"""

import os, sys
import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    BOUNDS, TILE_ROWS, TILE_COLS, TILE_OVERLAP_DEG,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET, OUTPUT_DIR,
)

TILES_DIR = os.path.join(OUTPUT_DIR, 'tiles')
OUT_PATH  = os.path.join(OUTPUT_DIR, 'assembled_map.pdf')

WALL_W_PT = WALL_WIDTH_FEET  * 12 * 72   # 7 920 pt = 110 in
WALL_H_PT = WALL_HEIGHT_FEET * 12 * 72   # 7 056 pt =  98 in
CORE_W_PT = WALL_W_PT / TILE_COLS        # target core width  per column
CORE_H_PT = WALL_H_PT / TILE_ROWS        # target core height per row

# ─── Geographic helpers ───────────────────────────────────────────────────────

full_dlon = BOUNDS['east']  - BOUNDS['west']
full_dlat = BOUNDS['north'] - BOUNDS['south']
tile_dlon  = full_dlon / TILE_COLS
tile_dlat  = full_dlat / TILE_ROWS


def tile_geo(row, col):
    """Return (west, east, south, north) of a tile including bleed."""
    n = BOUNDS['north'] - row       * tile_dlat
    s = BOUNDS['north'] - (row + 1) * tile_dlat
    w = BOUNDS['west']  + col       * tile_dlon
    e = BOUNDS['west']  + (col + 1) * tile_dlon
    return (max(BOUNDS['west'],  w - TILE_OVERLAP_DEG),
            min(BOUNDS['east'],  e + TILE_OVERLAP_DEG),
            max(BOUNDS['south'], s - TILE_OVERLAP_DEG),
            min(BOUNDS['north'], n + TILE_OVERLAP_DEG))


def lon_to_x(lon, west, east, pw):
    """Geographic longitude → PDF x-coordinate (points) in a tile."""
    return (lon - west) / (east - west) * pw


def lat_to_y(lat, south, north, ph):
    """Geographic latitude → PDF y-coordinate (points, top-origin) in a tile."""
    return (north - lat) / (north - south) * ph


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n  Assembling {TILE_ROWS}×{TILE_COLS} tiles → {OUT_PATH}")
    print(f"  Assembled page: {WALL_W_PT/72:.2f} × {WALL_H_PT/72:.2f} in\n")

    # Load all tile PDFs
    docs  = {}
    dims  = {}
    for r in range(TILE_ROWS):
        for c in range(TILE_COLS):
            path = os.path.join(TILES_DIR, f'tile_{r}_{c}.pdf')
            doc  = fitz.open(path)
            docs[(r, c)] = doc
            dims[(r, c)] = (doc[0].rect.width, doc[0].rect.height)
            print(f"  loaded tile({r},{c}): {dims[(r,c)][0]:.1f} × {dims[(r,c)][1]:.1f} pt")

    # ── Compute crop rect for each tile ──────────────────────────────────────
    # Each tile is cropped from its bleed-extended bounds down to the core
    # geographic extent (no overlap bleed).  The crop is expressed in the
    # tile's own PDF point coordinates.
    print()
    crops = {}
    for r in range(TILE_ROWS):
        for c in range(TILE_COLS):
            w, e, s, n = tile_geo(r, c)
            pw, ph     = dims[(r, c)]

            # Core geographic boundaries for this tile
            core_west  = BOUNDS['west'] + c * tile_dlon       if c > 0            else w
            core_east  = BOUNDS['west'] + (c + 1) * tile_dlon if c < TILE_COLS-1  else e
            core_north = BOUNDS['north'] - r * tile_dlat       if r > 0            else n
            core_south = BOUNDS['north'] - (r + 1) * tile_dlat if r < TILE_ROWS-1 else s

            # Map core boundaries to PDF points inside this tile
            x0 = lon_to_x(core_west,  w, e, pw)
            x1 = lon_to_x(core_east,  w, e, pw)
            y0 = lat_to_y(core_north, s, n, ph)   # top-origin: north → small y
            y1 = lat_to_y(core_south, s, n, ph)   # south → large y

            crops[(r, c)] = fitz.Rect(x0, y0, x1, y1)
            print(f"  tile({r},{c})  crop x=[{x0:.1f}, {x1:.1f}]  y=[{y0:.1f}, {y1:.1f}]"
                  f"  → {x1-x0:.1f} × {y1-y0:.1f} pt core")

    # ── Assemble ──────────────────────────────────────────────────────────────
    print(f"\n  Building assembled PDF …")
    out_doc  = fitz.open()
    out_page = out_doc.new_page(width=WALL_W_PT, height=WALL_H_PT)

    for r in range(TILE_ROWS):
        for c in range(TILE_COLS):
            target = fitz.Rect(
                c * CORE_W_PT,       r * CORE_H_PT,
                (c+1) * CORE_W_PT,   (r+1) * CORE_H_PT,
            )
            out_page.show_pdf_page(
                target, docs[(r, c)], 0,
                clip=crops[(r, c)],
                keep_proportion=False,  # <0.2% stretch — imperceptible at wall scale
            )
            print(f"  placed tile({r},{c}) → {target}")

    out_doc.save(OUT_PATH, garbage=4, deflate=True)
    out_doc.close()
    for doc in docs.values():
        doc.close()

    size_mb = os.path.getsize(OUT_PATH) / 1e6
    print(f"\n  ✓  Assembled map saved: {OUT_PATH}  ({size_mb:.1f} MB)")
    print(f"     Page: {WALL_W_PT/72:.2f} × {WALL_H_PT/72:.2f} in\n")


if __name__ == '__main__':
    main()
