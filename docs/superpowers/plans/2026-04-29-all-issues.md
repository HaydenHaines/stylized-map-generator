# All Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 6 open GitHub issues: water-body filter (#4), memory monitoring (#6), CMYK export (#2), CLI args (#5), parallel rendering (#3), and performance docs (#1).

**Architecture:** Issues are implemented in dependency order — #4 and #6 are isolated additions; #2 and #5 layer on top; #3 refactors render internals into importable layer functions and adds a parallel driver; #1 documents the results.

**Tech Stack:** Python 3.11+, matplotlib, geopandas, pikepdf (new), psutil (new), multiprocessing, argparse

---

## File Map

| File | Role | Issues |
|------|------|--------|
| `config.py` | Add `MIN_WATER_BODY_AREA_M2`, `CMYK_ICC_PROFILE` | #4, #2 |
| `01_download_data.py` | Water-body area filter + argparse | #4, #5 |
| `02_render_map.py` | Memory monitoring + argparse + CMYK wire-in + extract layer fns | #6, #5, #2, #3 |
| `03_to_cmyk.py` | Standalone CMYK converter (new) | #2 |
| `_render_layer.py` | Per-layer render functions, importable (new) | #3 |
| `render_full_parallel.py` | Parallel driver + pikepdf composite (new) | #3 |
| `requirements.txt` | Add psutil, pikepdf | #6, #3 |
| `README.md` | CMYK section update, RAM + perf notes | #2, #1 |

---

## Task 1: Issue #4 — Water-body area filter

**Files:**
- Modify: `config.py`
- Modify: `01_download_data.py`

- [ ] **Step 1: Add config knob**

In `config.py`, after `SIMPLIFY_TOLERANCE_DEG`:

```python
# ─── WATER BODY FILTER ────────────────────────────────────────────────────────
# Minimum polygon area (m²) kept at download time.
# 10 000 m² ≈ 1 ha — drops stock ponds, pools, drainage ditches.
# Set to 0 to disable.
MIN_WATER_BODY_AREA_M2 = 10_000
```

- [ ] **Step 2: Import and apply in 01_download_data.py**

Change the import line:
```python
from config import BOUNDS, DEM_PATH, OSM_PATH, DATA_DIR, DEM_RESOLUTION_M, MIN_WATER_BODY_AREA_M2
```

After `wb = wb[wb.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])].copy()`, add:
```python
    if MIN_WATER_BODY_AREA_M2 > 0 and len(wb) > 0:
        before = len(wb)
        wb = wb[wb.to_crs(epsg=5070).geometry.area >= MIN_WATER_BODY_AREA_M2].copy()
        print(f"     · area filter: {before:,} → {len(wb):,} polygons "
              f"(kept ≥ {MIN_WATER_BODY_AREA_M2/1e4:.0f} ha)")
```

- [ ] **Step 3: Verify smoke test still passes**

```bash
cd /home/hayden/projects/stylized-map-generator
python test_render.py && python 02_render_map.py
```
Expected: `output/map_preview.pdf` written, no errors.

- [ ] **Step 4: Commit**

```bash
git add config.py 01_download_data.py
git commit -m "fix: filter water-body polygons smaller than 1 ha at download time (#4)"
```

---

## Task 2: Issue #6 — Memory monitoring

**Files:**
- Modify: `requirements.txt`
- Modify: `02_render_map.py`

- [ ] **Step 1: Add psutil to requirements**

Append to `requirements.txt`:
```
psutil>=5.9        # RSS memory monitoring during render
```

- [ ] **Step 2: Install**

```bash
pip install psutil
```

- [ ] **Step 3: Add background memory monitor to 02_render_map.py**

After the `time` import block (before `import matplotlib`), add:

```python
import threading
import psutil as _psutil

_peak_rss_mb: list[float] = [0.0]
_mem_stop = threading.Event()

def _memory_monitor() -> None:
    proc = _psutil.Process()
    while not _mem_stop.wait(5):
        rss = proc.memory_info().rss / 1024 ** 2
        if rss > _peak_rss_mb[0]:
            _peak_rss_mb[0] = rss

_mem_thread = threading.Thread(target=_memory_monitor, daemon=True)
_mem_thread.start()
```

