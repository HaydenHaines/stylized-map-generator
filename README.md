# Oklahoma Topo Map

High-resolution topographic map renderer for the Tulsa–Oklahoma City corridor, designed for a 9 × 8 ft vinyl wall print.

Pulls free public data — USGS 3DEP elevation + OpenStreetMap roads / rivers / rails / towns — and renders a clean, print-ready map. All style parameters (palette, line weights, fonts, bounds) live in `config.py`.

## Install

```bash
pip install -r requirements.txt
```

Tested against Python 3.11+ on macOS. No API keys required.

## Use

```bash
# 1. Download elevation + OSM data (~5–15 min, network-bound)
python 01_download_data.py

# 2. Render a preview PNG (fast; ~30 sec)
python 02_render_map.py
```

Output lands in `output/map_preview.png`. Iterate on `config.py` and re-run step 2 — no re-download needed unless you change `BOUNDS`.

When you're happy with the style, set `PREVIEW = False` in `config.py` to export the full print-resolution PDF + PNG.

## Customizing

Everything visual lives in `config.py`:

- `BOUNDS` — geographic extent (kept at 9:8 aspect to match the wall)
- `PALETTE` — colors for paper, contours, roads, rivers, labels, etc.
- `LW` — line weights (in matplotlib points; auto-scaled for print)
- `FONT` — label sizes per place tier
- `CONTOUR_INTERVAL_M`, `INDEX_EVERY` — topo line spacing
- `HS_ALPHA` — set > 0 to enable hillshade

`02_render_map.py` reads everything from `config.py`; you should rarely need to edit it.

## Smoke test

`python test_render.py` runs the pipeline against a synthetic DEM, useful for validating the install without a network round-trip.

## Data sources

- Elevation: [USGS 3DEP](https://www.usgs.gov/3d-elevation-program) via [py3dep](https://github.com/hyriver/py3dep)
- Vector layers: [OpenStreetMap](https://www.openstreetmap.org) via [osmnx](https://github.com/gboeing/osmnx)

OSM data © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).
