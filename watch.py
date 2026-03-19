#!/usr/bin/env python3
"""
watch.py (SAFE MODE)

- Electron microscopy papers from arXiv
- Try to create GitHub Issue
- NEVER exits with code 1 (for GitHub Actions)
"""

import feedparser
import datetime
import os
import requests
import sys

# =========================
# GitHub settings
# =========================

GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# =========================
# arXiv settings
# =========================

ARXIV_QUERY = (
    'search_query=all:"electron microscopy"'
    '+OR+all:TEM+OR+all:STEM+OR+all:SEM'
    '&start=0&max_results=20'
)
ARXIV_API_URL = "http://export.arxiv.org/api/query?"

# =========================
# Keywords
# =========================

EM_CORE_KEYWORDS = [
    "electron microscopy",
    "tem", "stem", "sem",
]

NEGATIVE_KEYWORDS = [
    "nuclear reactor",
    "rocket",
    "fission",
]

# =========================
# Utils
# =========================

def contains_any(text, keywords):
    text = text.lower()
    return any(k in text for k in keywords)

def contains_negative(text):
    text = text.lower()
    return any(k in text for k in NEGATIVE_KEYWORDS)

# =========================
# Fetch papers
# =========================

def fetch_papers():
    feed = feedparser.parse(ARXIV_API_URL + ARXIV_QUERY)
    papers = []

    for e in feed.entries:
        text = f"{e.title} {e.summary}"
