#!/usr/bin/env python3
"""
watch.py (final improved version)

- Electron Microscopy arXiv watcher
- Output:
    * 1 paper: Priority institution × EM-related (loose EM)
    * 5 papers: Other institutions × EM-focused (strict EM)
- Post to GitHub Issues using TOKEN_1 / REPO
"""

import datetime
import io
import os
import re
import sys
from typing import List, Dict
from urllib.parse import urlencode

import feedparser
import requests

# PDF (for affiliation detection)
try:
    from PyPDF2 import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# =========================
# Environment variables
# =========================
TOKEN_1 = os.environ.get("TOKEN_1")   # GitHub PAT
REPO = os.environ.get("REPO")         # "username/reponame"


# =========================
# arXiv query
# =========================
ARXIV_BASE_URL = "https://export.arxiv.org/api/query?"
ARXIV_SEARCH_QUERY = "all:electron+microscopy OR all:TEM OR all:STEM OR all:SEM"

ARXIV_PARAMS = {
    "search_query": ARXIV_SEARCH_QUERY,
    "start": 0,
    "max_results": 100,
    "sortBy": "submittedDate",
    "sortOrder": "descending",
}
ARXIV_URL = ARXIV_BASE_URL + urlencode(ARXIV_PARAMS)


# =========================
# EM判定
# =========================
EM_STRICT_KEYWORDS = [
    "electron microscopy",
    "transmission electron",
    "scanning electron",
    "tem", "stem", "sem",
]

EM_LOOSE_KEYWORDS = EM_STRICT_KEYWORDS + [
    "eels", "haadf", "edx", "ebsd", "4d-stem", "ptychography"
]

NEGATIVE_KEYWORDS = [
    "nuclear reactor", "fission",
    "rocket", "propulsion",
    "astrophysics", "cosmic"
]


def contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def contains_negative(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in NEGATIVE_KEYWORDS)


def is_em_strict(title: str, abstract: str) -> bool:
    t = (title + " " + abstract).lower()
    return contains_any(t, EM_STRICT_KEYWORDS)


def is_em_loose(title: str, abstract: str) -> bool:
    t = (title + " " + abstract).lower()
    return contains_any(t, EM_LOOSE_KEYWORDS)


def em_score(title: str, abstract: str) -> float:
    score = 5.0
    t = (title + " " + abstract).lower()
    for k in EM_LOOSE_KEYWORDS:
        if k in t:
            score += 0.5
    if "electron microscopy" in title.lower():
        score += 1.0
    return score


# =========================
# 注目機関パターン
# =========================
PRIORITY_PATTERNS = [
    # Universities (JP)
    r"university of tokyo", r"東京大学",
    r"osaka university", r"大阪大学",
    r"kyoto university", r"京都大学",
    r"nagoya university", r"名古屋大学",
    r"kyushu university", r"九州大学",
    r"tohoku university", r"東北大学",
    r"hokkaido university", r"北海道大学",

    # Institutes
    r"\bnims\b", r"物質・材料研究機構",
    r"\baist\b", r"産業技術総合研究所",
    r"\bjfcc\b", r"ファインセラミックスセンター",

    # Companies
    r"\bjeol\b", r"日本電子",
    r"\bhitachi\b", r"日立",
    r"\bsamsung\b", r"サムスン",
    r"\btoshiba\b", r"東芝",
    r"\bkioxia\b",

    # US
    r"\bmit\b", r"massachusetts institute of technology",
    r"columbia university",
    r"university of california", r"uc berkeley", r"ucla",
]

PRIORITY_RE = re.compile("|".join(PRIORITY_PATTERNS), re.IGNORECASE)


def is_priority_affiliation(text: str) -> bool:
    return bool(text) and PRIORITY_RE.search(text) is not None


# =========================
# arXiv helpers
# =========================
def arxiv_id(entry) -> str:
    return entry.id.split("/abs/")[-1]


def pdf_url(entry) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id(entry)}.pdf"


def extract_affiliation_from_pdf(pdf_bytes: bytes) -> str:
    if not PDF_AVAILABLE:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.pages:
            return reader.pages[0].extract_text() or ""
    except Exception:
        pass
    return ""


# =========================
# Fetch & classify
# =========================
def fetch_candidates() -> List[Dict]:
    feed = feedparser.parse(ARXIV_URL)
    items = []

    for e in getattr(feed, "entries", []):
        title = e.title.replace("\n", " ").strip()
        abstract = e.summary.replace("\n", " ").strip()

        if contains_negative(title + " " + abstract):
            continue

        em_strict = is_em_strict(title, abstract)
        em_loose = is_em_loose(title, abstract)

        if not (em_strict or em_loose):
            continue

        items.append({
            "title": title,
            "abstract": abstract,
            "abs": e.link,
            "pdf": pdf_url(e),
            "published": getattr(e, "published", "")[:10],
            "score": em_score(title, abstract),
            "em_strict": em_strict,
            "em_loose": em_loose,
            "aff_text": getattr(e, "arxiv_affiliation", "") or "",
            "is_priority": False,
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def enrich_priority_flags(items: List[Dict], max_pdf: int = 25) -> None:
    for it in items[:max_pdf]:
        aff = it["aff_text"]
        if PDF_AVAILABLE:
            try:
                r = requests.get(it["pdf"], timeout=20)
                if r.status_code == 200:
                    aff += " " + extract_affiliation_from_pdf(r.content)
            except Exception:
                pass
        it["is_priority"] = is_priority_affiliation(aff)


def pick_1_plus_5(items: List[Dict]):
    priority = [x for x in items if x["is_priority"] and x["em_loose"]]
    others = [x for x in items if (not x["is_priority"]) and x["em_strict"]]

    top_priority = priority[:1]
    used = {x["abs"] for x in top_priority}
    top_others = [x for x in others if x["abs"] not in used][:5]

    return top_priority, top_others


# =========================
# Issue creation
# =========================
def create_issue(top_priority, top_others):
    if not TOKEN_1 or not REPO:
        print("[WARN] TOKEN_1 or REPO not set")
        return

    today = datetime.date.today().isoformat()
    title = f"Electron Microscopy Watch ({today})"

    lines = ["## ⭐ 注目機関（電子顕微鏡関連）"]
    if top_priority:
        p = top_priority[0]
        lines += [
            f"- **{p['title']}**",
            f"  - abs: {p['abs']}",
            f"  - pdf: {p['pdf']}",
            f"  - score: {p['score']:.1f}",
        ]
    else:
        lines.append("- 該当なし")

    lines.append("\n## 📚 その他（電子顕微鏡関連）")
    for p in top_others:
        lines += [
            f"- **{p['title']}**",
            f"  - abs: {p['abs']}",
            f"  - pdf: {p['pdf']}",
            f"  - score: {p['score']:.1f}",
            "",
        ]

    body = "\n".join(lines)

    r = requests.post(
        f"https://api.github.com/repos/{REPO}/issues",
        headers={
            "Authorization": f"token {TOKEN_1}",
            "Accept": "application/vnd.github+json",
        },
        json={"title": title, "body": body, "labels": ["electron-microscopy"]},
    )

    print("[INFO] Issue status:", r.status_code)


# =========================
# Main
# =========================
def main():
    print("[INFO] watcher started")
    items = fetch_candidates()
    enrich_priority_flags(items)
    top_priority, top_others = pick_1_plus_5(items)
    create_issue(top_priority, top_others)
    print("[INFO] watcher finished")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
    sys.exit(0)
