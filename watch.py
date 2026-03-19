#!/usr/bin/env python3
"""
watch.py
Electron microscopy arXiv watcher
- Fetch papers
- Create GitHub Issue if papers are found
"""

import feedparser
import datetime
import os
import requests
from typing import List

# =========================
# GitHub settings
# =========================

GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")  # owner/repo
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# =========================
# arXiv settings
# =========================

ARXIV_QUERY = (
    'search_query=all:"electron microscopy"'
    '+OR+all:TEM+OR+all:STEM+OR+all:SEM'
    '&start=0&max_results=30'
)

ARXIV_API_URL = "http://export.arxiv.org/api/query?"

# =========================
# Keywords
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
    "ptychography": 1.5,
    "tomography": 1.5,
    "dpc": 1.5,
    "ebsd": 1.2,
}

NEGATIVE_KEYWORDS = [
    "nuclear reactor",
    "rocket",
    "propulsion",
    "fission",
    "astrophysics",
]

# =========================
# Utility
# =========================

def contains_any(text: str, keywords: List[str]) -> bool:
    text = text.lower()
    return any(k in text for k in keywords)

def contains_negative(text: str) -> bool:
    text = text.lower()
    return any(k in text for k in NEGATIVE_KEYWORDS)

def score_em(text: str) -> float:
    score = 5.0
    text = text.lower()
    for k, w in EM_METHOD_KEYWORDS.items():
        if k in text:
            score += w
    return score

# =========================
# Fetch papers
# =========================

def fetch_papers():
    feed = feedparser.parse(ARXIV_API_URL + ARXIV_QUERY)
    papers = []

    for e in feed.entries:
        text = f"{e.title} {e.summary}"

        if not contains_any(text, EM_CORE_KEYWORDS):
            continue
        if contains_negative(text):
            continue

        papers.append({
            "title": e.title.replace("\n", " "),
            "link": e.link,
            "score": score_em(text),
        })

    papers.sort(key=lambda x: x["score"], reverse=True)
    return papers

# =========================
# Create GitHub Issue
# =========================

def create_issue(papers):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GitHub token or repository not set")

    today = datetime.date.today().isoformat()
    title = f"Electron Microscopy Papers ({today})"

    body_lines = [
        "## 🧪 New Electron Microscopy Papers\n"
    ]

    for p in papers:
        body_lines.append(
            f"- **[{p['title']}]({p['link']})**  \n"
            f"  EM score: {p['score']:.1f}\n"
        )