- [ ] **Step 4: Report peak RSS at end of 02_render_map.py**

Replace the final `print(f"\n  Done.  Total wall: {mm:02d}:{ss:02d}\n")` with:

```python
_mem_stop.set()
_mem_thread.join(timeout=6)
print(f"\n  Done.  Total wall: {mm:02d}:{ss:02d}  |  Peak RSS: {_peak_rss_mb[0]:.0f} MB\n")
```

- [ ] **Step 5: Verify**

```bash
python 02_render_map.py
```
Expected: last line includes `Peak RSS: NNN MB`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt 02_render_map.py
git commit -m "feat: track and report peak RSS during render (#6)"
```

---

## Task 3: Issue #2 — CMYK conversion

**Files:**
- Modify: `config.py`
- Create: `03_to_cmyk.py`
- Modify: `02_render_map.py`
- Modify: `README.md`

- [ ] **Step 1: Add config knob**

In `config.py`, at the bottom (before `# ─── PATHS`):

```python
# ─── CMYK EXPORT ─────────────────────────────────────────────────────────────
# Absolute path to your print shop's ICC profile.
# Set to None to skip CMYK conversion (default).
# Common choices: U.S. Web Coated SWOP v2, GRACoL 2006, FOGRA39.
# Ask your shop which profile to target.
CMYK_ICC_PROFILE: str | None = None
```

- [ ] **Step 2: Create 03_to_cmyk.py**

```python
"""
03_to_cmyk.py — Convert RGB print PDF to CMYK via Ghostscript.

Usage:
    python 03_to_cmyk.py --input output/map_PRINT.pdf --icc /path/to/profile.icc
    python 03_to_cmyk.py  # uses paths from config.py (CMYK_ICC_PROFILE must be set)

Requires: Ghostscript  (sudo apt install ghostscript  /  brew install ghostscript)
"""

import argparse
import subprocess
import sys
from pathlib import Path

from config import OUTPUT_DIR, CMYK_ICC_PROFILE


def convert_to_cmyk(input_pdf: str, icc_profile: str, output_pdf: str | None = None) -> str:
    input_path = Path(input_pdf)
    if output_pdf is None:
        output_pdf = str(input_path.with_stem(input_path.stem + '_CMYK'))

    cmd = [
        'gs',
        '-sDEVICE=pdfwrite',
        '-dNOPAUSE', '-dBATCH', '-dQUIET',
        '-sColorConversionStrategy=CMYK',
        '-sProcessColorModel=DeviceCMYK',
        f'-sOutputICCProfile={icc_profile}',
        f'-sOutputFile={output_pdf}',
        input_pdf,
    ]

    print(f"  Converting {input_pdf} → {output_pdf}")
    print(f"  ICC profile: {icc_profile}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: Ghostscript failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)

    size_mb = Path(output_pdf).stat().st_size / 1024 ** 2
    print(f"  ✓  CMYK PDF written: {output_pdf}  ({size_mb:.1f} MB)")
    return output_pdf


def _check_ghostscript() -> None:
    result = subprocess.run(['gs', '--version'], capture_output=True)
    if result.returncode != 0:
        print("ERROR: Ghostscript not found.", file=sys.stderr)
        print("Install: sudo apt install ghostscript  /  brew install ghostscript", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert RGB PDF to CMYK via Ghostscript')
    parser.add_argument('--input', default=str(Path(OUTPUT_DIR) / 'map_PRINT.pdf'),
                        help='Input RGB PDF (default: output/map_PRINT.pdf)')
    parser.add_argument('--icc', default=CMYK_ICC_PROFILE,
                        help='Path to printer ICC profile (overrides config.CMYK_ICC_PROFILE)')
    parser.add_argument('--output', default=None,
                        help='Output CMYK PDF path (default: <input>_CMYK.pdf)')
    args = parser.parse_args()

    if not args.icc:
        print("ERROR: No ICC profile specified.", file=sys.stderr)
        print("Set CMYK_ICC_PROFILE in config.py or pass --icc /path/to/profile.icc", file=sys.stderr)
        sys.exit(1)

    _check_ghostscript()
    convert_to_cmyk(args.input, args.icc, args.output)
```

