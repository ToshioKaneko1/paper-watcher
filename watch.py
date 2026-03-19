#!/usr/bin/env python3
"""
watch.py (improved)
- Broad EM search: TEM / STEM / SEM
- Pick: 1 paper from priority institutions + 5 other EM papers
- Create GitHub Issue using TOKEN_1 / REPO (no GITHUB_* env vars)
- Safe arXiv URL building via urlencode (avoid InvalidURL)
"""

import datetime
import io
import os
import re
import sys
from urllib.parse import urlencode

import feedparser
import requests
from PyPDF2 import PdfReader  # or use pypdf

# =========================
# 0) Environment variables (NO "GITHUB_*")
# =========================
TOKEN_1 = os.environ.get("TOKEN_1")   # GitHub Issues 作成用 PAT
REPO = os.environ.get("REPO")         # "username/reponame"

# =========================
# 1) arXiv query (safe URL encoding)
# =========================
ARXIV_BASE_URL = "https://export.arxiv.org/api/query?"

# 電子顕微鏡を広く拾う（必須軸）
ARXIV_SEARCH_QUERY = "all:electron+microscopy OR all:TEM OR all:STEM OR all:SEM"

ARXIV_PARAMS = {
    "search_query": ARXIV_SEARCH_QUERY,
    "start": 0,
    "max_results": 80,  # ←候補を多めに取って、後で 1+5 に絞る
    "sortBy": "submittedDate",
    "sortOrder": "descending",
}
ARXIV_URL = ARXIV_BASE_URL + urlencode(ARXIV_PARAMS)

