#!/usr/bin/env python3
"""
watch.py
Electron microscopy arXiv watcher

- TEM / STEM / SEM を必須条件に広く収集
- EELS / 4D-STEM などは加点評価
- 該当論文があれば GitHub Issue を自動作成
"""

import feedparser
import datetime
import os
import requests
from typing import List

# =========================
# GitHub settings
# =========================

GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo"
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
    "in-situ": 1.2,
    "cryo-em": 1.2,
    "diffraction": 1.0,
    "haadf": 1.0,
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
# Utility
# =========================

def contains_any(text: str, keywords: List[str]) -> bool:
    text = text.lower()
    return any(k in text for k in keywords)

def contains_negative(text: str) -> bool:
    text = text.lower()
    return any(k in text for k in NEGATIVE_KEYWORDS)

def electron_microscopy_score(text: str) -> float:
    score = 5.0  # base score
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
            "score": electron_microscopy_score(text),
        })

    papers.sort(key=lambda x: x["score"], reverse=True)
    return papers

# =========================
# Create GitHub Issue
# =========================

def create_issue(papers):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GITHUB_TOKEN or GITHUB_REPOSITORY is not set")

    today = datetime.date.today().isoformat()
    title = f"Electron Microscopy Papers ({today})"

    body_lines = [
        "## 🧪 New Electron Microscopy Papers",
        ""
    ]

    for p in papers:
        body_lines.append(
            f"- [{p['link']}]({p['link']})  \n"
            f"  EM score: {p['score']:.1f}"
        )

    body = "\n".join(body_lines)

    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.post(url, headers=headers, json={
        "title": title,
        "body": body,
        "labels": ["electron-microscopy", "arxiv-watch"]
    })

    # デバッグ用（Actions ログに必ず出る）
    print("GitHub issue POST status:", r.status_code)
    print("GitHub response:", r.text)

    if r.status_code != 201:
        raise RuntimeError("Issue creation failed")

# =========================
# Main
# =========================

def main():
    papers = fetch_papers()

    if not papers:
        print("No relevant electron microscopy papers found.")
        return

    create_issue(papers)
    print(f"Created issue with {len(papers)} papers.")

if __name__ == "__main__":
    main()