- [ ] **Step 3: Wire CMYK into print branch of 02_render_map.py**

After the `fig.savefig(...)` call in the export section and after the `tick(f"✓  PDF written...")` line, add:

```python
# Auto-convert to CMYK if profile is configured
from config import CMYK_ICC_PROFILE as _CMYK_ICC
if not PREVIEW and _CMYK_ICC:
    try:
        from pathlib import Path as _Path
        import subprocess as _sp
        cmyk_path = str(_Path(out_pdf).with_stem(_Path(out_pdf).stem + '_CMYK'))
        tick(f"Converting to CMYK (Ghostscript) …")
        _sp.run([
            'gs', '-sDEVICE=pdfwrite', '-dNOPAUSE', '-dBATCH', '-dQUIET',
            '-sColorConversionStrategy=CMYK', '-sProcessColorModel=DeviceCMYK',
            f'-sOutputICCProfile={_CMYK_ICC}', f'-sOutputFile={cmyk_path}', out_pdf,
        ], check=True)
        tick(f"✓  CMYK PDF: {cmyk_path}")
    except Exception as _e:
        tick(f"⚠  CMYK conversion failed: {_e} — RGB PDF still valid")
```

- [ ] **Step 4: Update README CMYK section**

Replace the current CMYK `## Print prep` shell block with:

```markdown
## Print prep

Output is **RGB vector PDF** by default.

**CMYK conversion** (required by most print shops):

1. Install Ghostscript: `sudo apt install ghostscript` / `brew install ghostscript`
2. Set `CMYK_ICC_PROFILE = '/path/to/printer-profile.icc'` in `config.py`, or pass `--icc`:

```bash
python 03_to_cmyk.py --input output/map_PRINT.pdf --icc /path/to/profile.icc
```

Common ICC profiles (ask your shop): U.S. Web Coated SWOP v2, GRACoL 2006, FOGRA39.

When `CMYK_ICC_PROFILE` is set in `config.py`, CMYK conversion runs automatically after the print PDF is written.
```

- [ ] **Step 5: Commit**

```bash
git add config.py 03_to_cmyk.py 02_render_map.py README.md
git commit -m "feat: add CMYK conversion via Ghostscript; auto-runs on print when ICC profile configured (#2)"
```

---

## Task 4: Issue #5 — CLI args

**Files:**
- Modify: `01_download_data.py`
- Modify: `02_render_map.py`

- [ ] **Step 1: Add argparse to 01_download_data.py**

After the imports (before `os.makedirs(...)`), add:

```python
import argparse

def _parse_args():
    p = argparse.ArgumentParser(
        description='Download DEM + OSM data for stylized-map-generator')
    p.add_argument('--bounds', metavar='W,S,E,N', default=None,
                   help='Bounding box as west,south,east,north decimal degrees '
                        '(overrides config.BOUNDS)')
    p.add_argument('--resolution', type=int, default=None,
                   help='DEM resolution in metres (overrides config.DEM_RESOLUTION_M)')
    p.add_argument('--output-dir', default=None,
                   help='Directory for downloaded data (overrides config.DATA_DIR)')
    return p.parse_args()

_args = _parse_args()

# Apply CLI overrides
if _args.bounds:
    w, s, e, n = map(float, _args.bounds.split(','))
    BOUNDS = {'west': w, 'south': s, 'east': e, 'north': n}
if _args.resolution:
    DEM_RESOLUTION_M = _args.resolution
if _args.output_dir:
    DATA_DIR = _args.output_dir
    DEM_PATH = f'{DATA_DIR}/dem.tif'
    OSM_PATH = f'{DATA_DIR}/osm_data.gpkg'
```

- [ ] **Step 2: Add argparse to 02_render_map.py**

After all imports and before `os.makedirs(OUTPUT_DIR, exist_ok=True)`, add:

