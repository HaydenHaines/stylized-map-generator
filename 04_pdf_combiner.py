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
from pathlib import Path
import fitz   # PyMuPDF

from render_config import RenderJob, RenderPaths, job_from_config, DEFAULT_LAYER_NAMES

# Module-level state — set by _setup() before any render function runs.
_LAYERS_DIR: str = ''
_OUT_PATH:   str = ''
_LAYER_ORDER: list = []


def _setup(job: RenderJob, paths: RenderPaths):
    global _LAYERS_DIR, _OUT_PATH, _LAYER_ORDER
    paths.makedirs()
    _LAYERS_DIR  = str(paths.layers_dir)
    _OUT_PATH    = str(paths.full_pdf)
    _LAYER_ORDER = job.enabled_layers()

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


def run(job: RenderJob, paths: RenderPaths, out_path: str | None = None) -> str:
    """Composite layer PDFs into the final map PDF. Returns the output path."""
    _setup(job, paths)
    out = out_path or _OUT_PATH

    sample_path = os.path.join(_LAYERS_DIR, f'{_LAYER_ORDER[0]}.pdf')
    if not os.path.exists(sample_path):
        print(f"\n  ERROR: {sample_path} not found.  Run 03_pdf_renderer.py first.")
        sys.exit(1)

    sample_doc = fitz.open(sample_path)
    page_rect  = sample_doc[0].rect
    page_w     = page_rect.width
    page_h     = page_rect.height
    sample_doc.close()

    print(f"\n  PDF Combiner → {out}")
    print(f"  Page: {page_w/72:.2f} × {page_h/72:.2f} in  ({page_w:.0f} × {page_h:.0f} pt)")

    step("Compositing layers …")

    out_doc  = fitz.open()
    out_page = out_doc.new_page(width=page_w, height=page_h)

    for name in _LAYER_ORDER:
        layer_path = os.path.join(_LAYERS_DIR, f'{name}.pdf')
        if not os.path.exists(layer_path):
            tick(f"WARNING: {name}.pdf not found — skipping")
            continue
        src = fitz.open(layer_path)
        out_page.show_pdf_page(out_page.rect, src, 0)
        src.close()
        tick(f"placed {name}.pdf")

    step("Saving …")
    out_doc.save(out, garbage=4, deflate=True)
    out_doc.close()

    size_mb = os.path.getsize(out) / 1e6
    total   = int(time.time() - _t_start)
    mm, ss  = divmod(total, 60)
    print(f"\n  ✓  {out}  ({size_mb:.1f} MB)")
    print(f"     {mm:02d}:{ss:02d} total\n")
    return out


def main():
    parser = argparse.ArgumentParser(description='Composite layer PDFs into final map.')
    parser.add_argument('--out', default=None,
                        help='Override output path (default: output/map_full.pdf)')
    args = parser.parse_args()

    job   = job_from_config()
    paths = RenderPaths(Path('.'))
    run(job, paths, out_path=args.out)


if __name__ == '__main__':
    main()
