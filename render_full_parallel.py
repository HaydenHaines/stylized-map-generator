"""
render_full_parallel.py — Parallel full-bounds print render.

Fans out one worker process per map layer (via multiprocessing.Pool), then
composites the per-layer PDFs into a single print file using pikepdf.

Each worker renders only its assigned layer to a transparent-background PDF
(the 'background' layer uses an opaque paper-colour fill).  pikepdf overlays
them in z-order by converting each page to a Form XObject and appending a
'Do' operator to the base page's content stream.

Usage:
    python render_full_parallel.py [--workers N] [--output-dir DIR]

Workers default to one per layer (9 total) — adjust down on RAM-limited machines.

Requires: pikepdf  (pip install pikepdf)
"""

from __future__ import annotations
import argparse
import os
import sys
import time
import tempfile
import multiprocessing as mp
from pathlib import Path

# matplotlib must be initialised *inside* worker processes so each one gets
# a clean non-interactive backend.  Do NOT import it at module level.

import pikepdf

from config import (
    BOUNDS, LAT_CENTER,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    PRINT_DPI, PREVIEW_WIDTH,
    PALETTE,
    OUTPUT_DIR,
)

WALL_W_IN = WALL_WIDTH_FEET  * 12
WALL_H_IN = WALL_HEIGHT_FEET * 12

# Layers rendered bottom → top.  'background' is opaque; all others transparent.
LAYER_ORDER = [
    'background',
    'hillshade',
    'contours',
    'water_bodies',
    'waterways',
    'roads',
    'railways',
    'labels',
    'border',
]


# ─── Worker ──────────────────────────────────────────────────────────────────

def _render_one(args: tuple[str, str]) -> tuple[str, str, dict]:
    """Render a single named layer to *out_path* as a PDF.  Returns (name, path, timings)."""
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    layer_name, out_path = args
    transparent = (layer_name != 'background')
    bg = 'none' if transparent else PALETTE['paper']

    import _render_layer as rl
    cos_lat = np.cos(np.radians(LAT_CENTER))

    fig = plt.figure(figsize=(WALL_W_IN, WALL_H_IN), dpi=PRINT_DPI, facecolor=bg)
    ax  = fig.add_axes([0.03, 0.04, 0.94, 0.92])
    ax.set_facecolor(bg)
    ax.set_xlim(BOUNDS['west'],  BOUNDS['east'])
    ax.set_ylim(BOUNDS['south'], BOUNDS['north'])
    ax.set_aspect(1.0 / cos_lat)
    ax.axis('off')
    for spine in ax.spines.values():
        spine.set_visible(False)

    dispatch = {
        'background':   lambda: None,
        'hillshade':    lambda: rl.render_hillshade(ax),
        'contours':     lambda: rl.render_contours(ax),
        'water_bodies': lambda: rl.render_water_bodies(ax),
        'waterways':    lambda: rl.render_waterways(ax),
        'roads':        lambda: rl.render_roads(ax),
        'railways':     lambda: rl.render_railways(ax),
        'labels':       lambda: rl.render_labels(ax),
        'border':       lambda: rl.render_border(ax),
    }
    save_kwargs: dict = dict(
        dpi=PRINT_DPI,
        bbox_inches='tight',
        format='pdf',
        facecolor=fig.get_facecolor(),
        metadata={'Creator': f'SMG layer:{layer_name}'},
    )
    if transparent:
        save_kwargs['transparent'] = True

    # Time render (data load + plot) and savefig separately to pinpoint bottleneck.
    t_start = time.time()
    try:
        dispatch[layer_name]()
        t_render = time.time()
        fig.savefig(out_path, **save_kwargs)
        t_save = time.time()
    finally:
        plt.close(fig)

    timings = {
        'render_s':  t_render - t_start,
        'savefig_s': t_save   - t_render,
        'total_s':   t_save   - t_start,
    }
    return layer_name, out_path, timings


# ─── pikepdf compositing ─────────────────────────────────────────────────────

def composite_layer_pdfs(layer_pdfs: list[str], output_pdf: str) -> None:
    """Overlay PDFs in z-order (first = bottom) into a single composite PDF."""
    result = pikepdf.open(layer_pdfs[0])
    dst_page = result.pages[0]

    # Ensure the base page has a Resources/XObject dict ready for overlays
    if '/Resources' not in dst_page:
        dst_page['/Resources'] = pikepdf.Dictionary()
    if '/XObject' not in dst_page.Resources:
        dst_page.Resources['/XObject'] = pikepdf.Dictionary()

    for i, layer_path in enumerate(layer_pdfs[1:], start=1):
        with pikepdf.open(layer_path) as src:
            src_page = src.pages[0]
            # Copy the source page as a Form XObject into the result PDF
            xobj     = result.copy_foreign(src_page.as_form_xobject())
            xobj_key = pikepdf.Name(f'/L{i}')
            dst_page.Resources.XObject[xobj_key] = xobj
            # Append draw command: save gs, invoke XObject, restore gs
            content = f'q {xobj_key} Do Q\n'.encode()
            dst_page.contents_add(content)

    result.save(output_pdf)
    result.close()


# ─── Driver ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Parallel full-bounds print render',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--workers', type=int, default=len(LAYER_ORDER),
                        help='Parallel workers (one per layer by default)')
    parser.add_argument('--output-dir', default=OUTPUT_DIR,
                        help='Directory for output PDF')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    t0 = time.time()

    with tempfile.TemporaryDirectory(prefix='smg_layers_') as tmp:
        layer_jobs = [
            (name, os.path.join(tmp, f'{i:02d}_{name}.pdf'))
            for i, name in enumerate(LAYER_ORDER)
        ]

        print(f"\n  ▸  Rendering {len(LAYER_ORDER)} layers with {args.workers} workers …\n")
        print(f"     {'layer':<14} {'render':>8}  {'savefig':>8}  {'total':>7}  {'size':>6}")
        print(f"     {'-'*14} {'-'*8}  {'-'*8}  {'-'*7}  {'-'*6}")
        with mp.Pool(processes=args.workers) as pool:
            completed: list[tuple[str, str]] = []
            for name, path, timings in pool.imap_unordered(_render_one, layer_jobs):
                elapsed = int(time.time() - t0)
                mm, ss  = divmod(elapsed, 60)
                size_mb = Path(path).stat().st_size / 1024 ** 2
                print(
                    f"     [{mm:02d}:{ss:02d}] ✓  {name:<12}"
                    f"  {timings['render_s']:>6.0f}s"
                    f"  {timings['savefig_s']:>6.0f}s"
                    f"  {timings['total_s']:>5.0f}s"
                    f"  {size_mb:>4.0f} MB"
                )
                completed.append((name, path))

        # Sort back into bottom→top z-order
        name_to_path = dict(completed)
        ordered_pdfs = [name_to_path[name] for name in LAYER_ORDER]

        out_pdf = os.path.join(args.output_dir, 'map_PRINT_parallel.pdf')
        print(f"\n  ▸  Compositing {len(ordered_pdfs)} layers with pikepdf …")
        composite_layer_pdfs(ordered_pdfs, out_pdf)

    elapsed = int(time.time() - t0)
    mm, ss  = divmod(elapsed, 60)
    size_mb = Path(out_pdf).stat().st_size / 1024 ** 2
    print(f"\n  ✓  {out_pdf}  ({size_mb:.0f} MB,  wall: {mm:02d}:{ss:02d})\n")


if __name__ == '__main__':
    # 'spawn' required on Linux so each worker gets a clean matplotlib state
    mp.set_start_method('spawn', force=True)
    main()