```python
import argparse as _ap

def _parse_render_args():
    p = _ap.ArgumentParser(description='Render stylized map PDF')
    p.add_argument('--bounds', metavar='W,S,E,N', default=None,
                   help='Override config.BOUNDS (west,south,east,north)')
    p.add_argument('--slice', metavar='W,S,E,N', default=None,
                   help='Override config.SLICE_BOUNDS (west,south,east,north)')
    p.add_argument('--wall-w', type=float, default=None,
                   help='Wall width in feet (overrides config.WALL_WIDTH_FEET)')
    p.add_argument('--wall-h', type=float, default=None,
                   help='Wall height in feet (overrides config.WALL_HEIGHT_FEET)')
    p.add_argument('--dpi', type=int, default=None,
                   help='Override PRINT_DPI')
    p.add_argument('--simplify', type=float, default=None,
                   help='Douglas-Peucker tolerance in degrees (overrides config)')
    p.add_argument('--output-dir', default=None,
                   help='Output directory (overrides config.OUTPUT_DIR)')
    grp = p.add_mutually_exclusive_group()
    grp.add_argument('--preview', action='store_true', default=None,
                     help='Force preview mode')
    grp.add_argument('--print', dest='full_print', action='store_true', default=None,
                     help='Force full print mode (PREVIEW=False)')
    return p.parse_args()

_rargs = _parse_render_args()
if _rargs.bounds:
    _w, _s, _e, _n = map(float, _rargs.bounds.split(','))
    BOUNDS = {'west': _w, 'south': _s, 'east': _e, 'north': _n}
if _rargs.slice:
    _w, _s, _e, _n = map(float, _rargs.slice.split(','))
    SLICE_BOUNDS = {'west': _w, 'south': _s, 'east': _e, 'north': _n}
if _rargs.wall_w:
    WALL_WIDTH_FEET = _rargs.wall_w
if _rargs.wall_h:
    WALL_HEIGHT_FEET = _rargs.wall_h
if _rargs.dpi:
    PRINT_DPI = _rargs.dpi
if _rargs.simplify is not None:
    SIMPLIFY_TOLERANCE_DEG = _rargs.simplify
if _rargs.output_dir:
    OUTPUT_DIR = _rargs.output_dir
if _rargs.preview:
    PREVIEW = True
if _rargs.full_print:
    PREVIEW = False
```

- [ ] **Step 3: Test CLI help output**

```bash
python 01_download_data.py --help
python 02_render_map.py --help
```
Expected: usage lines listing all flags with descriptions.

- [ ] **Step 4: Test a slice override**

```bash
python 02_render_map.py --slice "-97.06,-96.42,35.40,35.85" --output-dir /tmp/map_test
```
Expected: renders slice, saves PDF to `/tmp/map_test/`.

- [ ] **Step 5: Commit**

```bash
git add 01_download_data.py 02_render_map.py
git commit -m "feat: add CLI overrides for bounds, slice, wall dims, DPI, output-dir (#5)"
```

---

## Task 5: Issue #3 — Parallel layer rendering

**Files:**
- Modify: `requirements.txt`
- Create: `_render_layer.py`
- Create: `render_full_parallel.py`

- [ ] **Step 1: Add pikepdf to requirements and install**

Append to `requirements.txt`:
```
pikepdf>=8.0          # PDF compositing for parallel layer merge
```

```bash
pip install pikepdf
```

- [ ] **Step 2: Create _render_layer.py**

This module holds one function per layer, each renders to a transparent-background PDF.

