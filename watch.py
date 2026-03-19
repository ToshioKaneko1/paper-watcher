#!/usr/bin/env python3
"""
watch.py (improved)

Goal:
- Broad EM search (TEM/STEM/SEM) from arXiv
- Output: 1 paper from PRIORITY institutions (must be EM-related)
          + 5 other EM-related papers
- Post to GitHub Issues using TOKEN_1 / REPO (no GITHUB_* env vars)
- arXiv URL safely built via urlencode

Notes:
- arXiv API metadata does not reliably include affiliation for all authors.
- We optionally parse the first page of PDF to detect affiliations (heuristic).
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

# PDF text extraction (for affiliation heuristics)
try:
    from PyPDF2 import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# =========================
# 0) Environment variables (NO "GITHUB_*")
# =========================
TOKEN_1 = os.environ.get("TOKEN_1")   # GitHub Issues 作成用 PAT
REPO = os.environ.get("REPO")         # "username/reponame"


# =========================
# 1) arXiv query (safe URL encoding)
# =========================
ARXIV_BASE_URL = "https://export.arxiv.org/api/query?"

# Broad EM query (retrieval stage) - keep broad, filter later in code
ARXIV_SEARCH_QUERY = "all:electron+microscopy OR all:TEM OR all:STEM OR all:SEM"

ARXIV_PARAMS = {
    "search_query": ARXIV_SEARCH_QUERY,
    "start": 0,
    "max_results": 100,          # fetch more candidates, then select 1+5
    "sortBy": "submittedDate",
    "sortOrder": "descending",
}
ARXIV_URL = ARXIV_BASE_URL + urlencode(ARXIV_PARAMS)


# =========================
# 2) EM topic detection
# =========================
# Base EM tokens
EM_CORE_KEYWORDS = [
    "electron microscopy",
    "transmission electron",
    "scanning electron",
    "tem", "stem", "sem",
]

# Optional method tokens (scoring only; not filtering)
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

# Mild negative filters (to reduce obvious drift)
NEGATIVE_KEYWORDS = [
    "nuclear reactor", "fission", "rocket", "propulsion",
    "astrophysics", "cosmic", "stellar"
]


def _contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def _contains_negative(text: str) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in NEGATIVE_KEYWORDS)


def em_score(title: str, abstract: str) -> float:
    """Score how strongly this looks like an EM method paper."""
    t = (title + " " + abstract).lower()
    score = 5.0  # base
    for k, w in EM_METHOD_KEYWORDS.items():
        if k in t:
            score += w
    # Slight boost if the title itself mentions EM explicitly
    title_l = title.lower()
    if "electron microscopy" in title_l or "tem" in title_l or "stem" in title_l or "sem" in title_l:
        score += 1.0
    return score


def is_em_paper_strict(title: str, abstract: str) -> bool:
    """
    Stricter EM-topic filter:
    - Must mention EM core tokens in TITLE OR in the beginning of abstract (first ~300 chars)
    This prevents 'TEM mentioned once in related work' papers from passing.
    """
    title_l = title.lower()
    abs_l = abstract.lower()
    abs_head = abs_l[:300]

    in_title = any(k in title_l for k in ["electron microscopy", "tem", "stem", "sem", "transmission electron", "scanning electron"])
    in_abs_head = any(k in abs_head for k in ["electron microscopy", "tem", "stem", "sem", "transmission electron", "scanning electron"])

    return in_title or in_abs_head


# =========================
# 3) Priority institution patterns
# =========================
PRIORITY_AFFIL_PATTERNS = [
    # Japan universities
    r"\buniversity of tokyo\b", r"\butokyo\b", r"東京大学",
    r"\bosaka university\b", r"大阪大学",
    r"\bkyoto university\b", r"京都大学",
    r"\bnagoya university\b", r"名古屋大学",
    r"\bkyushu university\b", r"九州大学",
    r"\btohoku university\b", r"東北大学",
    r"\bhokkaido university\b", r"北海道大学",

    # Japan institutes / orgs
    r"\bnims\b", r"物質・材料研究機構", r"national institute for materials science",
    r"\baist\b", r"産業技術総合研究所", r"national institute of advanced industrial science and technology",
    r"\bjfcc\b", r"ファインセラミックスセンター", r"fine ceramics center",

    # Companies / vendors (EM-related)
    r"\bjeol\b", r"日本電子",
    r"\bhitachi\b", r"日立",

    # Semiconductor companies (examples)
    r"\bsamsung\b", r"サムスン",
    r"\btoshiba\b", r"東芝",
    r"\bkioxia\b", r"キオクシア", r"toshiba memory",

    # US universities
    r"\bmit\b", r"massachusetts institute of technology",
    r"\bcolumbia university\b",
    r"\buniversity of california\b", r"\buc berkeley\b", r"\bucla\b", r"\buc san diego\b",
]

PRIORITY_RE = re.compile("|".join(PRIORITY_AFFIL_PATTERNS), re.IGNORECASE)


def is_priority_affiliation(text: str) -> bool:
    if not text:
        return False
    return PRIORITY_RE.search(text) is not None


# =========================
# 4) arXiv helpers
# =========================
def arxiv_id_from_entry(entry) -> str:
    # entry.id: "http://arxiv.org/abs/xxxx.xxxxxv1"
    return entry.id.split("/abs/")[-1].strip()


def pdf_url_from_entry(entry) -> str:
    arxiv_id = arxiv_id_from_entry(entry)
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def extract_first_page_text(pdf_bytes: bytes) -> str:
    if not PDF_AVAILABLE:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) == 0:
            return ""
        text = reader.pages[0].extract_text() or ""
        return text.replace("\n", " ")
    except Exception:
        return ""


# =========================
# 5) Fetch & classify candidates
# =========================
def fetch_candidates() -> List[Dict]:
    feed = feedparser.parse(ARXIV_URL)
    items: List[Dict] = []

    for entry in getattr(feed, "entries", []):
        title = entry.title.replace("\n", " ").strip()
        abstract = entry.summary.replace("\n", " ").strip()

        # mild negatives first
        if _contains_negative(title + " " + abstract):
            continue

        # STRICT EM filter: this is the key fix
        if not is_em_paper_strict(title, abstract):
            continue

        score = em_score(title, abstract)

        items.append({
            "title": title,
            "abstract": abstract,
            "abs": entry.link,
            "pdf": pdf_url_from_entry(entry),
            "published": getattr(entry, "published", "")[:10],
            "score": score,
            # affiliation text will be filled later (optional)
            "aff_text": getattr(entry, "arxiv_affiliation", "") or "",
            "is_priority": False,
        })

    # sort by score desc
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def enrich_affiliations_for_top(items: List[Dict], max_pdf: int = 25) -> None:
    """
    Download PDFs only for top-N candidates (to reduce traffic),
    and use first page text for priority affiliation detection.
    """
    if not PDF_AVAILABLE:
        # fallback to whatever arXiv metadata provides
        for it in items:
            it["is_priority"] = is_priority_affiliation(it.get("aff_text", ""))
        return

    for i, it in enumerate(items[:max_pdf]):
        pdf_text = ""
        try:
            r = requests.get(it["pdf"], timeout=25)
            if r.status_code == 200 and r.content:
                pdf_text = extract_first_page_text(r.content)
        except Exception:
            pdf_text = ""

        combined = (it.get("aff_text", "") + " " + pdf_text).strip()
        it["aff_text"] = combined
        it["is_priority"] = is_priority_affiliation(combined)

    # For the rest, rely on existing aff_text only
    for it in items[max_pdf:]:
        it["is_priority"] = is_priority_affiliation(it.get("aff_text", ""))


def pick_1_plus_5(items: List[Dict]):
    # IMPORTANT: items are already EM-only due to strict filter
    priority = [x for x in items if x["is_priority"]]
    others = [x for x in items if not x["is_priority"]]

    top_priority = priority[:1]
    used = set(x["abs"] for x in top_priority)
    top_others = [x for x in others if x["abs"] not in used][:5]

    return top_priority, top_others


# =========================
# 6) GitHub Issue creation (TOKEN_1 / REPO)
# =========================
def create_issue(top_priority: List[Dict], top_others: List[Dict]) -> None:
    if not TOKEN_1:
        print("[WARN] TOKEN_1 not set -> skip issue creation")
        return
    if not REPO:
        print("[WARN] REPO not set -> skip issue creation")
        return

    today = datetime.date.today().isoformat()
    issue_title = f"Electron Microscopy Watch ({today})"

    lines = []
    lines.append("## ⭐ 注目機関（電子顕微鏡関連・最大1件）")
    if top_priority:
        p = top_priority[0]
        lines.append(f"- **{p['title']}**")
        lines.append(f"  - abs: {p['abs']}")
        lines.append(f"  - pdf: {p['pdf']}")
        lines.append(f"  - score: {p['score']:.1f}")
        lines.append(f"  - published: {p['published']}")
    else:
        lines.append("- 該当なし（注目機関×電子顕微鏡の条件を満たす論文が見つかりませんでした）")

    lines.append("")
    lines.append("## 📚 その他（電子顕微鏡関連・最大5件）")
    if top_others:
        for p in top_others:
            lines.append(f"- **{p['title']}**")
            lines.append(f"  - abs: {p['abs']}")
            lines.append(f"  - pdf: {p['pdf']}")
            lines.append(f"  - score: {p['score']:.1f}")
            lines.append(f"  - published: {p['published']}")
            lines.append("")
    else:
        lines.append("- 該当なし")

    body = "\n".join(lines)

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
# 7) Main (never exit 1)
# =========================
def main():
    print("[INFO] watch.py started")
    print("[INFO] arXiv URL:", ARXIV_URL)

    items = fetch_candidates()
    print(f"[INFO] EM candidates (strict): {len(items)}")

    # affiliation enrichment for top N only
    enrich_affiliations_for_top(items, max_pdf=25)

    top_priority, top_others = pick_1_plus_5(items)
    print(f"[INFO] picked priority: {len(top_priority)}, others: {len(top_others)}")

    create_issue(top_priority, top_others)
    print("[INFO] watch.py finished normally")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print("[ERROR] Unhandled exception occurred")
        traceback.print_exc()
    sys.exit(0)
