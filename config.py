"""
Stylized Map Generator — Configuration
=======================================
All tuneable parameters live here.
Tweak and re-run 02_render_map.py to see changes.
No need to touch the render script itself for style changes.

To map a different region: change BOUNDS, WALL_WIDTH_FEET / WALL_HEIGHT_FEET,
and (optionally) SLICE_BOUNDS, then run 01_download_data.py followed by
02_render_map.py.  Everything else is style and scales automatically.
"""

import numpy as np

# ─── GEOGRAPHIC BOUNDS ─────────────────────────────────────────────────────
# Decimal degrees; west/east are negative in the Western Hemisphere.
# Pick a Δlon × cos(LAT_CENTER) / Δlat that matches your wall aspect ratio.
# Example below: Tulsa-OKC corridor with +30 mi bleed on each side, sized to
# match ~9:8 aspect on the print.

BOUNDS = {
    'west':  -97.90,   # ~25 mi west of OKC
    'east':  -95.55,   # ~25 mi east of Tulsa
    'south':  35.10,
    'north':  36.55,
}

# Latitude used for aspect-ratio + hillshade cell-size corrections
LAT_CENTER = (BOUNDS['north'] + BOUNDS['south']) / 2   # ≈ 35.8 °N

# ─── WALL / OUTPUT DIMENSIONS ───────────────────────────────────────────────
WALL_WIDTH_FEET  = 10 + 10/12     # 10' 10"  proportional to geographic extent at this height
WALL_HEIGHT_FEET =  8 +  3/12     #  8'  3"  final print height

# ── PREVIEW vs. PRINT ──────────────────────────────────────────────────────
# PREVIEW = True  → fast, screen-resolution render (good for style iteration)
# PREVIEW = False → full print-resolution export (slow, large file)
PREVIEW       = False

PREVIEW_DPI   = 300        # DPI for preview PNG  (was 120 — 300 lets thin lines/contours resolve)
PREVIEW_WIDTH = 14.0       # figure width in inches for preview (height auto-calculated)

PRINT_DPI     = 900        # DPI for final print export
#   At 900 DPI:  9 ft × 900 = 97 200 px wide,  8 ft × 900 = 86 400 px tall (~8.4 GP)
#   PDF (vector) preferred at this scale; PNG would be ~25 GB uncompressed.

# ─── DEM / ELEVATION ────────────────────────────────────────────────────────
# Resolution in metres.  30 = SRTM-class (fine for a wall map).
# Use 10 for maximum sharpness (5× larger download + longer processing).
DEM_RESOLUTION_M = 30

# ─── CONTOUR SETTINGS ───────────────────────────────────────────────────────
CONTOUR_INTERVAL_M = 10      # metres between contour lines
INDEX_EVERY        = 5       # every Nth contour is an "index" contour (thicker + labelled)
CONTOUR_SMOOTH     = 1.2     # gaussian σ applied to DEM before contouring (smooths jaggies)
CONTOUR_LABEL_FMT  = 'ft'    # 'ft' shows elevation in feet; 'm' shows metres

# ─── COLOR PALETTE ──────────────────────────────────────────────────────────
# Black / grey on white — clean base for Photoshop color grading.
# Swap these to the warm vintage palette once you've approved the structure.
PALETTE = {
    'paper':           '#F3ECDD',   # warm aged-paper background
    'contour':         '#B8AEA1',   # regular contours
    'index_contour':   '#B8AEA1',   # index contours — same color, differentiated by alpha + LW
    'hillshade_dark':  '#93897D',   # warm shadow tint (used only if HS_ALPHA > 0)
    'water_line':      '#8A9CAA',   # rivers
    'water_fill':      '#B8C5CE',   # softer river fill for lakes/reservoirs
    'highway':         '#8C7A67',   # major roads
    'major_road':      '#8C7A67',   # major roads
    'minor_road':      '#B19F8B',   # minor roads
    'railroad':        '#4E453C',
    'town_dot':        '#3F372F',   # major label
    'town_label':      '#3F372F',
    'label_halo':      '#F3ECDD',   # paper-color knockout behind labels
    'grid':            '#E4DAC7',   # secondary paper shadow — subtle grid
    'border':          '#3F372F',   # dark neatline
    'legend_bg':       '#E4DAC7',
    'accent':          '#B67B6B',   # optional trade-corridor accent
}

# ─── LINE WEIGHTS ───────────────────────────────────────────────────────────
# Values are in matplotlib "points" (1 pt = 1/72 inch) and are tuned for the
# PREVIEW figure (14 in wide).  The render script automatically scales them up
# for the full-size PRINT figure (108 in wide) by multiplying by
# WALL_W_IN / PREVIEW_WIDTH ≈ 7.7.
#
# To tweak aesthetics, adjust the numbers below and re-run 02_render_map.py.
LW = {
    # Preview line weights (pt) — tuned so lines are visible at 14" × 300 DPI.
    # These do NOT control print thickness; see LW_PRINT below.
    'contour':        0.40,   # regular topo contour
    'index_contour':  0.95,   # thicker index (every 5th) contour
    'river_major':    1.00,   # rivers / canals
    'river_minor':    0.28,   # streams / creeks (thinned for 300 DPI preview)
    'highway':        0.70,   # interstate & US highways
    'major_road':     0.40,   # state highways / primary roads
    'minor_road':     0.15,   # county / residential roads — tuned for 300 DPI
    'railroad':       0.85,   # rail lines
    'border':         2.80,   # map neatline
    'border_inner':   0.70,
}

