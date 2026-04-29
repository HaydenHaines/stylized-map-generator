# Stylized Map Generator

Render a high-resolution topographic + transit map of any region as a print-ready vector PDF. Pulls free public data — USGS 3DEP elevation + OpenStreetMap roads / rivers / rails / towns — clips to a bounding box you choose, and styles it through a single config file.

Built for large-format wall prints (the included config is tuned for a 9 × 8 ft vinyl print of central Oklahoma), but works for any rectangular region: change the bounds, change the wall dimensions, re-run.

## Install

```bash
pip install -r requirements.txt
```

Tested against Python 3.11+ on macOS. No API keys required.

## Use

1. **Set your region** in `config.py`:

   ```python
   BOUNDS = {
       'west':  -98.45,    # decimal degrees, negative for Western Hemisphere
       'east':  -95.10,
       'south':  34.60,
       'north':  37.00,
   }

   WALL_WIDTH_FEET  = 9 + 8/12   # final printed dimensions (with bleed)
   WALL_HEIGHT_FEET = 8 + 6/12
   ```

   Pick `BOUNDS` so `Δlon × cos(center_lat) / Δlat` ≈ your wall aspect ratio. There's a comment in `config.py` showing the math.

2. **Download the data** (network-bound; ~5 min for a small region, ~40+ min for a 100+-mile bbox because the OpenStreetMap Overpass API splits large requests):

   ```bash
   python 01_download_data.py
   ```

   Saves to `data/dem.tif` and `data/osm_data.gpkg`.

3. **Render a slice preview** for fast iteration on style. Set `SLICE_BOUNDS` in `config.py` to a small sub-region (e.g. one county), then:

   ```bash
   python 02_render_map.py
   ```

   Output: `output/slice_preview.pdf` — vector PDF, **rendered at full print scale 1:1**. Open it, zoom in/out to evaluate hair-thin line widths and font sizing without paying the full-render cost.

4. **Render the final print PDF**: in `config.py` set `PREVIEW = False` and `SLICE_BOUNDS = None`, then re-run `02_render_map.py`. Output lands at `output/map_PRINT.pdf` at the full wall dimensions.

## Customizing

Everything visual lives in `config.py`:

- `BOUNDS` — geographic extent (decimal degrees)
- `WALL_WIDTH_FEET` / `WALL_HEIGHT_FEET` — final print dimensions
- `SLICE_BOUNDS` — sub-region rendered at print scale for fast iteration; set to `None` to render the full bounds
- `PALETTE` — colors for paper, contours, roads, rivers, labels, etc.
- `LW_PRINT` — line widths in **pixels at `PRINT_DPI`** (e.g. `4` = 4 px wide on a 900 DPI print). Easy to reason about without unit math.
- `FONT` — label sizes per place tier (city / town / village / hamlet)
- `CONTOUR_INTERVAL_M`, `INDEX_EVERY` — topo line spacing
- `HS_ALPHA` — set > 0 to enable hillshade
- `PRINT_DPI` — target DPI for the print (e.g. `900` for ultra-fine line work)

The render script reads everything from `config.py`; you should rarely need to edit it.

## Print prep

Output is **RGB vector PDF** by default.

**CMYK conversion** (required by most print shops):

1. Install Ghostscript: `sudo apt install ghostscript` / `brew install ghostscript`
2. Run the standalone converter:

```bash
python 03_to_cmyk.py --input output/map_PRINT.pdf --icc /path/to/profile.icc
```

Or set `CMYK_ICC_PROFILE = '/path/to/profile.icc'` in `config.py` — CMYK conversion then runs automatically at the end of every print render.

Ask your shop which ICC profile to target (common: U.S. Web Coated SWOP v2, GRACoL 2006, FOGRA39).

## Smoke test

`python test_render.py` runs the pipeline against a synthetic DEM, useful for validating the install without a network round-trip.

## Data sources

- Elevation: [USGS 3DEP](https://www.usgs.gov/3d-elevation-program) via [py3dep](https://github.com/hyriver/py3dep)
- Vector layers: [OpenStreetMap](https://www.openstreetmap.org) via [osmnx](https://github.com/gboeing/osmnx)

OSM data © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).
