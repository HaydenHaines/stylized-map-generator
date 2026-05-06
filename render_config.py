"""
Render Config — dataclasses for the map rendering pipeline.
============================================================
RenderJob is the single source of truth for a render request.
It replaces the global config.py singletons so multiple jobs
can run independently (in subprocesses with different work dirs).

Usage by the pipeline scripts:
    from render_config import RenderJob, RenderPaths, load_job, DEFAULT_JOB

Usage by the API worker:
    job = RenderJob(bounds=BBox(...), palette_name='vintage', ...)
    save_job(job, work_dir / 'job.json')

Named palettes live in PALETTES.  To add a new one, just add an entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ─── Named colour palettes ────────────────────────────────────────────────────

# ─── Typography constants (style-preset level — not per-job for v1) ──────────

FONT_FAMILY: str = 'serif'
PREVIEW_WIDTH: float = 14.0   # inches — preview figure width (used to derive PRINT_SCALE)

FONT: dict = {
    'city':     {'size': 2.25,  'weight': 'bold',   'style': 'normal'},
    'town':     {'size': 1.75,  'weight': 'normal', 'style': 'normal'},
    'village':  {'size': 1.375, 'weight': 'normal', 'style': 'italic'},
    'hamlet':   {'size': 1.125, 'weight': 'normal', 'style': 'italic'},
    'contour':  {'size': 1.0,   'weight': 'normal', 'style': 'normal'},
    'title':    {'size': 7.0,   'weight': 'bold',   'style': 'normal'},
    'subtitle': {'size': 3.5,   'weight': 'normal', 'style': 'italic'},
}


# ─── Named colour palettes ────────────────────────────────────────────────────

PALETTES: dict[str, dict[str, str]] = {
    'vintage': {
        'paper':          '#F3ECDD',
        'contour':        '#B8AEA1',
        'index_contour':  '#B8AEA1',
        'hillshade_dark': '#93897D',
        'water_line':     '#8A9CAA',
        'water_fill':     '#B8C5CE',
        'highway':        '#8C7A67',
        'major_road':     '#8C7A67',
        'minor_road':     '#B19F8B',
        'railroad':       '#4E453C',
        'town_dot':       '#3F372F',
        'town_label':     '#3F372F',
        'label_halo':     '#F3ECDD',
        'grid':           '#E4DAC7',
        'border':         '#3F372F',
        'legend_bg':      '#E4DAC7',
        'accent':         '#B67B6B',
    },
    'monochrome': {
        'paper':          '#FFFFFF',
        'contour':        '#BBBBBB',
        'index_contour':  '#BBBBBB',
        'hillshade_dark': '#999999',
        'water_line':     '#888888',
        'water_fill':     '#CCCCCC',
        'highway':        '#555555',
        'major_road':     '#666666',
        'minor_road':     '#999999',
        'railroad':       '#333333',
        'town_dot':       '#111111',
        'town_label':     '#111111',
        'label_halo':     '#FFFFFF',
        'grid':           '#EEEEEE',
        'border':         '#111111',
        'legend_bg':      '#F0F0F0',
        'accent':         '#666666',
    },
    'navy': {
        'paper':          '#0A1628',
        'contour':        '#1E3A5F',
        'index_contour':  '#2E5F8A',
        'hillshade_dark': '#0D2040',
        'water_line':     '#4A90C4',
        'water_fill':     '#1A4A7A',
        'highway':        '#4A7AB5',
        'major_road':     '#3A6A9A',
        'minor_road':     '#2A4A6A',
        'railroad':       '#7AAAD0',
        'town_dot':       '#C8DDEF',
        'town_label':     '#C8DDEF',
        'label_halo':     '#0A1628',
        'grid':           '#12243F',
        'border':         '#C8DDEF',
        'legend_bg':      '#0D2040',
        'accent':         '#5BAED6',
    },
    'parchment': {
        'paper':          '#E8DEC0',
        'contour':        '#9C8A6E',
        'index_contour':  '#7A6A50',
        'hillshade_dark': '#8A7A60',
        'water_line':     '#6A8FAA',
        'water_fill':     '#9ABACC',
        'highway':        '#7A6040',
        'major_road':     '#8A7050',
        'minor_road':     '#AA9070',
        'railroad':       '#4A3A28',
        'town_dot':       '#2A1E10',
        'town_label':     '#2A1E10',
        'label_halo':     '#E8DEC0',
        'grid':           '#D8CEAC',
        'border':         '#2A1E10',
        'legend_bg':      '#D8CEAC',
        'accent':         '#A05A3A',
    },
}

# ─── Default layer ordering and line weights ──────────────────────────────────

DEFAULT_LAYER_NAMES = [
    'hillshade',
    'contours',
    'waterways',
    'water_bodies',
    'roads',
    'railways',
    'places',
    'border',
]

DEFAULT_LW_PRINT: dict[str, int] = {
    'contour':        1,
    'index_contour':  2,
    'river_major':    16,
    'river_minor':    4,
    'highway':        24,
    'major_road':     16,
    'minor_road':     6,
    'railroad':       16,
    'border':         96,
    'border_inner':   16,
}

# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class BBox:
    west:  float
    east:  float
    south: float
    north: float

    @property
    def lat_center(self) -> float:
        return (self.north + self.south) / 2

    def to_dict(self) -> dict[str, float]:
        return {'west': self.west, 'east': self.east,
                'south': self.south, 'north': self.north}

    def as_tuple(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) — osmnx / py3dep convention."""
        return (self.west, self.south, self.east, self.north)


