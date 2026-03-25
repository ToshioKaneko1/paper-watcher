#!/usr/bin/env python3
"""
watch.py (Tech Spotlight edition) - with "seen papers" exclusion (Plan A)

What it does:
  - Fetch arXiv candidates (Electron Microscopy related)
  - Exclude papers already posted in past GitHub Issues (label: arxiv-watch)
  - Pick:
      * 1 paper: Tech Spotlight (advanced EM techniques)
      * 5 papers: General EM (TEM/STEM/SEM/electron microscopy)
  - Create (or update) a GitHub Issue daily

Env vars (NO GITHUB_*):
  - TOKEN_1 : GitHub PAT for creating/updating issues and reading issues
  - REPO    : "username/reponame"

Optional env vars:
  - SEEN_ISSUE_PAGES         : how many pages of past issues to scan (100 issues/page). default: 5
  - MAX_ARXIV_PAGES          : how many arXiv pages to fetch when candidates are insufficient. default: 3
  - ARXIV_MAX_RESULTS        : max_results per arXiv API call (<=200 recommended). default: 200
  - MIN_POOL_AFTER_FILTER    : target number of candidates after seen-filter to try to collect. default: 60
  - STRIP_ARXIV_VERSION      : "1" to treat 2503.01234v2 as same as 2503.01234. default: 0
  - ISSUE_LABEL              : label used to find past issues. default: "arxiv-watch"
"""

import datetime
import os
import re
import sys
import time
from typing import List, Dict, Tuple, Set
from urllib.parse import urlencode

import feedparser
import requests

# =========================
# Env vars (NO "GITHUB_*")
# =========================
TOKEN_1 = os.environ.get("TOKEN_1")   # GitHub PAT
REPO = os.environ.get("REPO")         # "username/reponame"

SEEN_ISSUE_PAGES = int(os.environ.get("SEEN_ISSUE_PAGES", "5"))
MAX_ARXIV_PAGES = int(os.environ.get("MAX_ARXIV_PAGES", "3"))
ARXIV_MAX_RESULTS = int(os.environ.get("ARXIV_MAX_RESULTS", "200"))
MIN_POOL_AFTER_FILTER = int(os.environ.get("MIN_POOL_AFTER_FILTER", "60"))
STRIP_ARXIV_VERSION = os.environ.get("STRIP_ARXIV_VERSION", "0").strip() == "1"
ISSUE_LABEL = os.environ.get("ISSUE_LABEL", "arxiv-watch")

