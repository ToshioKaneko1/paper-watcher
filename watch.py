#!/usr/bin/env python3
"""
watch.py (Tech Spotlight edition)

Output:
  - 1 paper: Tech Spotlight (advanced EM techniques)
  - 5 papers: General EM (TEM/STEM/SEM/electron microscopy)

Env vars (NO GITHUB_*):
  - TOKEN_1 : GitHub PAT for creating issues
  - REPO    : "username/reponame"
"""

import datetime
import os
import sys
from typing import List, Dict, Tuple
from urllib.parse import urlencode

import feedparser
import requests

# =========================
# Env vars (NO "GITHUB_*")
# =========================
TOKEN_1 = os.environ.get("TOKEN_1")   # GitHub PAT
REPO = os.environ.get("REPO")         # "username/reponame"

# =========================
# arXiv query (safe URL)
# =========================
ARXIV_BASE_URL = "https://export.arxiv.org/api/query?"
ARXIV_SEARCH_QUERY = "all:electron+microscopy OR all:TEM OR all:STEM OR all:SEM"

ARXIV_PARAMS = {
    "search_query": ARXIV_SEARCH_QUERY,
    "start": 0,
    "max_results": 200,
    "sortBy": "submittedDate",
    "sortOrder": "descending",
}
ARXIV_URL = ARXIV_BASE_URL + urlencode(ARXIV_PARAMS)

# =========================
# Filters
# =========================
NEGATIVE_KEYWORDS = [
    "nuclear reactor", "fission", "rocket", "propulsion",
    "astrophysics", "cosmic", "stellar"
]

# "General EM" gate (broad but real)
EM_CORE_KEYWORDS = [
    "electron microscopy",
    "transmission electron",
    "scanning electron",
    "tem", "stem", "sem",
]

# =========================
# Tech Spotlight keywords (your request)
# =========================
# Each entry: keyword variants -> weight
TECH_KEYWORDS = {
    # Monochromated / monochromator EELS
    "Monochromated EELS": ([
        "monochromated eels", "monochromated", "monochromator",
        "monochromatic eels"
    ], 4.0),

    # 4D-STEM
    "4D-STEM": ([
        "4d-stem", "4d stem", "four-dimensional stem", "4dstem",
        "4d scanning transmission"
    ], 4.0),

    # VEELS
    "VEELS": ([
        "veels", "valence eels", "valence electron energy loss"
    ], 3.5),

    # Vibrational EELS
    "Vibrational EELS": ([
        "vibrational eels", "phonon eels", "vibrational spectroscopy eels",
        "aloof eels", "phonon spectroscopy"
    ], 4.0),

    # High-res STEM-EDX/EDS
    "High-res STEM-EDX": ([
        "stem-edx", "stem edx", "atomic-resolution edx", "atomic resolution edx",
        "stem-eds", "stem eds", "atomic-resolution eds", "x-ray mapping",
        "high resolution edx", "high-resolution edx"
    ], 3.5),

    # Damage-less / low-dose
    "Damage-less / Low-dose": ([
        "low dose", "dose-efficient", "dose efficiency", "damage-free",
        "beam sensitive", "beam-sensitive", "radiation damage", "damage mitigation",
        "cryo", "cryogenic"
    ], 3.0),

    # Phase contrast / phase imaging
    "Phase contrast": ([
        "phase contrast", "phase-contrast", "phase imaging",
        "electron holography", "off-axis holography",
        "dpc", "differential phase contrast"
    ], 3.0),

    # Ptychography
    "Ptychography": ([
        "ptychography", "electron ptychography", "ptychographic", "4d ptychography"
    ], 4.0),
}

# Extra signals that indicate "method paper"
METHOD_SIGNALS = {
    "algorithm": 0.8,
    "method": 0.8,
    "framework": 0.6,
    "instrumentation": 0.8,
    "detector": 0.8,
    "aberration-corrected": 0.8,
    "aberration corrected": 0.8,
}


def contains_negative(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in NEGATIVE_KEYWORDS)


def is_em_paper(title: str, abstract: str) -> bool:
    t = (title + " " + abstract).lower()
    return any(k in t for k in EM_CORE_KEYWORDS)


def em_score(title: str, abstract: str) -> float:
    """General EM ranking score."""
    t = (title + " " + abstract).lower()
    score = 0.0

    # core mention boosts
    for k in EM_CORE_KEYWORDS:
        if k in t:
            score += 1.0

    # method signals
    for k, w in METHOD_SIGNALS.items():
        if k in t:
            score += w

    # title boost
    tl = title.lower()
    if "electron microscopy" in tl or "tem" in tl or "stem" in tl or "sem" in tl:
        score += 1.0

    return score