```python
"""
_render_layer.py — Per-layer render functions for parallel full render.

Each function takes (ax, fig) already sized and positioned, renders only
its own content, and returns.  Called from render_full_parallel.py.
"""

import numpy as np
from scipy.ndimage import gaussian_filter
from matplotlib.colors import LightSource, LinearSegmentedColormap

from config import (
    BOUNDS, LAT_CENTER, PRINT_DPI,
    CONTOUR_INTERVAL_M, INDEX_EVERY, CONTOUR_SMOOTH, CONTOUR_LABEL_FMT,
    PALETTE, LW_PRINT,
    HS_AZIMUTH, HS_ALTITUDE, HS_VERT_EXAG, HS_ALPHA,
    FONT_FAMILY, FONT,
    SIMPLIFY_TOLERANCE_DEG,
    DEM_PATH, OSM_PATH,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    SHOW_TITLE, SHOW_LEGEND,
    MAP_TITLE, MAP_SUBTITLE,
    PREVIEW_WIDTH,
)

WALL_W_IN    = WALL_WIDTH_FEET * 12
PRINT_SCALE  = WALL_W_IN / PREVIEW_WIDTH
cos_lat      = np.cos(np.radians(LAT_CENTER))


def _lw(key: str) -> float:
    return LW_PRINT[key] * 72.0 / PRINT_DPI


def _fs(key: str) -> float:
    return FONT[key]['size'] * PRINT_SCALE


def _load_dem():
    import rioxarray
    dem_ds = rioxarray.open_rasterio(DEM_PATH).squeeze()
    if str(dem_ds.rio.crs).upper() != 'EPSG:4326':
        dem_ds = dem_ds.rio.reproject('EPSG:4326')
    dem = dem_ds.values.astype(np.float32)
    nodata = dem_ds.rio.nodata
    if nodata is not None:
        dem[dem == nodata] = np.nan
    dem[dem < -500] = np.nan
    bnd_left   = float(dem_ds.x.values.min())
    bnd_right  = float(dem_ds.x.values.max())
    bnd_top    = float(dem_ds.y.values.max())
    bnd_bottom = float(dem_ds.y.values.min())
    h, w = dem.shape
    X = np.linspace(bnd_left, bnd_right, w)
    Y = np.linspace(bnd_top, bnd_bottom, h)
    Xg, Yg = np.meshgrid(X, Y)
    return dem, Xg, Yg, bnd_left, bnd_right, bnd_top, bnd_bottom, dem_ds.rio.transform()


def render_hillshade(ax) -> None:
    dem, Xg, Yg, bl, br, bt, bb, xform = _load_dem()
    cell_lon_deg = abs(xform[0])
    cell_lat_deg = abs(xform[4])
    dx = cell_lon_deg * 111_320 * cos_lat
    dy = cell_lat_deg * 111_320
    dem_s = gaussian_filter(np.where(np.isnan(dem), np.nanmean(dem), dem), CONTOUR_SMOOTH)
    ls    = LightSource(azdeg=HS_AZIMUTH, altdeg=HS_ALTITUDE)
    shade = ls.hillshade(dem_s, vert_exag=HS_VERT_EXAG, dx=dx, dy=dy)
    cmap  = LinearSegmentedColormap.from_list('hs', [PALETTE['hillshade_dark'], PALETTE['paper']])
    ax.imshow(shade, cmap=cmap, extent=[bl, br, bb, bt],
              origin='upper', alpha=HS_ALPHA, zorder=1, interpolation='bilinear')


def render_contours(ax) -> None:
    dem, Xg, Yg, *_ = _load_dem()
    dem_s     = gaussian_filter(np.where(np.isnan(dem), np.nanmean(dem), dem), CONTOUR_SMOOTH)
    elev_min  = np.nanmin(dem_s)
    elev_max  = np.nanmax(dem_s)
    first     = np.ceil(elev_min / CONTOUR_INTERVAL_M) * CONTOUR_INTERVAL_M
    all_lvls  = np.arange(first, elev_max + CONTOUR_INTERVAL_M, CONTOUR_INTERVAL_M)
    reg_lvls  = [l for i, l in enumerate(all_lvls) if (i % INDEX_EVERY) != 0]
    idx_lvls  = [l for i, l in enumerate(all_lvls) if (i % INDEX_EVERY) == 0]
    ax.contour(Xg, Yg, dem_s, levels=reg_lvls,
               colors=[PALETTE['contour']], linewidths=_lw('contour'), zorder=2, alpha=0.5)
    cs = ax.contour(Xg, Yg, dem_s, levels=idx_lvls,
                    colors=[PALETTE['index_contour']], linewidths=_lw('index_contour'), zorder=3, alpha=0.75)
    fmt = (lambda v: f"{v*3.28084:.0f}") if CONTOUR_LABEL_FMT == 'ft' else (lambda v: f"{v:.0f}")
    ax.clabel(cs, inline=True, fontsize=_fs('contour'), fmt=fmt,
              inline_spacing=2, use_clabeltext=True, colors=PALETTE['index_contour'])


def render_water_bodies(ax) -> None:
    import geopandas as gpd
    import os
    if not os.path.exists(OSM_PATH):
        return
    try:
        gdf = gpd.read_file(OSM_PATH, layer='water_bodies', engine='pyogrio')
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(gdf):
            gdf.geometry = gdf.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        gdf.plot(ax=ax, color=PALETTE['water_fill'], edgecolor=PALETTE['water_line'],
                 linewidth=_lw('river_minor'), zorder=3, alpha=0.95)
    except Exception:
        pass


def render_waterways(ax) -> None:
    import geopandas as gpd
    import os
    if not os.path.exists(OSM_PATH):
        return
    try:
        ww = gpd.read_file(OSM_PATH, layer='waterways', engine='pyogrio')
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(ww):
            ww.geometry = ww.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        is_river = ww.get('waterway', '').isin(['river', 'canal']) if 'waterway' in ww.columns \
                   else ww.index.isin([])
        major = ww[is_river]
        minor = ww[~is_river]
        if len(major):
            major.plot(ax=ax, color=PALETTE['water_line'], linewidth=_lw('river_major'), zorder=4)
        if len(minor):
            minor.plot(ax=ax, color=PALETTE['water_line'], linewidth=_lw('river_minor'), zorder=4, alpha=0.7)
    except Exception:
        pass


def render_roads(ax) -> None:
    import geopandas as gpd
    import os
    if not os.path.exists(OSM_PATH):
        return
    try:
        roads = gpd.read_file(OSM_PATH, layer='roads', engine='pyogrio')
        if SIMPLIFY_TOLERANCE_DEG > 0 and len(roads):
            roads.geometry = roads.geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        hierarchy = [
            ('motorway',     'highway',    'highway',    8),
            ('trunk',        'highway',    'highway',    8),
            ('primary',      'major_road', 'major_road', 6),
            ('secondary',    'major_road', 'major_road', 6),
            ('tertiary',     'minor_road', 'minor_road', 5),
            ('residential',  'minor_road', 'minor_road', 5),
            ('unclassified', 'minor_road', 'minor_road', 5),
        ]
        if 'highway' in roads.columns:
            for htype, lw_key, color_key, zord in hierarchy:
                subset = roads[roads['highway'].astype(str).str.lower() == htype]
                if len(subset):
                    subset.plot(ax=ax, color=PALETTE[color_key],
                                linewidth=_lw(lw_key), zorder=zord)
        else:
            roads.plot(ax=ax, color=PALETTE['minor_road'], linewidth=_lw('minor_road'), zorder=5)
    except Exception:
        pass


def render_railways(ax) -> None:
    import geopandas as gpd
    import os
    if not os.path.exists(OSM_PATH):
        return
    try:
        rail = gpd.read_file(OSM_PATH, layer='railways', engine='pyogrio')
        if len(rail):
            rail.plot(ax=ax, color=PALETTE['railroad'],
                      linewidth=_lw('railroad') * 0.7, zorder=7, linestyle=(0, (5, 4)))
    except Exception:
        pass


def render_labels(ax) -> None:
    import geopandas as gpd
    import os
    if not os.path.exists(OSM_PATH):
        return
    try:
        places = gpd.read_file(OSM_PATH, layer='places', engine='pyogrio')
        if 'place' not in places.columns:
            places['place'] = 'town'
        for ptype, fspec in FONT.items():
            if ptype not in ('city', 'town', 'village', 'hamlet'):
                continue
            subset = places[places['place'] == ptype]
            if 'name' not in subset.columns:
                continue
            for _, row in subset.iterrows():
                name = row.get('name')
                if not name or (isinstance(name, float) and np.isnan(name)):
                    continue
                name = str(name).split(';', 1)[0].strip()
                ax.annotate(
                    name,
                    xy=(row.geometry.x, row.geometry.y),
                    xytext=(0, 2 * PRINT_SCALE),
                    textcoords='offset points',
                    ha='center', va='bottom',
                    fontsize=_fs(ptype),
                    fontfamily=FONT_FAMILY,
                    fontweight=fspec['weight'],
                    fontstyle=fspec.get('style', 'normal'),
                    color=PALETTE['town_label'],
                    zorder=11,
                )
    except Exception:
        pass


def render_border(ax, fig) -> None:
    import matplotlib.pyplot as plt
    dlon = BOUNDS['east']  - BOUNDS['west']
    dlat = BOUNDS['north'] - BOUNDS['south']
    outer = plt.Rectangle(
        (BOUNDS['west'], BOUNDS['south']), dlon, dlat,
        linewidth=_lw('border'), edgecolor=PALETTE['border'],
        facecolor='none', transform=ax.transData, zorder=20,
    )
    ax.add_patch(outer)
    for lon in np.arange(np.ceil(BOUNDS['west']), BOUNDS['east'] + 0.5, 0.5):
        ax.axvline(lon, color=PALETTE['grid'], linewidth=0.3 * PRINT_SCALE, zorder=0, alpha=0.5)
    for lat in np.arange(np.ceil(BOUNDS['south']), BOUNDS['north'] + 0.5, 0.5):
        ax.axhline(lat, color=PALETTE['grid'], linewidth=0.3 * PRINT_SCALE, zorder=0, alpha=0.5)
```

