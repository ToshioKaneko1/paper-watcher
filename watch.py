#!/usr/bin/env python3
"""
watch.py
Electron microscopy arXiv watcher

- TEM / STEM / SEM を必須条件に広く収集
- EELS / 4D-STEM などは「加点」にして絞りすぎない
- 該当論文があれば GitHub Issue を自動作成
- 環境変数は TOKEN_1 / REPO を使用（GITHUB_*は不使用）
- arXiv API URLは urlencode で安全に生成（InvalidURL対策）
"""

import datetime
import os
import sys
from urllib.parse import urlencode

import feedparser
import requests
from typing import List, Dict

# =========================
# 0) Environment variables (NO "GITHUB_*")
# =========================
TOKEN_1 = os.environ.get("TOKEN_1")   # GitHub Issues 作成用 PAT
REPO = os.environ.get("REPO")         # "username/reponame"


# =========================
# 1) arXiv query (safe URL encoding)
# =========================
ARXIV_BASE_URL = "https://export.arxiv.org/api/query?"

# 「電子顕微鏡」を広く拾う（必須軸）
# NOTE: arXiv advanced queryはスペースや引用符で壊れやすいので、
#       + で結合した形式を使い、urlencode でエンコードします。
ARXIV_SEARCH_QUERY = "all:electron+microscopy OR all:TEM OR all:STEM OR all:SEM"

ARXIV_PARAMS = {
    "search_query": ARXIV_SEARCH_QUERY,
    "start": 0,
    "max_results": 30,
}
ARXIV_URL = ARXIV_BASE_URL + urlencode(ARXIV_PARAMS)


# =========================
# 2) Filtering / scoring keywords
# =========================
# 必須条件（このどれかが title+abstract に含まれる）
EM_CORE_KEYWORDS = [
    "electron microscopy",
    "tem", "stem", "sem",
    "transmission electron",
    "scanning electron",
]

# 加点（絞らず順位付けに利用）
EM_METHOD_KEYWORDS = {
    "eels": 2.0,
    "4d-stem": 2.0,
    "dpc": 1.5,
    "ptychography": 1.5,
    "tomography": 1.5,
    "ebsd": 1.2,
    "edx": 1.2,
    "haadf": 1.0,
    "bf-stem": 1.0,
    "in-situ": 1.2,
    "cryo-em": 1.2,
    "diffraction": 1.0,
}

# 明らかにズレやすい領域の除外（軽め）
NEGATIVE_KEYWORDS = [
    "nuclear reactor",
    "rocket",
    "propulsion",
    "fission",
    "astrophysics",
    "cosmic",
]


# =========================
# 3) Utility functions
# =========================
def contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)

def contains_negative(text: str) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in NEGATIVE_KEYWORDS)

def em_score(text: str) -> float:
    """Electron microscopy relevance score."""
    t = text.lower()
    score = 5.0  # base
    for k, w in EM_METHOD_KEYWORDS.items():
        if k in t:
            score += w
    return score


# =========================
# 4) Fetch papers from arXiv
# =========================
def fetch_papers() -> List[Dict]:
    feed = feedparser.parse(ARXIV_URL)

    papers = []
    for entry in getattr(feed, "entries", []):
        title = entry.title.replace("\n", " ").strip()
        abstract = entry.summary.replace("\n", " ").strip()
        link = entry.link

        text = f"{title} {abstract}"

        # 必須：電子顕微鏡が主題であること
        if not contains_any(text, EM_CORE_KEYWORDS):
            continue

        # 除外（軽め）
        if contains_negative(text):
            continue

        papers.append({
            "title": title,
            "link": link,
            "score": em_score(text),
        })

    papers.sort(key=lambda x: x["score"], reverse=True)
    return papers


# =========================
# 5) Create GitHub Issue
# =========================
def create_issue(papers: List[Dict]) -> None:
    if not TOKEN_1:
        print("[WARN] TOKEN_1 not set -> skip issue creation")
        return
    if not REPO:
        print("[WARN] REPO not set -> skip issue creation")
        return

    today = datetime.date.today().isoformat()
    issue_title = f"Electron Microscopy Papers ({today})"

    body_lines = ["## 🧪 New Electron Microscopy Papers", ""]
    for p in papers:
        body_lines.append(f"- **{p['title']}**")
        body_lines.append(f"  - {p['link']}")
        body_lines.append(f"  - EM score: {p['score']:.1f}")
        body_lines.append("")
    body = "\n".join(body_lines)

    url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {
        "Authorization": f"token {TOKEN_1}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.post(url, headers=headers, json={
        "title": issue_title,
        "body": body,
        "labels": ["arxiv-watch", "electron-microscopy"],
    })

    print("[INFO] GitHub issue POST status:", r.status_code)
    print("[INFO] GitHub response:", r.text)


# =========================
# 6) Main (safe: never exit 1)
# =========================
def main():
    print("[INFO] watch.py started")
    print("[INFO] arXiv URL:", ARXIV_URL)

    papers = fetch_papers()
    print(f"[INFO] found {len(papers)} papers")

    if papers:
        create_issue(papers)
    else:
        print("[INFO] no relevant papers today")

    print("[INFO] watch.py finished normally")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print("[ERROR] Unhandled exception occurred")
        traceback.print_exc()
    sys.exit(0)
