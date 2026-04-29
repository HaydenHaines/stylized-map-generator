"""
Oklahoma Topo Map — Configuration
==================================
All tuneable parameters live here.
Tweak and re-run 02_render_map.py to see changes.
No need to touch the render script itself for style changes.
"""

import numpy as np

# ─── GEOGRAPHIC BOUNDS ─────────────────────────────────────────────────────
# Coverage: just east of Tulsa to just west of Oklahoma City
# Sized to fill a 9 × 8 foot wall at the latitude correction for ~36 °N.
# At 36 °N: 1° lon ≈ 90 km, 1° lat ≈ 111 km  →  ratio ≈ 0.81
# Our Δlon=1.70° × 0.81 = 1.377 "lat-equivalent degrees"
# Our Δlat=1.22°  →  ratio 1.377/1.22 ≈ 1.128  ≈  9/8  ✓

BOUNDS = {
    'west':  -98.45,   # +30 mi bleed west (kept 9:8 aspect → ~33 mi here)
    'east':  -95.10,   # +30 mi bleed east (~33 mi to match aspect)
    'south':  34.60,   # +30 mi bleed south
    'north':  37.00,   # +30 mi bleed north
}

# Latitude used for aspect-ratio + hillshade cell-size corrections
LAT_CENTER = (BOUNDS['north'] + BOUNDS['south']) / 2   # ≈ 35.8 °N

# ─── WALL / OUTPUT DIMENSIONS ───────────────────────────────────────────────
WALL_WIDTH_FEET  = 9
WALL_HEIGHT_FEET = 8

# ── PREVIEW vs. PRINT ──────────────────────────────────────────────────────
# PREVIEW = True  → fast, screen-resolution render (good for style iteration)
# PREVIEW = False → full print-resolution export (slow, large file)
PREVIEW       = True

PREVIEW_DPI   = 300        # DPI for preview PNG  (was 120 — 300 lets thin lines/contours resolve)
PREVIEW_WIDTH = 14.0       # figure width in inches for preview (height auto-calculated)

PRINT_DPI     = 150        # DPI for final print export
#   At 150 DPI:  9 ft × 150 = 16 200 px wide,  8 ft × 150 = 14 400 px tall

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
    'contour':         '#B8AEA1',   # lighter topo (regular contours)
    'index_contour':   '#93897D',   # primary topo (index contours, labels)
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

# ─── HILLSHADE ───────────────────────────────────────────────────────────────
HS_AZIMUTH   = 320    # degrees — NW light source (classic cartographic convention)
HS_ALTITUDE  = 40     # degrees above horizon
HS_VERT_EXAG = 6.0    # vertical exaggeration (Oklahoma topography is subtle — push it)
HS_ALPHA     = 0.0    # 0 = off (clean white base for Photoshop).  Set to 0.3–0.4 to re-enable.

# ─── TYPOGRAPHY ──────────────────────────────────────────────────────────────
# Sizes are in points and designed for the PREVIEW figure.
# The render script scales them up for the print figure automatically.
FONT_FAMILY = 'serif'    # built-in matplotlib serif; swap for 'IM Fell English'
               #   or 'Libre Baskerville' if you install them via matplotlib font cache

# Font sizes are in points and tuned for the PREVIEW figure (14 in wide).
# They scale up automatically for the print figure.
FONT = {
    'city':      {'size': 9.0,  'weight': 'bold',   'style': 'normal'},
    'town':      {'size': 7.0,  'weight': 'normal',  'style': 'normal'},
    'village':   {'size': 5.5,  'weight': 'normal',  'style': 'italic'},
    'hamlet':    {'size': 4.5,  'weight': 'normal',  'style': 'italic'},
    'contour':   {'size': 4.0,  'weight': 'normal',  'style': 'normal'},
    'title':     {'size': 28.0, 'weight': 'bold',   'style': 'normal'},
    'subtitle':  {'size': 14.0, 'weight': 'normal',  'style': 'italic'},
}

# ─── LEGEND / TITLE ──────────────────────────────────────────────────────────
MAP_TITLE    = "COMMERCIAL ROUTES OF OKLAHOMA"
MAP_SUBTITLE = "Showing Principal Roads, Rails, Rivers, and Trade Corridors"
SHOW_TITLE   = False    # set False to suppress the title block
SHOW_LEGEND  = True     # set False to suppress the legend

# ─── PATHS ───────────────────────────────────────────────────────────────────
DATA_DIR   = 'data'
OUTPUT_DIR = 'output'
DEM_PATH   = f'{DATA_DIR}/dem.tif'
OSM_PATH   = f'{DATA_DIR}/osm_data.gpkg'