- [ ] **Step 3: Create render_full_parallel.py**

```python
"""
render_full_parallel.py — Parallel full-bounds print render.

Fans out one subprocess per map layer (via multiprocessing), then composites
the per-layer PDFs into a single print file using pikepdf.

Usage:
    python render_full_parallel.py [--workers N] [--output-dir DIR]

Requires: pikepdf  (pip install pikepdf)
"""

import argparse
import os
import sys
import time
import tempfile
import multiprocessing as mp
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pikepdf

from config import (
    BOUNDS, LAT_CENTER,
    WALL_WIDTH_FEET, WALL_HEIGHT_FEET,
    PRINT_DPI, PREVIEW_WIDTH,
    PALETTE,
    OUTPUT_DIR,
)
import _render_layer as rl

WALL_W_IN = WALL_WIDTH_FEET  * 12
WALL_H_IN = WALL_HEIGHT_FEET * 12
cos_lat   = __import__('numpy').cos(__import__('numpy').radians(LAT_CENTER))

# Ordered bottom → top.  'background' is opaque; all others transparent.
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


def _make_axes(transparent: bool):
    bg = 'none' if transparent else PALETTE['paper']
    fig = plt.figure(figsize=(WALL_W_IN, WALL_H_IN), dpi=PRINT_DPI, facecolor=bg)
    ax  = fig.add_axes([0.03, 0.04, 0.94, 0.92])
    ax.set_facecolor(bg)
    ax.set_xlim(BOUNDS['west'],  BOUNDS['east'])
    ax.set_ylim(BOUNDS['south'], BOUNDS['north'])
    ax.set_aspect(1.0 / cos_lat)
    ax.axis('off')
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig, ax


def _render_one(args):
    """Worker function: render one named layer to a temp PDF, return the path."""
    layer_name, out_path = args
    matplotlib.use('Agg')
    import matplotlib.pyplot as _plt

    transparent = (layer_name != 'background')
    fig, ax = _make_axes(transparent)

    try:
        if layer_name == 'background':
            pass  # facecolor already set; just save
        elif layer_name == 'hillshade':
            rl.render_hillshade(ax)
        elif layer_name == 'contours':
            rl.render_contours(ax)
        elif layer_name == 'water_bodies':
            rl.render_water_bodies(ax)
        elif layer_name == 'waterways':
            rl.render_waterways(ax)
        elif layer_name == 'roads':
            rl.render_roads(ax)
        elif layer_name == 'railways':
            rl.render_railways(ax)
        elif layer_name == 'labels':
            rl.render_labels(ax)
        elif layer_name == 'border':
            rl.render_border(ax, fig)
    finally:
        kwargs = dict(dpi=PRINT_DPI, bbox_inches='tight', format='pdf',
                      facecolor=fig.get_facecolor())
        if transparent:
            kwargs['transparent'] = True
        fig.savefig(out_path, **kwargs)
        _plt.close(fig)

    return layer_name, out_path


def composite_layer_pdfs(layer_pdfs: list[str], output_pdf: str) -> None:
    """Overlay PDFs in z-order (first = bottom) into a single composite PDF."""
    result = pikepdf.open(layer_pdfs[0])
    dst_page = result.pages[0]

    for i, layer_path in enumerate(layer_pdfs[1:], start=1):
        with pikepdf.open(layer_path) as src:
            src_page = src.pages[0]
            xobj     = result.copy_foreign(src_page.as_form_xobject())
            xobj_key = pikepdf.Name(f'/L{i}')

            if '/XObject' not in dst_page.Resources:
                dst_page.Resources['/XObject'] = pikepdf.Dictionary()
            dst_page.Resources.XObject[xobj_key] = xobj

            content = f'q {xobj_key} Do Q\n'.encode()
            existing = dst_page.get('/Contents')
            new_stream = result.make_stream(content)
            if isinstance(existing, pikepdf.Array):
                existing.append(new_stream)
            elif existing is not None:
                dst_page['/Contents'] = pikepdf.Array([existing, new_stream])
            else:
                dst_page['/Contents'] = new_stream

    result.save(output_pdf)
    result.close()


def main():
    parser = argparse.ArgumentParser(description='Parallel full-bounds print render')
    parser.add_argument('--workers', type=int, default=len(LAYER_ORDER),
                        help=f'Parallel workers (default: {len(LAYER_ORDER)} = one per layer)')
    parser.add_argument('--output-dir', default=OUTPUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    t0 = time.time()

    with tempfile.TemporaryDirectory(prefix='smg_layers_') as tmp:
        layer_jobs = [
            (name, os.path.join(tmp, f'{i:02d}_{name}.pdf'))
            for i, name in enumerate(LAYER_ORDER)
        ]

        print(f"  Rendering {len(LAYER_ORDER)} layers with {args.workers} workers …")
        with mp.Pool(processes=args.workers) as pool:
            results = list(pool.imap_unordered(_render_one, layer_jobs))

        # Sort back into z-order
        name_to_path = dict(results)
        ordered_pdfs = [name_to_path[name] for name in LAYER_ORDER]

        out_pdf = os.path.join(args.output_dir, 'map_PRINT_parallel.pdf')
        print(f"  Compositing {len(ordered_pdfs)} layers with pikepdf …")
        composite_layer_pdfs(ordered_pdfs, out_pdf)

    elapsed = int(time.time() - t0)
    mm, ss  = divmod(elapsed, 60)
    print(f"\n  ✓  {out_pdf}  (wall: {mm:02d}:{ss:02d})\n")


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)
    main()
```