@dataclass
class LayerSpec:
    name: str
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class TitleSpec:
    title:    str  = "UNTITLED MAP"
    subtitle: str  = ""
    show:     bool = True


@dataclass
class PreviewSpec:
    """If provided, a low-res PNG of the full bounds + a full-print-res PDF
    of slice_bounds will be produced alongside the full render."""
    slice_bounds: BBox | None = None   # None → use centre third of bounds


@dataclass
class RenderJob:
    # ── Identification ──────────────────────────────────────────
    job_id:     str

    # ── Geography ───────────────────────────────────────────────
    bounds:     BBox
    region_id:  str | None = None   # if set, use shared pre-cached data

    # ── Physical output ─────────────────────────────────────────
    width_in:   float = 9 + 7/12   # 115" default
    height_in:  float = 8 + 2/12   # 98" default
    print_dpi:  int   = 900

    # ── Style ───────────────────────────────────────────────────
    palette_name: str        = 'vintage'
    palette:      dict       = field(default_factory=dict)  # overrides palette_name

    # ── Layers ──────────────────────────────────────────────────
    layers: list[LayerSpec] = field(
        default_factory=lambda: [LayerSpec(name=n) for n in DEFAULT_LAYER_NAMES]
    )

    # ── Title block ─────────────────────────────────────────────
    title: TitleSpec | None = None

    # ── Preview ─────────────────────────────────────────────────
    preview: PreviewSpec | None = None

    # ── Processing knobs (usually left at defaults) ─────────────
    dem_resolution_m:       int   = 30
    contour_interval_m:     int   = 10
    index_every:            int   = 5
    contour_smooth:         float = 1.2
    contour_label_fmt:      str   = 'ft'
    hs_azimuth:             float = 320.0
    hs_altitude:            float = 40.0
    hs_vert_exag:           float = 6.0
    hs_alpha:               float = 0.35
    simplify_tolerance_deg: float = 5e-5
    water_body_min_area_ha: float = 0.5

    # ── Derived ─────────────────────────────────────────────────

    def resolved_palette(self) -> dict[str, str]:
        """Return the full palette, applying any per-key overrides."""
        base = PALETTES.get(self.palette_name, PALETTES['vintage']).copy()
        base.update(self.palette)
        return base

    def enabled_layers(self) -> list[str]:
        return [ls.name for ls in self.layers if ls.enabled]

    def layer_options(self, name: str) -> dict[str, Any]:
        for ls in self.layers:
            if ls.name == name:
                return ls.options
        return {}

    # ── Serialisation ───────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> RenderJob:
        d = json.loads(text)
        d['bounds'] = BBox(**d['bounds'])
        d['layers'] = [
            LayerSpec(**ls) for ls in d.get('layers', [])
        ]
        if d.get('title'):
            d['title'] = TitleSpec(**d['title'])
        if d.get('preview'):
            ps = d['preview']
            if ps.get('slice_bounds'):
                ps['slice_bounds'] = BBox(**ps['slice_bounds'])
            d['preview'] = PreviewSpec(**ps)
        return cls(**d)


