"""conftest.py — pytest root configuration for stylized-map-generator."""

import os
import pytest

# Ensure tests always run from the project root so relative paths
# in config.py (data/dem.tif, data/osm_data.gpkg) resolve correctly.
@pytest.fixture(autouse=True, scope='session')
def _project_root():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