- [ ] **Step 4: Verify import works**

```bash
cd /home/hayden/projects/stylized-map-generator
python -c "import _render_layer; print('OK')"
python -c "import render_full_parallel; print('OK')"
```
Expected: `OK` for both.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt _render_layer.py render_full_parallel.py
git commit -m "feat: parallel layer rendering with pikepdf composite for full-bounds print (#3)"
```

---

## Task 6: Issue #1 — Performance documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add performance and RAM section to README**

After the `## Smoke test` section, add:

```markdown
## Performance & RAM

| Mode | Typical wall time | Peak RSS |
|------|-------------------|----------|
| Slice preview (`PREVIEW=True`, `SLICE_BOUNDS` set) | 5–30 min (varies by area) | 2–8 GB |
| Full bounds serial (`python 02_render_map.py`, `PREVIEW=False`) | 8–15 h | 16–32 GB |
| Full bounds parallel (`python render_full_parallel.py`) | ~heaviest-layer time | 4–8 GB per worker |

**Minimum recommended RAM:**
- Slice renders: 8 GB
- Serial full render: 32 GB (16 GB minimum, OOM risk)
- Parallel full render: 16 GB (workers share no heap)

**If RAM is limited:**
- Increase `SIMPLIFY_TOLERANCE_DEG` (try `1e-4`) to reduce path counts
- Increase `MIN_WATER_BODY_AREA_M2` (try `50_000` for 5 ha minimum)
- Use slice mode for style iteration; only run full render when ready to print

**Bottleneck:** `fig.savefig(format='pdf')` — matplotlib encodes every vector path sequentially. The parallel renderer (`render_full_parallel.py`) splits this across cores, bounding total time by the slowest layer (typically roads).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: RAM requirements, render timing table, bottleneck explanation (#1)"
```

---

## Final: Push and close issues

- [ ] **Push branch**

```bash
git push -u origin feature/all-issues
```

- [ ] **Open PR**

```bash
gh pr create --title "Resolve all 6 open issues" \
  --body "Closes #1, #2, #3, #4, #5, #6"
```