# ─── Per-job paths ────────────────────────────────────────────────────────────

@dataclass
class RenderPaths:
    """All filesystem paths for one render job, rooted at work_dir."""
    work_dir: Path

    def __post_init__(self):
        self.work_dir = Path(self.work_dir)

    # raw data
    @property
    def data_dir(self)  -> Path: return self.work_dir / 'data'
    @property
    def dem_path(self)  -> Path: return self.data_dir / 'dem.tif'
    @property
    def osm_path(self)  -> Path: return self.data_dir / 'osm_data.gpkg'

    # preprocessed cache
    @property
    def cache_dir(self) -> Path: return self.work_dir / 'cache'

    # layer PDFs
    @property
    def layers_dir(self) -> Path: return self.work_dir / 'output' / 'layers'

    # final outputs
    @property
    def output_dir(self) -> Path: return self.work_dir / 'output'
    @property
    def preview_png(self)  -> Path: return self.output_dir / 'preview.png'
    @property
    def slice_pdf(self)    -> Path: return self.output_dir / 'slice.pdf'
    @property
    def full_pdf(self)     -> Path: return self.output_dir / 'map_full.pdf'

    def makedirs(self):
        for d in (self.data_dir, self.cache_dir, self.layers_dir):
            d.mkdir(parents=True, exist_ok=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def save_job(job: RenderJob, path: Path | str):
    Path(path).write_text(job.to_json())


def load_job(path: Path | str) -> RenderJob:
    return RenderJob.from_json(Path(path).read_text())


def job_from_config() -> RenderJob:
    """Build a RenderJob from the legacy config.py — used by CLI entry points."""
    import config as cfg
    import uuid

    bounds = BBox(
        west=cfg.BOUNDS['west'],
        east=cfg.BOUNDS['east'],
        south=cfg.BOUNDS['south'],
        north=cfg.BOUNDS['north'],
    )

    layers = []
    for name in DEFAULT_LAYER_NAMES:
        layers.append(LayerSpec(name=name, enabled=True))

    slice_b = None
    if cfg.SLICE_BOUNDS:
        slice_b = BBox(**cfg.SLICE_BOUNDS)

    title = TitleSpec(
        title=cfg.MAP_TITLE,
        subtitle=cfg.MAP_SUBTITLE,
        show=cfg.SHOW_TITLE,
    ) if cfg.SHOW_TITLE else None

    return RenderJob(
        job_id=str(uuid.uuid4()),
        bounds=bounds,
        region_id='local',
        width_in=cfg.WALL_WIDTH_FEET * 12,
        height_in=cfg.WALL_HEIGHT_FEET * 12,
        print_dpi=cfg.PRINT_DPI,
        palette_name='vintage',
        palette=cfg.PALETTE,
        layers=layers,
        title=title,
        preview=PreviewSpec(slice_bounds=slice_b) if slice_b else None,
        dem_resolution_m=cfg.DEM_RESOLUTION_M,
        contour_interval_m=cfg.CONTOUR_INTERVAL_M,
        index_every=cfg.INDEX_EVERY,
        contour_smooth=cfg.CONTOUR_SMOOTH,
        contour_label_fmt=cfg.CONTOUR_LABEL_FMT,
        hs_azimuth=cfg.HS_AZIMUTH,
        hs_altitude=cfg.HS_ALTITUDE,
        hs_vert_exag=cfg.HS_VERT_EXAG,
        hs_alpha=cfg.HS_ALPHA,
        simplify_tolerance_deg=cfg.SIMPLIFY_TOLERANCE_DEG,
        water_body_min_area_ha=cfg.WATER_BODY_MIN_AREA_HA,
    )