# =========================
# 2) Filtering / scoring keywords
# =========================
EM_CORE_KEYWORDS = [
    "electron microscopy",
    "tem", "stem", "sem",
    "transmission electron",
    "scanning electron",
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

NEGATIVE_KEYWORDS = [
    "nuclear reactor",
    "rocket",
    "propulsion",
    "fission",
    "astrophysics",
    "cosmic",
]

# =========================
# 3) Priority institution keywords
# =========================
# ※ここは「ゆるい文字一致」でOK。まず運用して、漏れたら追加していくのが安定です。
PRIORITY_AFFIL_PATTERNS = [
    # Japan universities
    r"\buniversity of tokyo\b", r"\butokyo\b", r"東京大学",
    r"\bosaka university\b", r"大阪大学",
    r"\bkyoto university\b", r"京都大学",
    r"\bnagoya university\b", r"名古屋大学",
    r"\bkyushu university\b", r"九州大学",
    r"\btohoku university\b", r"東北大学",
    r"\bhokkaido university\b", r"北海道大学",

    # Japan institutes / companies (examples)
    r"\bnims\b", r"物質・材料研究機構", r"nims\b",
    r"\baist\b", r"産業技術総合研究所",
    r"\bjeol\b", r"日本電子",
    r"\bhitachi\b", r"日立",
    r"\bthermo fisher\b", r"\btfs\b",  # 参考（THSは表記ゆれが多いので暫定）
    r"\bjfcc\b", r"ファインセラミックスセンター", r"fine ceramics center",

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


# =========================
# 4) Utility
# =========================
def contains_any(text: str, keywords):
    t = text.lower()
    return any(k.lower() in t for k in keywords)

def contains_negative(text: str):
    t = text.lower()
    return any(k.lower() in t for k in NEGATIVE_KEYWORDS)

def em_score(text: str) -> float:
    t = text.lower()
    score = 5.0
    for k, w in EM_METHOD_KEYWORDS.items():
        if k in t:
            score += w
    return score

def is_priority_affiliation(text: str) -> bool:
    if not text:
        return False
    return PRIORITY_RE.search(text) is not None

def arxiv_id_from_entry(entry) -> str:
    # entry.id: "http://arxiv.org/abs/xxxx.xxxxxv1"
    return entry.id.split("/abs/")[-1].strip()

def pdf_url_from_entry(entry) -> str:
    # arXivは /pdf/{id}.pdf で取得可能
    arxiv_id = arxiv_id_from_entry(entry)
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def extract_affiliation_from_pdf(pdf_bytes: bytes) -> str:
    """
    Get likely affiliation text from first page of PDF.
    (Heuristic: just return first page text; we'll match patterns against it.)
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) == 0:
            return ""
        text = reader.pages[0].extract_text() or ""
        return text.replace("\n", " ")
    except Exception:
        return ""


# =========================
# 5) Fetch papers and classify
# =========================
def fetch_candidates():
    feed = feedparser.parse(ARXIV_URL)
    items = []

    for entry in getattr(feed, "entries", []):
        title = entry.title.replace("\n", " ").strip()
        abstract = entry.summary.replace("\n", " ").strip()
        link_abs = entry.link
        text = f"{title} {abstract}"

        # 必須：電子顕微鏡関連
        if not contains_any(text, EM_CORE_KEYWORDS):
            continue

        # 除外（軽め）
        if contains_negative(text):
            continue

        score = em_score(text)

        # affiliation は arXiv metadata に「任意の自由記述」として入る場合があるが、常に揃わない
        # → PDF からも拾って判定する（頑健化）
        aff_text = ""
        # feedparserが arxiv_affiliation を拾う場合もある（ただし完全ではない）
        aff_text = getattr(entry, "arxiv_affiliation", "") or ""

        # PDF から補強（最大でも候補数分だけ。多すぎる場合は max_results を減らす）
        pdf_url = pdf_url_from_entry(entry)
        pdf_text = ""
        try:
            r = requests.get(pdf_url, timeout=20)
            if r.status_code == 200 and r.content:
                pdf_text = extract_affiliation_from_pdf(r.content)
        except Exception:
            pdf_text = ""

        combined_aff = f"{aff_text} {pdf_text}".strip()

        items.append({
            "title": title,
            "abs": link_abs,
            "pdf": pdf_url,
            "score": score,
            "aff_text": combined_aff,
            "is_priority": is_priority_affiliation(combined_aff),
            "published": getattr(entry, "published", "")[:10],
        })

    # score順
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def pick_1_plus_5(items):
    priority = [x for x in items if x["is_priority"]]
    others = [x for x in items if not x["is_priority"]]

    top_priority = priority[:1]  # 1件
    # もし注目1件を取ったなら、others から同じ論文が紛れないように除外（念のため）
    used_abs = set(x["abs"] for x in top_priority)
    others_filtered = [x for x in others if x["abs"] not in used_abs]

    top_others = others_filtered[:5]  # 5件

    return top_priority, top_others


# =========================
# 6) Create GitHub Issue (TOKEN_1 / REPO)
# =========================
def create_issue(top_priority, top_others):
    if not TOKEN_1:
        print("[WARN] TOKEN_1 not set -> skip issue creation")
        return
    if not REPO:
        print("[WARN] REPO not set -> skip issue creation")
        return

    today = datetime.date.today().isoformat()
    issue_title = f"Electron Microscopy Watch ({today})"

    lines = []
    lines.append("## ⭐ 注目機関（最大1件）")
    if top_priority:
        p = top_priority[0]
        lines.append(f"- **{p['title']}**")
        lines.append(f"  - abs: {p['abs']}")
        lines.append(f"  - pdf: {p['pdf']}")
        lines.append(f"  - score: {p['score']:.1f}")
        lines.append(f"  - published: {p['published']}")
    else:
        lines.append("- 該当なし（今回の候補から注目機関の所属検出ができませんでした）")

    lines.append("")
    lines.append("## 📚 その他（最大5件）")
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
    print(f"[INFO] candidates: {len(items)}")

    top_priority, top_others = pick_1_plus_5(items)
    print(f"[INFO] picked priority: {len(top_priority)}, others: {len(top_others)}")

    # Issueに出す
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
