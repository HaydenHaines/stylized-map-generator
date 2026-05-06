"""
Render Job — single entrypoint for running a full map render.
=============================================================
Chains all four pipeline steps for a given RenderJob.

Usage (programmatic):
    from render_job import run_render_job, RenderResult
    from render_config import RenderJob, BBox, LayerSpec, PreviewSpec

    job = RenderJob(
        job_id='my-job',
        bounds=BBox(west=-98.39, east=-94.92, south=34.55, north=36.95),
        palette_name='vintage',
    )
    result = run_render_job(job, work_dir=Path('/tmp/jobs/my-job'))
    print(result.full_pdf)     # Path to completed map PDF
    print(result.preview_png)  # Path to low-res preview (if preview was requested)

Usage (CLI):
    python render_job.py --job job.json [--work-dir /path/to/workdir] [--skip-download]
"""

from __future__ import annotations

import gc
import sys
import time
import json
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from render_config import RenderJob, RenderPaths, load_job, TitleSpec, PreviewSpec


# ─── Result ───────────────────────────────────────────────────────────────────

@dataclass
class RenderResult:
    job_id:      str
    work_dir:    Path
    full_pdf:    Optional[Path] = None
    preview_png: Optional[Path] = None
    slice_pdf:   Optional[Path] = None
    elapsed_s:   float = 0.0
    error:       Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.full_pdf is not None


# ─── Shared cache for curated regions ─────────────────────────────────────────
# Curated regions have pre-downloaded data/ + preprocessed cache/ stored here.
# When region_id is set, we symlink (or copy-on-first-use) from this directory
# instead of re-downloading or re-preprocessing.
REGIONS_DIR = Path(__file__).parent / 'regions'


def _link_shared_cache(job: RenderJob, paths: RenderPaths):
    """If job.region_id is set and a shared cache exists, symlink data/ + cache/
    from REGIONS_DIR/<region_id>/ into paths.work_dir so we skip download + preprocess."""
    if not job.region_id:
        return False

    region_dir = REGIONS_DIR / job.region_id
    if not region_dir.exists():
        return False

    shared_data  = region_dir / 'data'
    shared_cache = region_dir / 'cache'

    linked = False
    for src, dst in [(shared_data, paths.data_dir), (shared_cache, paths.cache_dir)]:
        if src.exists() and not dst.exists():
            dst.symlink_to(src.resolve())
            linked = True

    return linked


# ─── Main orchestrator ────────────────────────────────────────────────────────

def run_render_job(
    job: RenderJob,
    work_dir: Path,
    skip_download:   bool = False,
    skip_preprocess: bool = False,
    force_render:    bool = False,
) -> RenderResult:
    """
    Run a full map render for the given job.

    Steps:
        1. Ensure data (download or symlink from shared region cache)
        2. Preprocess (vector renderer — DEM smooth, hillshade, OSM parquets)
        3. Render per-layer PDFs
        4. Composite final PDF
        5. (Optional) render low-res preview PNG + slice PDF

    Returns a RenderResult with paths to all outputs.
    """
    t0    = time.time()
    paths = RenderPaths(work_dir)
    paths.makedirs()

    result = RenderResult(job_id=job.job_id, work_dir=work_dir)

    try:
        # ── Step 1: Data ──────────────────────────────────────────────────────
        if not skip_download:
            cached = _link_shared_cache(job, paths)
            if cached:
                print(f"  [render_job] Using shared cache for region '{job.region_id}'")
            elif not (paths.dem_path.exists() and paths.osm_path.exists()):
                print(f"  [render_job] Downloading data for job {job.job_id} …")
                import importlib
                dl = importlib.import_module('01_download_data')
                dl.run(job, paths)
            else:
                print(f"  [render_job] Data already present — skipping download")

        # ── Step 2: Preprocess ────────────────────────────────────────────────
        if not skip_preprocess:
            import importlib
            vr = importlib.import_module('02_vector_renderer')
            vr.run(job, paths)
        gc.collect()

        # ── Step 3: Render layers ─────────────────────────────────────────────
        import importlib
        pr = importlib.import_module('03_pdf_renderer')
        pr.run(job, paths, force=force_render)
        gc.collect()

        # ── Step 4: Composite ─────────────────────────────────────────────────
        cb = importlib.import_module('04_pdf_combiner')
        cb.run(job, paths)
        gc.collect()

        result.full_pdf = paths.full_pdf

        # ── Step 5: Preview ───────────────────────────────────────────────────
        if job.preview:
            _render_preview(job, paths, result)
            gc.collect()

    except Exception as exc:
        result.error = str(exc)
        import traceback
        traceback.print_exc()

    result.elapsed_s = time.time() - t0
    elapsed = int(result.elapsed_s)
    mm, ss = divmod(elapsed, 60)
    status = '✓' if result.success else '✗'
    print(f"\n  {status}  render_job {job.job_id}  ({mm:02d}:{ss:02d} total)\n")
    return result


