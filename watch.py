#!/usr/bin/env python3
"""
watch.py
Electron microscopy focused arXiv watcher
"""

import feedparser
import datetime
from typing import List, Dict

# =========================
# 1. arXiv search settings
# =========================

ARXIV_QUERY = (
    'search_query=all:"electron microscopy"'
    '+OR+all:TEM+OR+all:STEM+OR+all:SEM'
    '&start=0&max_results=50'
)

ARXIV_API_URL = "http://export.arxiv.org/api/query?"

# =========================
# 2. Keyword definitions
# =========================

EM_CORE_KEYWORDS = [
    "electron microscopy",
    "tem", "stem", "sem",
    "transmission electron",
    "scanning electron"
]

EM_METHOD_KEYWORDS = {
    "eels": 2.0,
    "4d-stem": 2.0,
    "dpc": 1.5,
    "ptychography": 1.5,
    "tomography": 1.5,
    "ebsd": 1.2,
    "in-situ": 1.2,
    "cryo-em": 1.2,
    "diffraction": 1.0,
    "haadf": 1.0,
    "bf-stem": 1.0,
}

NEGATIVE_KEYWORDS = [
    "nuclear reactor",
    "rocket",
    "propulsion",
    "fission",
    "astrophysics",
    "cosmic",
]

# =========================
# 3. Utility functions
# =========================

