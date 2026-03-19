#!/usr/bin/env python3
"""
watch.py
Electron microscopy focused arXiv watcher

- Broad coverage: TEM / STEM / SEM
- No over-filtering to EELS / 4D-STEM
- Ranking by "electron microscopy relevance"
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

# --- 必須：電子顕微鏡 ---
EM_CORE_KEYWORDS = [
    "electron microscopy",
    "tem", "stem", "sem",
    "transmission electron",
    "scanning electron"
]

# --- 加点：手法・拡張 ---
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

# --- 除外（軽め） ---
NEGATIVE_KEYWORDS = [
    "nuclear reactor",
    "rocket",
    "propulsion",
    "fission",
    "astrophysics",
    "cosmic",
    "stellar",
]


# =========================
# 3. Utility functions
# =========================

def contains_any(text: str, keywords: List[str]) -> bool:
    text = text.lower()
    return any(k in text for k in keywords)


def contains_negative(text: str) -> bool:
    text = text.lower()
    return any(k in text for k in NEGATIVE_KEYWORDS)


def electron_microscopy_score(text: str) -> float:
    """
    Score how strongly this paper is about electron microscopy
    """
    text = text.lower()
    score = 0.0

    # 基本点（電子顕微鏡が主題）
    score += 5.0

    for kw, weight in EM_METHOD_KEYWORDS.items():
        if kw in text:
            score += weight

    return score


# =========================
# 4. Fetch & filter papers
# =========================

def fetch_papers() -> List[Dict]:
    feed = feedparser.parse(ARXIV_API_URL + ARXIV_QUERY)
    results = []

    for entry in feed.entries:
        title = entry.title
        abstract = entry.summary
        text = f"{title} {abstract}"

        # --- 必須条件 ---
        if not contains_any(text, EM_CORE_KEYWORDS):
            continue

        # --- 明確な除外 ---
        if contains_negative(text):
            continue

        score = electron_microscopy_score(text)

        results.append({
            "title": title.strip().replace("\n", " "),
            "authors": ", ".join(a.name for a in entry.authors),
            "published": entry.published[:10],
            "link": entry.link,
            "summary": abstract.strip().replace("\n", " "),
            "score": score,
        })

    return results


# =========================
# 5. Main
# =========================

def main():
    papers = fetch_papers()

    # 電子顕微鏡スコア順に並び替え
    papers.sort(key=lambda x: x["score"], reverse=True)

    today = datetime.date.today().isoformat()
    print(f"\n=== Electron Microscopy Watch ({today}) ===\n")

    for p in papers:
        print(f"[Score {p['score']:.1f}] {p['title']}")
        print(f"  Authors : {p['authors']}")
        print(f"  Date    : {p['published']}")
        print(f"  Link    : {p['link']}")
        print("")

    if not papers:
        print("No relevant electron microscopy papers found.")


if __name__ == "__main__":
    main()