# =========================
# arXiv query base
# =========================
ARXIV_BASE_URL = "https://export.arxiv.org/api/query?"
ARXIV_SEARCH_QUERY = "all:electron+microscopy OR all:TEM OR all:STEM OR all:SEM"

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
# Tech Spotlight keywords
# =========================
# Each entry: keyword variants -> weight
TECH_KEYWORDS = {
    "Monochromated EELS": ([
        "monochromated eels", "monochromated", "monochromator",
        "monochromatic eels"
    ], 4.0),
    "4D-STEM": ([
        "4d-stem", "4d stem", "four-dimensional stem", "4dstem",
        "4d scanning transmission"
    ], 4.0),
    "VEELS": ([
        "veels", "valence eels", "valence electron energy loss"
    ], 3.5),
    "Vibrational EELS": ([
        "vibrational eels", "phonon eels", "vibrational spectroscopy eels",
        "aloof eels", "phonon spectroscopy"
    ], 4.0),
    "High-res STEM-EDX": ([
        "stem-edx", "stem edx", "atomic-resolution edx", "atomic resolution edx",
        "stem-eds", "stem eds", "atomic-resolution eds", "x-ray mapping",
        "high resolution edx", "high-resolution edx"
    ], 3.5),
    "Damage-less / Low-dose": ([
        "low dose", "dose-efficient", "dose efficiency", "damage-free",
        "beam sensitive", "beam-sensitive", "radiation damage", "damage mitigation",
        "cryo", "cryogenic"
    ], 3.0),
    "Phase contrast": ([
        "phase contrast", "phase-contrast", "phase imaging",
        "electron holography", "off-axis holography",
        "dpc", "differential phase contrast"
    ], 3.0),
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

# =========================
# Regex to extract arXiv IDs from issue bodies
# =========================
# Matches:
# - new style: 2503.01234 or 2503.01234v2
# - old style: cond-mat/0301234 or cond-mat/0301234v3
ARXIV_ABS_ID_RE = re.compile(
    r"arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}(v\d+)?|[a-z-]+/\d{7}(v\d+)?)",
    re.IGNORECASE
)


def normalize_arxiv_id(aid: str) -> str:
    """Optionally strip version suffix vN to treat v2 as same as v1."""
    aid = (aid or "").strip().lower()
    if STRIP_ARXIV_VERSION:
        aid = re.sub(r"v\d+$", "", aid)
    return aid


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
    if "electron microscopy" in tl or " tem" in " " + tl or " stem" in " " + tl or " sem" in " " + tl:
        score += 1.0

    return score


def tech_score(title: str, abstract: str) -> Tuple[float, List[str]]:
    """Tech Spotlight score + matched labels."""
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


def arxiv_id_from_entry(entry) -> str:
    # entry.id like "http://arxiv.org/abs/2503.01234v2"
    return entry.id.split("/abs/")[-1].strip()


def build_arxiv_url(start: int) -> str:
    params = {
        "search_query": ARXIV_SEARCH_QUERY,
        "start": start,
        "max_results": ARXIV_MAX_RESULTS,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return ARXIV_BASE_URL + urlencode(params)


# =========================
# GitHub: seen arXiv IDs from past issues
# =========================
def get_seen_arxiv_ids_from_issues(max_pages: int = 5) -> Set[str]:
    """
    Collect arXiv IDs already posted in past GitHub Issues (label: ISSUE_LABEL).
    Returns a set of normalized arXiv IDs.
    """
    seen: Set[str] = set()
    if not TOKEN_1 or not REPO:
        return seen

    session = requests.Session()
    session.headers.update({
        "Authorization": f"token {TOKEN_1}",
        "Accept": "application/vnd.github+json",
    })

    for page in range(1, max_pages + 1):
        r = session.get(
            f"https://api.github.com/repos/{REPO}/issues",
            params={
                "state": "all",
                "labels": ISSUE_LABEL,
                "per_page": 100,
                "page": page,
            },
            timeout=30,
        )
        if r.status_code != 200:
            print("[WARN] cannot fetch issues:", r.status_code, r.text[:200])
            break

        issues = r.json()
        if not issues:
            break

        for iss in issues:
            # Skip PRs: GitHub returns PRs in /issues endpoint
            if "pull_request" in iss:
                continue
            body = iss.get("body") or ""
            for m in ARXIV_ABS_ID_RE.finditer(body):
                seen.add(normalize_arxiv_id(m.group(1)))

        # gentle sleep to avoid rate spikes
        time.sleep(0.2)

    print(f"[INFO] seen arXiv IDs from issues: {len(seen)}")
    return seen


def find_today_issue_number(session: requests.Session, today_title: str) -> int:
    """
    If today's issue already exists (any state) with our label, return issue number else 0.
    This prevents duplicates when the job reruns.
    """
    for page in range(1, 4):  # usually enough
        r = session.get(
            f"https://api.github.com/repos/{REPO}/issues",
            params={
                "state": "all",
                "labels": ISSUE_LABEL,
                "per_page": 100,
                "page": page,
            },
            timeout=30,
        )
        if r.status_code != 200:
            return 0
        issues = r.json()
        if not issues:
            return 0
        for iss in issues:
            if "pull_request" in iss:
                continue
            if (iss.get("title") or "").strip() == today_title:
                return int(iss.get("number") or 0)
    return 0


# =========================
# arXiv candidates (with seen-filter and pagination)
# =========================
def fetch_candidates_page(arxiv_url: str, seen_ids: Set[str]) -> List[Dict]:
    feed = feedparser.parse(arxiv_url)
    items: List[Dict] = []

    for e in getattr(feed, "entries", []):
        raw_id = arxiv_id_from_entry(e)
        aid = normalize_arxiv_id(raw_id)

        # seen filter
        if aid in seen_ids:
            continue

        title = e.title.replace("\n", " ").strip()
        abstract = e.summary.replace("\n", " ").strip()

        if contains_negative(title + " " + abstract):
            continue
        if not is_em_paper(title, abstract):
            continue

        ems = em_score(title, abstract)
        tscore, matched = tech_score(title, abstract)

        abs_link = e.link
        items.append({
            "title": title,
            "abs": abs_link,
            "pdf": f"https://arxiv.org/pdf/{raw_id}.pdf",
            "published": getattr(e, "published", "")[:10],
            "em_score": ems,
            "tech_score": tscore,
            "tech_matched": matched,
            "arxiv_id": aid,
        })

    return items


def fetch_candidates(seen_ids: Set[str]) -> List[Dict]:
    """
    Fetch multiple pages from arXiv if needed, until MIN_POOL_AFTER_FILTER is reached
    or MAX_ARXIV_PAGES is exhausted.
    """
    all_items: List[Dict] = []
    used_abs: Set[str] = set()
    used_id: Set[str] = set()

    for page in range(MAX_ARXIV_PAGES):
        start = page * ARXIV_MAX_RESULTS
        url = build_arxiv_url(start)
        print("[INFO] arXiv URL:", url)

        page_items = fetch_candidates_page(url, seen_ids)

        # de-dup within this run
        for it in page_items:
            if it["abs"] in used_abs:
                continue
            if it["arxiv_id"] in used_id:
                continue
            used_abs.add(it["abs"])
            used_id.add(it["arxiv_id"])
            all_items.append(it)

        print(f"[INFO] page {page+1}/{MAX_ARXIV_PAGES} -> candidates (running): {len(all_items)}")

        if len(all_items) >= MIN_POOL_AFTER_FILTER:
            break

        # be gentle to arXiv
        time.sleep(0.4)

    # sort by EM score for general pool
    all_items.sort(key=lambda x: (x["em_score"], x["tech_score"]), reverse=True)
    return all_items


def pick_spotlight_and_general(items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Spotlight: highest tech_score (>0)
    General: top 5 by em_score excluding spotlight
    """
    spotlight: List[Dict] = []
    candidates_spot = [x for x in items if x["tech_score"] > 0]

    if candidates_spot:
        candidates_spot.sort(key=lambda x: (x["tech_score"], x["em_score"]), reverse=True)
        spotlight = [candidates_spot[0]]

    used = {x["abs"] for x in spotlight}
    general = [x for x in items if x["abs"] not in used][:5]
    return spotlight, general


# =========================
# GitHub Issue creation/update
# =========================
def create_or_update_issue(spotlight: List[Dict], general: List[Dict]) -> None:
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
        lines.append(f"  - arxiv_id: `{p['arxiv_id']}`")
        lines.append(f"  - matched: {matched}")
        lines.append(f"  - abs: {p['abs']}")
        lines.append(f"  - pdf: {p['pdf']}")
        lines.append(f"  - tech_score: {p['tech_score']:.1f} / em_score: {p['em_score']:.1f}")
        lines.append(f"  - published: {p['published']}")
    else:
        lines.append("- 該当なし（今回の候補内で“注目技術”キーワードにヒットしませんでした）")

    lines.append("")
    lines.append("## 📚 General EM（電子顕微鏡関連・最大5件）")
    if general:
        for p in general:
            lines.append(f"- **{p['title']}**")
            lines.append(f"  - arxiv_id: `{p['arxiv_id']}`")
            lines.append(f"  - abs: {p['abs']}")
            lines.append(f"  - pdf: {p['pdf']}")
            lines.append(f"  - em_score: {p['em_score']:.1f} / tech_score: {p['tech_score']:.1f}")
            lines.append(f"  - published: {p['published']}")
            lines.append("")
    else:
        lines.append("- 該当なし（seen除外後に候補が足りませんでした。MAX_ARXIV_PAGES を増やすと改善します。）")

    body = "\n".join(lines)

    session = requests.Session()
    session.headers.update({
        "Authorization": f"token {TOKEN_1}",
        "Accept": "application/vnd.github+json",
    })

    # Avoid duplicate issues on rerun: update if today's exists
    existing_number = find_today_issue_number(session, issue_title)
    if existing_number:
        r = session.patch(
            f"https://api.github.com/repos/{REPO}/issues/{existing_number}",
            json={"title": issue_title, "body": body},
            timeout=30,
        )
        print("[INFO] Issue update status:", r.status_code, "number:", existing_number)
        if r.status_code not in (200, 201):
            print("[INFO] Issue update response:", r.text[:400])
        return

    # Create new issue
    r = session.post(
        f"https://api.github.com/repos/{REPO}/issues",
        json={
            "title": issue_title,
            "body": body,
            "labels": [ISSUE_LABEL, "electron-microscopy", "tech-spotlight"],
        },
        timeout=30,
    )

    print("[INFO] Issue create status:", r.status_code)
    if r.status_code not in (201, 200):
        print("[INFO] Issue create response:", r.text[:400])


def main():
    print("[INFO] watch.py started")

    # 1) Build seen set from past issues (Plan A)
    seen_ids = get_seen_arxiv_ids_from_issues(max_pages=SEEN_ISSUE_PAGES)

    # 2) Fetch arXiv candidates, excluding seen
    items = fetch_candidates(seen_ids)
    print(f"[INFO] EM candidates (after seen filter): {len(items)}")

    # 3) Pick spotlight + general
    spotlight, general = pick_spotlight_and_general(items)
    print(f"[INFO] picked spotlight: {len(spotlight)}, general: {len(general)}")

    # 4) Create/update issue
    create_or_update_issue(spotlight, general)

    print("[INFO] watch.py finished normally")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print("[ERROR] Unhandled exception occurred")
        traceback.print_exc()
    sys.exit(0)
