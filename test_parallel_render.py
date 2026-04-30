"""
test_parallel_render.py — pytest tests for parallel layer rendering.

Tests cover:
  - composite_layer_pdfs: pikepdf overlay logic
  - _render_layer functions: per-layer render correctness
  - LAYER_ORDER invariants in render_full_parallel
"""

from __future__ import annotations
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pikepdf
import pytest

from config import BOUNDS
from render_full_parallel import composite_layer_pdfs, LAYER_ORDER
from _render_layer import render_border


# ─── helpers ─────────────────────────────────────────────────────────────────

def _tiny_pdf(path: str, color: str = '#FFFFFF', transparent: bool = False) -> str:
    """Write a 1×1 inch single-page PDF to *path*."""
    fig, ax = plt.subplots(figsize=(1, 1))
    ax.set_facecolor(color)
    ax.axis('off')
    save_kw: dict = dict(format='pdf', bbox_inches='tight',
                         facecolor=fig.get_facecolor())
    if transparent:
        save_kw['transparent'] = True
    fig.savefig(path, **save_kw)
    plt.close(fig)
    return path


# ─── composite_layer_pdfs ─────────────────────────────────────────────────────

def test_composite_produces_valid_pdf(tmp_path):
    """composite_layer_pdfs should write a readable single-page PDF."""
    base    = _tiny_pdf(str(tmp_path / 'base.pdf'),    color='#F3ECDD')
    overlay = _tiny_pdf(str(tmp_path / 'overlay.pdf'), transparent=True)
    out     = str(tmp_path / 'composite.pdf')

    composite_layer_pdfs([base, overlay], out)

    assert os.path.isfile(out), 'output PDF not created'
    assert os.path.getsize(out) > 0, 'output PDF is empty'
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


def test_composite_xobjects_count_matches_overlays(tmp_path):
    """Each overlay layer should produce exactly one Form XObject on the base page."""
    pdfs = [_tiny_pdf(str(tmp_path / f'l{i}.pdf'), transparent=(i > 0))
            for i in range(4)]
    out  = str(tmp_path / 'composite.pdf')

    composite_layer_pdfs(pdfs, out)

    with pikepdf.open(out) as pdf:
        page      = pdf.pages[0]
        resources = page.get('/Resources', pikepdf.Dictionary())
        xobjects  = resources.get('/XObject', pikepdf.Dictionary())
        # 4 PDFs → 3 overlay XObjects (base page carries no XObject for itself)
        assert len(xobjects) == len(pdfs) - 1


def test_composite_single_layer_is_valid(tmp_path):
    """A single-PDF 'composite' should still produce a valid PDF."""
    base = _tiny_pdf(str(tmp_path / 'base.pdf'), color='#AABBCC')
    out  = str(tmp_path / 'out.pdf')

    composite_layer_pdfs([base], out)

    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


def test_composite_content_stream_contains_do_operator(tmp_path):
    """Overlay PDFs must be invoked via a 'Do' operator in the content stream."""
    base    = _tiny_pdf(str(tmp_path / 'base.pdf'))
    overlay = _tiny_pdf(str(tmp_path / 'overlay.pdf'), transparent=True)
    out     = str(tmp_path / 'composite.pdf')

    composite_layer_pdfs([base, overlay], out)

    with pikepdf.open(out) as pdf:
        # read_bytes() decodes compressed streams; raw bytes may be deflate-compressed
        page    = pdf.pages[0]
        content = b''
        contents = page.get('/Contents')
        if contents is not None:
            if isinstance(contents, pikepdf.Array):
                for stream in contents:
                    content += stream.read_bytes()
            else:
                content += contents.read_bytes()
        assert b' Do' in content or b'\nDo' in content


# ─── LAYER_ORDER invariants ───────────────────────────────────────────────────

def test_layer_order_starts_with_background():
    """Background must be first so it serves as the opaque base page."""
    assert LAYER_ORDER[0] == 'background'


def test_layer_order_contains_expected_layers():
    """All expected map layers must be present in LAYER_ORDER."""
    expected = {
        'background', 'hillshade', 'contours', 'water_bodies',
        'waterways', 'roads', 'railways', 'labels', 'border',
    }
    assert expected.issubset(set(LAYER_ORDER))


def test_layer_order_no_duplicates():
    assert len(LAYER_ORDER) == len(set(LAYER_ORDER))


# ─── _render_layer functions ─────────────────────────────────────────────────

@pytest.fixture
def blank_axes():
    """A minimal Axes sized to the configured bounds."""
    import numpy as np
    from config import LAT_CENTER
    cos_lat = float(__import__('numpy').cos(__import__('numpy').radians(LAT_CENTER)))
    fig = plt.figure(figsize=(4, 4))
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(BOUNDS['west'],  BOUNDS['east'])
    ax.set_ylim(BOUNDS['south'], BOUNDS['north'])
    ax.set_aspect(1.0 / cos_lat)
    ax.axis('off')
    yield ax
    plt.close(fig)


def test_render_border_adds_patch(blank_axes):
    """render_border should add a Rectangle neatline to the axes."""
    before = len(blank_axes.patches)
    render_border(blank_axes)
    assert len(blank_axes.patches) > before


def test_render_border_patch_covers_bounds(blank_axes):
    """The border rectangle must span the full configured map bounds."""
    render_border(blank_axes)
    rect = blank_axes.patches[-1]
    x0, y0 = rect.get_xy()
    assert abs(x0 - BOUNDS['west'])  < 1e-9
    assert abs(y0 - BOUNDS['south']) < 1e-9
    assert abs(rect.get_width()  - (BOUNDS['east']  - BOUNDS['west']))  < 1e-9
    assert abs(rect.get_height() - (BOUNDS['north'] - BOUNDS['south'])) < 1e-9


@pytest.mark.skipif(not os.path.exists('data/osm_data.gpkg'),
                    reason='synthetic OSM data not generated; run test_render.py first')
def test_render_water_bodies_no_error(blank_axes):
    """render_water_bodies should complete silently when OSM data exists."""
    from _render_layer import render_water_bodies
    render_water_bodies(blank_axes)   # must not raise


@pytest.mark.skipif(not os.path.exists('data/osm_data.gpkg'),
                    reason='synthetic OSM data not generated; run test_render.py first')
def test_render_roads_no_error(blank_axes):
    """render_roads should complete silently when OSM data exists."""
    from _render_layer import render_roads
    render_roads(blank_axes)          # must not raise


@pytest.mark.skipif(not os.path.exists('data/osm_data.gpkg'),
                    reason='synthetic OSM data not generated; run test_render.py first')
def test_render_labels_no_error(blank_axes):
    """render_labels should complete silently when OSM data exists."""
    from _render_layer import render_labels
    render_labels(blank_axes)         # must not raise


@pytest.mark.skipif(not os.path.exists('data/dem.tif'),
                    reason='synthetic DEM not generated; run test_render.py first')
def test_render_contours_no_error(blank_axes):
    """render_contours should complete silently when DEM data exists."""
    from _render_layer import render_contours
    render_contours(blank_axes)       # must not raise
