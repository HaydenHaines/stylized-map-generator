"""
Stylized Map Generator — Step 4: PDF Combiner
==============================================
Composites the per-layer PDFs from Step 3 into a single final map PDF.
Layer PDFs must have transparent backgrounds (produced by 03_pdf_renderer.py).

Output:
    output/map.pdf

Layer order (bottom → top):
    paper background (filled rect, no PDF source)
    hillshade
    contours
    water_bodies
    waterways
    roads
    railways
    places
    border

Usage:
    python 04_pdf_combiner.py
    python 04_pdf_combiner.py --preview   (uses output/layers/*_preview.pdf if present)
"""

import os, sys, time, argparse
import fitz   # PyMuPDF

from config import (
    BOUNDS, WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    PALETTE, SLICE_BOUNDS, OUTPUT_DIR,
)

LAYERS_DIR = os.path.join(OUTPUT_DIR, 'layers')
OUT_PATH   = os.path.join(OUTPUT_DIR, 'map.pdf')

WALL_W_PT = WALL_WIDTH_FEET  * 12 * 72
WALL_H_PT = WALL_HEIGHT_FEET * 12 * 72

# Bottom-to-top composite order
LAYER_ORDER = [
    'hillshade',
    'contours',
    'waterways',
    'water_bodies',
    'roads',
    'railways',
    'places',
    'border',
]

_t_start = time.time()

def step(msg):
    elapsed = int(time.time() - _t_start)
    mm, ss = divmod(elapsed, 60)
    print(f"\n  ▸  [{mm:02d}:{ss:02d}] {msg}", flush=True)

def tick(msg):
    elapsed = int(time.time() - _t_start)
    mm, ss = divmod(elapsed, 60)
    print(f"     [{mm:02d}:{ss:02d}] {msg}", flush=True)

def _hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def main():
    parser = argparse.ArgumentParser(description='Composite layer PDFs into final map.')
    parser.add_argument('--preview', action='store_true',
                        help='Use SLICE_BOUNDS page size for preview output')
    parser.add_argument('--out', default=None,
                        help='Override output path (default: output/map.pdf)')
    args = parser.parse_args()

    out_path = args.out or OUT_PATH

    # Determine page dimensions from the layer PDFs (they all share the same size)
    sample_path = os.path.join(LAYERS_DIR, f'{LAYER_ORDER[0]}.pdf')
    if not os.path.exists(sample_path):
        print(f"\n  ERROR: {sample_path} not found.  Run 03_pdf_renderer.py first.")
        sys.exit(1)

    sample_doc  = fitz.open(sample_path)
    page_rect   = sample_doc[0].rect
    page_w      = page_rect.width
    page_h      = page_rect.height
    sample_doc.close()

    print(f"\n  PDF Combiner → {out_path}")
    print(f"  Page: {page_w/72:.2f} × {page_h/72:.2f} in  ({page_w:.0f} × {page_h:.0f} pt)")

    step("Compositing layers …")

    out_doc  = fitz.open()
    out_page = out_doc.new_page(width=page_w, height=page_h)

    # hillshade.pdf is rendered with an opaque paper background, so it serves
    # as the base layer. All other layers have transparent backgrounds and
    # composite correctly on top without PDF alpha-group issues.

    # Overlay each layer in z-order
    for name in LAYER_ORDER:
        layer_path = os.path.join(LAYERS_DIR, f'{name}.pdf')
        if not os.path.exists(layer_path):
            tick(f"WARNING: {name}.pdf not found — skipping")
            continue
        src = fitz.open(layer_path)
        out_page.show_pdf_page(out_page.rect, src, 0)
        src.close()
        tick(f"placed {name}.pdf")

    step("Saving …")
    out_doc.save(out_path, garbage=4, deflate=True)
    out_doc.close()

    size_mb = os.path.getsize(out_path) / 1e6
    total   = int(time.time() - _t_start)
    mm, ss  = divmod(total, 60)
    print(f"\n  ✓  {out_path}  ({size_mb:.1f} MB)")
    print(f"     {mm:02d}:{ss:02d} total\n")


if __name__ == '__main__':
    main()