# Final-print line widths in PIXELS at PRINT_DPI on the 9 × 8 ft figure.
# Render script converts to absolute points: pt = px × 72 / PRINT_DPI.
# At 900 DPI: 1 px ≈ 0.08 pt ≈ 0.028 mm.
LW_PRINT = {
    'contour':        1,    # regular topo contour — hair-thin secondary detail
    'index_contour':  2,    # index (every 5th)   — hair-thin secondary detail
    'river_major':    16,   # rivers / canals
    'river_minor':    4,    # streams / creeks
    'highway':        24,   # interstate & US highways
    'major_road':     16,   # state highways / primary roads
    'minor_road':     6,    # county / residential roads
    'railroad':       16,   # rail lines
    'border':         96,   # map neatline
    'border_inner':   16,
}

# ─── GEOMETRY SIMPLIFICATION ───────────────────────────────────────────────────
# Apply Douglas-Peucker simplification to OSM line/polygon geometries before
# plotting.  Tolerance in decimal degrees; sub-pixel values produce no visible
# change at print scale but cut path counts substantially.
#   At 900 DPI on this map: 1° lon ≈ 28 000 px → tolerance 5e-5° ≈ 1.4 px.
# Set to 0 to disable.
SIMPLIFY_TOLERANCE_DEG = 5e-5

# ─── WATER BODY FILTER ────────────────────────────────────────────────────────
# Minimum polygon area (m²) kept at download time.
# 10 000 m² ≈ 1 ha — drops stock ponds, pools, drainage ditches.
# Set to 0 to disable.
MIN_WATER_BODY_AREA_M2 = 10_000

# ─── CMYK EXPORT ─────────────────────────────────────────────────────────────
# Absolute path to your print shop's ICC profile.
# Set to None to skip CMYK conversion (default).
# Common choices: U.S. Web Coated SWOP v2, GRACoL 2006, FOGRA39.
CMYK_ICC_PROFILE: 'str | None' = None

# ─── HILLSHADE ───────────────────────────────────────────────────────────────
HS_AZIMUTH   = 320    # degrees — NW light source (classic cartographic convention)
HS_ALTITUDE  = 40     # degrees above horizon
HS_VERT_EXAG = 6.0    # vertical exaggeration (push higher for subtle topography)
HS_ALPHA     = 0.0    # 0 = off (clean white base for Photoshop).  Set to 0.3–0.4 to re-enable.

# ─── TYPOGRAPHY ──────────────────────────────────────────────────────────────
# Sizes are in points and designed for the PREVIEW figure.
# The render script scales them up for the print figure automatically.
FONT_FAMILY = 'serif'    # built-in matplotlib serif; swap for 'IM Fell English'
               #   or 'Libre Baskerville' if you install them via matplotlib font cache

# Font sizes are in points and tuned for the PREVIEW figure (14 in wide).
# They scale up automatically for the print figure.
FONT = {
    # Sizes reduced 4× from previous (× 0.25) to relieve label overlap
    'city':      {'size': 2.25,  'weight': 'bold',   'style': 'normal'},
    'town':      {'size': 1.75,  'weight': 'normal',  'style': 'normal'},
    'village':   {'size': 1.375, 'weight': 'normal',  'style': 'italic'},
    'hamlet':    {'size': 1.125, 'weight': 'normal',  'style': 'italic'},
    'contour':   {'size': 1.0,   'weight': 'normal',  'style': 'normal'},
    'title':     {'size': 7.0,   'weight': 'bold',   'style': 'normal'},
    'subtitle':  {'size': 3.5,   'weight': 'normal',  'style': 'italic'},
}

# ─── LEGEND / TITLE ──────────────────────────────────────────────────────────
MAP_TITLE    = "COMMERCIAL ROUTES OF OKLAHOMA"
MAP_SUBTITLE = "Showing Principal Roads, Rails, Rivers, and Trade Corridors"
SHOW_TITLE   = False    # set False to suppress the title block
SHOW_LEGEND  = True     # set False to suppress the legend
SHOW_GRID    = False    # lat/lon tick grid (subtle 0.5° lines)

# ─── SLICE PREVIEW ───────────────────────────────────────────────────────────
# When set (not None), renders only this sub-region at full print specs as a
# vector PDF.  Use this to verify hair-thin line widths without paying the
# render cost of the full 9 × 8 ft figure.
# Set to None to render the full BOUNDS.
SLICE_BOUNDS = None   # full bounds render

# ─── PATHS ───────────────────────────────────────────────────────────────────
DATA_DIR   = 'data'
OUTPUT_DIR = 'output'
DEM_PATH   = f'{DATA_DIR}/dem.tif'
OSM_PATH   = f'{DATA_DIR}/osm_data.gpkg'
