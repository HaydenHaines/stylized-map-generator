"""conftest.py — pytest root configuration for stylized-map-generator."""

import os
import pytest

# Ensure tests always run from the project root so relative paths
# in config.py (data/dem.tif, data/osm_data.gpkg) resolve correctly.
@pytest.fixture(autouse=True, scope='session')
def _project_root():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope='session')
def synth_data(tmp_path_factory):
    """Session-scoped fixture: synthetic DEM + OSM data in a temp directory.

    Returns a dict with keys 'dem_path' and 'osm_path' pointing to the
    generated files.  These paths are isolated from the real data/ directory
    so tests never clobber downloaded production data.
    """
    from test_render import make_synthetic_data
    from config import BOUNDS

    tmp = tmp_path_factory.mktemp('synth_data')
    dem_path = str(tmp / 'dem.tif')
    osm_path = str(tmp / 'osm_data.gpkg')
    make_synthetic_data(dem_path, osm_path, BOUNDS)
    return {'dem_path': dem_path, 'osm_path': osm_path, 'data_dir': str(tmp)}