def _render_preview(job: RenderJob, paths: RenderPaths, result: RenderResult):
    """Render a low-res preview PNG of the full bounds + a slice PDF."""
    import importlib
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    pr = importlib.import_module('03_pdf_renderer')

    # ── Low-res PNG of full map ───────────────────────────────────────────────
    # Reuse the existing layer PDFs — convert hillshade + one-pass rasterise.
    # Simpler: render a special low-res matplotlib figure directly from cache.
    _render_preview_png(job, paths, result)

    # ── Slice PDF ─────────────────────────────────────────────────────────────
    if job.preview.slice_bounds:
        # Derive a slice job with full print DPI but restricted bounds
        slice_job = RenderJob(
            job_id=job.job_id + '_slice',
            bounds=job.preview.slice_bounds,
            region_id=job.region_id,
            width_in=job.width_in,
            height_in=job.height_in,
            print_dpi=job.print_dpi,
            palette_name=job.palette_name,
            palette=job.palette,
            layers=job.layers,
            title=job.title,
            dem_resolution_m=job.dem_resolution_m,
            contour_interval_m=job.contour_interval_m,
            index_every=job.index_every,
            hs_alpha=job.hs_alpha,
            water_body_min_area_ha=job.water_body_min_area_ha,
        )
        slice_layers_dir = paths.output_dir / 'layers_slice'
        slice_layers_dir.mkdir(exist_ok=True)

        slice_paths = RenderPaths(paths.work_dir)
        # Override layers dir by monkey-patching after setup — use a temp subdir
        pr.run(slice_job, slice_paths, force=True, use_slice=True)

        cb = importlib.import_module('04_pdf_combiner')
        slice_out = str(paths.slice_pdf)
        cb.run(slice_job, slice_paths, out_path=slice_out)
        result.slice_pdf = paths.slice_pdf


def _render_preview_png(job: RenderJob, paths: RenderPaths, result: RenderResult):
    """Rasterise the composited map PDF to a low-res PNG for email/web preview."""
    try:
        import fitz
        pdf_path = paths.full_pdf
        if not pdf_path.exists():
            return
        doc  = fitz.open(str(pdf_path))
        page = doc[0]
        # Target ~1200px wide for preview
        scale = 1200 / page.rect.width
        mat   = fitz.Matrix(scale, scale)
        pix   = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(paths.preview_png))
        doc.close()
        result.preview_png = paths.preview_png
        size_kb = paths.preview_png.stat().st_size // 1024
        print(f"  [render_job] preview.png saved  ({size_kb} KB, {pix.width}×{pix.height})")
    except Exception as e:
        print(f"  [render_job] WARNING: preview PNG failed: {e}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Run a full map render from a job JSON file.')
    parser.add_argument('--job',  required=True, help='Path to job.json')
    parser.add_argument('--work-dir', default=None,
                        help='Working directory (default: same dir as job.json)')
    parser.add_argument('--skip-download',   action='store_true')
    parser.add_argument('--skip-preprocess', action='store_true')
    parser.add_argument('--force-render',    action='store_true')
    args = parser.parse_args()

    job_path = Path(args.job)
    work_dir = Path(args.work_dir) if args.work_dir else job_path.parent

    job = load_job(job_path)
    result = run_render_job(
        job, work_dir,
        skip_download=args.skip_download,
        skip_preprocess=args.skip_preprocess,
        force_render=args.force_render,
    )

    if not result.success:
        print(f"ERROR: {result.error}", file=sys.stderr)
        sys.exit(1)

    print(f"Full PDF : {result.full_pdf}")
    if result.preview_png:
        print(f"Preview  : {result.preview_png}")
    if result.slice_pdf:
        print(f"Slice    : {result.slice_pdf}")


if __name__ == '__main__':
    main()
