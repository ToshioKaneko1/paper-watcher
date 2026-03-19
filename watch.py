#!/usr/bin/env python3
"""
watch.py (final)

Output:
  - Priority (max 1): EM-related paper where affiliation text indicates an EM-strong institution/facility
  - Others (max 5): EM-focused papers from the remaining set

Key changes:
  - Priority is NOT limited to a short manual institution list.
  - Priority is detected by "EM facility/institution keywords" in affiliation-like text
    (from arXiv metadata + PDF first page text when available).

Env vars (NO GITHUB_*):
  - TOKEN_1 : GitHub PAT for creating issues
  - REPO    : "username/reponame"
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

# PDF (affiliation detection support)
try:
    from PyPDF2 import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# =========================
# Env vars (NO "GITHUB_*")
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
    "max_results": 150,           # broaden candidate pool
    "sortBy": "submittedDate",
    "sortOrder": "descending",
}
ARXIV_URL = ARXIV_BASE_URL + urlencode(ARXIV_PARAMS)

# =========================
# EM判定（厳格/緩め）
# =========================
EM_STRICT_KEYWORDS = [
    "electron microscopy",
    "transmission electron",
    "scanning electron",
    "tem", "stem", "sem",
]

# Priority枠は「EM関連技術」まで拾うため、手法キーワードも許容
EM_LOOSE_KEYWORDS = EM_STRICT_KEYWORDS + [
    "eels", "edx", "ebsd", "haadf", "4d-stem", "dpc", "ptychography", "tomography"
]

NEGATIVE_KEYWORDS = [
    "nuclear reactor", "fission", "rocket", "propulsion",
    "astrophysics", "cosmic", "stellar"
]

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

def contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)

def contains_negative(text: str) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in NEGATIVE_KEYWORDS)

def is_em_strict(title: str, abstract: str) -> bool:
    t = (title + " " + abstract).lower()
    return contains_any(t, EM_STRICT_KEYWORDS)

def is_em_loose(title: str, abstract: str) -> bool:
    t = (title + " " + abstract).lower()
    return contains_any(t, EM_LOOSE_KEYWORDS)

def em_score(title: str, abstract: str) -> float:
    """Ranking score (method-rich EM papers bubble up)."""
    t = (title + " " + abstract).lower()
    score = 5.0
    for k, w in EM_METHOD_KEYWORDS.items():
        if k in t:
            score += w
    # small boost if explicitly EM in title
    tl = title.lower()
    if "electron microscopy" in tl or " tem" in (" " + tl) or " stem" in (" " + tl) or " sem" in (" " + tl):
        score += 1.0
    return score

# =========================
# Priority detection (NEW)
# =========================
# 1) “EMに強い拠点/施設/センター”を示す語（世界共通で効く）
EM_INSTITUTION_KEYWORDS = [
    "microscopy center",
    "microscopy centre",
    "microscopy facility",
    "electron microscopy center",
    "electron microscopy centre",
    "electron microscopy facility",
    "electron microscopy laboratory",
    "electron microscopy lab",
    "microanalysis center",
    "microanalysis facility",
    "nanocharacterization",
    "nanoscopy",
    "imaging center",
    "imaging facility",
    "cryo-em facility",
    "cryo electron microscopy facility",
    "national center for electron microscopy",
    "molecular foundry",
    "center for nanoscale materials",
]

EM_INST_RE = re.compile("|".join(re.escape(k) for k in EM_INSTITUTION_KEYWORDS), re.IGNORECASE)

def is_em_strong_institution(text: str) -> bool:
    """Priority if affiliation-like text contains EM facility keywords."""
    if not text:
        return False
    return EM_INST_RE.search(text) is not None

# 2) あなたが挙げた注目機関も“追加ブースト”として残す（少なくてもOK）
#    これだけに頼らないのが今回の肝
MANUAL_PRIORITY_PATTERNS = [
    # Japan universities / institutes / companies (examples)
    r"university of tokyo|東京大学",
    r"osaka university|大阪大学",
    r"kyoto university|京都大学",
    r"nagoya university|名古屋大学",
    r"kyushu university|九州大学",
    r"tohoku university|東北大学",
    r"hokkaido university|北海道大学",
    r"\bnims\b|物質・材料研究機構|national institute for materials science",
    r"\baist\b|産業技術総合研究所|national institute of advanced industrial science and technology",
    r"\bjeol\b|日本電子",
    r"\bhitachi\b|日立",
    r"\bjfcc\b|ファインセラミックスセンター|fine ceramics center",
    r"\bsamsung\b|サムスン",
    r"\btoshiba\b|東芝",
    r"\bkioxia\b|toshiba memory|キオクシア",
    r"\bmit\b|massachusetts institute of technology",
    r"columbia university",
    r"university of california|uc berkeley|ucla|uc san diego",
]
MANUAL_PRI_RE = re.compile("|".join(MANUAL_PRIORITY_PATTERNS), re.IGNORECASE)

def is_manual_priority(text: str) -> bool:
    if not text:
        return False
    return MANUAL_PRI_RE.search(text) is not None

def is_priority(text: str) -> bool:
    """Final priority rule: EM-strong institution keywords OR manual list match."""
    return is_em_strong_institution(text) or is_manual_priority(text)

# =========================
# arXiv helpers
# =========================
def arxiv_id(entry) -> str:
    return entry.id.split("/abs/")[-1].strip()

def pdf_url(entry) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id(entry)}.pdf"

def extract_first_page_text(pdf_bytes: bytes) -> str:
    if not PDF_AVAILABLE:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.pages:
            return (reader.pages[0].extract_text() or "").replace("\n", " ")
    except Exception:
        pass
    return ""

# =========================
# Fetch candidates
# =========================
def fetch_candidates() -> List[Dict]:
    feed = feedparser.parse(ARXIV_URL)
    items: List[Dict] = []

    for e in getattr(feed, "entries", []):
        title = e.title.replace("\n", " ").strip()
        abstract = e.summary.replace("\n", " ").strip()

        if contains_negative(title + " " + abstract):
            continue

        em_strict_flag = is_em_strict(title, abstract)
        em_loose_flag = is_em_loose(title, abstract)
        if not (em_strict_flag or em_loose_flag):
            continue

        items.append({
            "title": title,
            "abstract": abstract,
            "abs": e.link,
            "pdf": pdf_url(e),
            "published": getattr(e, "published", "")[:10],
            "score": em_score(title, abstract),
            "em_strict": em_strict_flag,
            "em_loose": em_loose_flag,
            "aff_text": (getattr(e, "arxiv_affiliation", "") or "").strip(),
            "priority": False,
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    return items

def enrich_affiliations_and_priority(items: List[Dict], max_pdf: int = 30) -> None:
    """
    Download PDFs only for top-N candidates to reduce traffic.
    Use first page text to detect priority institutions more robustly.
    """
    for it in items[:max_pdf]:
        aff = it["aff_text"]

        if PDF_AVAILABLE:
            try:
                r = requests.get(it["pdf"], timeout=25)
                if r.status_code == 200 and r.content:
                    aff += " " + extract_first_page_text(r.content)
            except Exception:
                pass

        it["aff_text"] = aff.strip()
        it["priority"] = is_priority(it["aff_text"])

    # Remaining items: priority by whatever aff_text exists
    for it in items[max_pdf:]:
        it["priority"] = is_priority(it["aff_text"])

def pick_1_plus_5(items: List[Dict]):
    """
    Priority slot:
      - must be EM-related (loose)
      - and priority==True (EM-strong institution/facility OR manual list)

    Others slot:
      - must be EM-focused (strict)
      - and priority==False (to keep diversity)
    """
    priority_pool = [x for x in items if x["priority"] and x["em_loose"]]
    others_pool = [x for x in items if (not x["priority"]) and x["em_strict"]]

    top_priority = priority_pool[:1]
    used = {x["abs"] for x in top_priority}
    top_others = [x for x in others_pool if x["abs"] not in used][:5]
    return top_priority, top_others

# =========================
# Create GitHub Issue (TOKEN_1 / REPO)
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
    lines.append("## ⭐ 注目（EM拠点/施設・電子顕微鏡関連・最大1件）")
    if top_priority:
        p = top_priority[0]
        lines.append(f"- **{p['title']}**")
        lines.append(f"  - abs: {p['abs']}")
        lines.append(f"  - pdf: {p['pdf']}")
        lines.append(f"  - score: {p['score']:.1f}")
        lines.append(f"  - published: {p['published']}")
    else:
        lines.append("- 該当なし（今回の候補内で「EM拠点/施設」判定にヒットしませんでした）")

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

    r = requests.post(
        f"https://api.github.com/repos/{REPO}/issues",
        headers={
            "Authorization": f"token {TOKEN_1}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": issue_title,
            "body": body,
            "labels": ["arxiv-watch", "electron-microscopy"],
        },
        timeout=30,
    )

    print("[INFO] Issue status:", r.status_code)
    if r.status_code not in (201, 200):
        print("[INFO] Issue response:", r.text)

# =========================
# Main (never exit 1)
# =========================
def main():
    print("[INFO] watch.py started")
    print("[INFO] arXiv URL:", ARXIV_URL)
    print("[INFO] PDF_AVAILABLE:", PDF_AVAILABLE)

    items = fetch_candidates()
    print(f"[INFO] candidates: {len(items)}")

    enrich_affiliations_and_priority(items, max_pdf=30)

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
