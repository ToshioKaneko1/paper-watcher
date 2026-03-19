#!/usr/bin/env python3
"""
watch.py
Electron microscopy arXiv watcher

- TEM / STEM / SEM を必須条件に広く収集
- Issue 作成には TOKEN_1 / REPO を使用
"""

import feedparser
import datetime
import os
import requests
import sys

# =========================
# GitHub settings
# =========================

GITHUB_TOKEN = os.environ.get("TOKEN_1")   # ← TOKEN_1 を使用
GITHUB_REPO  = os.environ.get("REPO")      # ← "username/reponame"

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

        if not contains_any(text, EM_CORE_KEYWORDS):
            continue
        if contains_negative(text):
            continue

        papers.append({
            "title": e.title.replace("\n", " "),
            "link": e.link,
        })

    return papers

# =========================
# Create GitHub Issue
# =========================

def try_create_issue(papers):
    if not GITHUB_TOKEN:
        print("[WARN] TOKEN_1 not set. Skip issue creation.")
        return

    if not GITHUB_REPO:
        print("[WARN] REPO not set. Skip issue creation.")
        return

    today = datetime.date.today().isoformat()
    title = f"Electron Microscopy Papers ({today})"

    body = "## 🧪 New Electron Microscopy Papers\n\n"
    for p in papers:
        body += f"- {p['link']}\n"

    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.post(url, headers=headers, json={
        "title": title,
        "body": body
    })

    print("[INFO] GitHub status:", r.status_code)
    print("[INFO] GitHub response:", r.text)

# =========================
# Main
# =========================

def main():
    print("[INFO] watch.py started")

    papers = fetch_papers()
    print(f"[INFO] found {len(papers)} papers")

    if papers:
        try_create_issue(papers)
    else:
        print("[INFO] no papers today")

    print("[INFO] watch.py finished normally")

if __name__ == "__main__":
    main()
    sys.exit(0)