def tech_score(title: str, abstract: str) -> Tuple[float, List[str]]:
    """
    Tech Spotlight score + matched labels.
    """
    t = (title + " " + abstract).lower()
    score = 0.0
    matched = []

    for label, (variants, w) in TECH_KEYWORDS.items():
        if any(v in t for v in variants):
            score += w
            matched.append(label)

    # small extra for being explicitly methodological
    for k, w in METHOD_SIGNALS.items():
        if k in t:
            score += 0.2 * w

    return score, matched


def arxiv_id(entry) -> str:
    return entry.id.split("/abs/")[-1].strip()


def fetch_candidates() -> List[Dict]:
    feed = feedparser.parse(ARXIV_URL)
    items = []

    for e in getattr(feed, "entries", []):
        title = e.title.replace("\n", " ").strip()
        abstract = e.summary.replace("\n", " ").strip()

        if contains_negative(title + " " + abstract):
            continue

        if not is_em_paper(title, abstract):
            continue

        ems = em_score(title, abstract)
        tscore, matched = tech_score(title, abstract)

        items.append({
            "title": title,
            "abs": e.link,
            "pdf": f"https://arxiv.org/pdf/{arxiv_id(e)}.pdf",
            "published": getattr(e, "published", "")[:10],
            "em_score": ems,
            "tech_score": tscore,
            "tech_matched": matched,
        })

    # sort by EM score for general pool
    items.sort(key=lambda x: (x["em_score"], x["tech_score"]), reverse=True)
    return items


def pick_spotlight_and_general(items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Spotlight: highest tech_score (>0)
    General: top 5 by em_score excluding spotlight
    """
    spotlight = []
    candidates_spot = [x for x in items if x["tech_score"] > 0]

    if candidates_spot:
        # choose the strongest tech paper; tie-break by em_score
        candidates_spot.sort(key=lambda x: (x["tech_score"], x["em_score"]), reverse=True)
        spotlight = [candidates_spot[0]]

    used = {x["abs"] for x in spotlight}
    general = [x for x in items if x["abs"] not in used][:5]
    return spotlight, general


def create_issue(spotlight: List[Dict], general: List[Dict]) -> None:
    if not TOKEN_1:
        print("[WARN] TOKEN_1 not set -> skip issue creation")
        return
    if not REPO:
        print("[WARN] REPO not set -> skip issue creation")
        return

    today = datetime.date.today().isoformat()
    issue_title = f"EM Tech Watch ({today})"

    lines = []
    lines.append("## ⭐ Tech Spotlight（注目“技術”・最大1件）")
    if spotlight:
        p = spotlight[0]
        matched = ", ".join(p["tech_matched"]) if p["tech_matched"] else "(no label)"
        lines.append(f"- **{p['title']}**")
        lines.append(f"  - matched: {matched}")
        lines.append(f"  - abs: {p['abs']}")
        lines.append(f"  - pdf: {p['pdf']}")
        lines.append(f"  - tech_score: {p['tech_score']:.1f} / em_score: {p['em_score']:.1f}")
        lines.append(f"  - published: {p['published']}")
    else:
        lines.append("- 該当なし（今回の候補内で“注目技術”キーワードにヒットしませんでした）")

    lines.append("")
    lines.append("## 📚 General EM（電子顕微鏡関連・最大5件）")
    for p in general:
        lines.append(f"- **{p['title']}**")
        lines.append(f"  - abs: {p['abs']}")
        lines.append(f"  - pdf: {p['pdf']}")
        lines.append(f"  - em_score: {p['em_score']:.1f} / tech_score: {p['tech_score']:.1f}")
        lines.append(f"  - published: {p['published']}")
        lines.append("")

    body = "\n".join(lines)

    r = requests.post(
        f"https://api.github.com/repos/{REPO}/issues",
        headers={
            "Authorization": f"token {TOKEN_1}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": issue_title,
            "body": body,
            "labels": ["arxiv-watch", "electron-microscopy", "tech-spotlight"],
        },
        timeout=30,
    )

    print("[INFO] Issue status:", r.status_code)
    if r.status_code not in (201, 200):
        print("[INFO] Issue response:", r.text)


def main():
    print("[INFO] watch.py started")
    print("[INFO] arXiv URL:", ARXIV_URL)

    items = fetch_candidates()
    print(f"[INFO] EM candidates: {len(items)}")

    spotlight, general = pick_spotlight_and_general(items)
    print(f"[INFO] picked spotlight: {len(spotlight)}, general: {len(general)}")

    create_issue(spotlight, general)
    print("[INFO] watch.py finished normally")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print("[ERROR] Unhandled exception occurred")
        traceback.print_exc()
    sys.exit(0)
