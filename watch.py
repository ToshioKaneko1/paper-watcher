import os
import json
import time
import requests
import feedparser
import openai
from datetime import datetime
from openai.error import RateLimitError, OpenAIError

# === Secrets ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN   = os.getenv("TOKEN_1")
REPO           = os.getenv("REPO")

openai.api_key = OPENAI_API_KEY

# === arXiv キーワードリスト（電子顕微鏡分野） ===
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

# === RSS feeds ===
ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-mat.mtrl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]

# === 日本語 要約関数（RateLimitでも落ちない版） ===
def summarize(text, context="電子顕微鏡関連論文"):
    prompt = f"""
電子顕微鏡研究者向けに以下の{context}をわかりやすく日本語で300字以内に要約してください。
特に以下に注目して整理してください：
・新規性（従来との差異）
・分解能、電子線条件、加速電圧（数値あれば必ず）
・検出器・観察技術（4D-STEM, EELS, DPC 等）
・応用範囲

本文:
{text}
"""
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return res["choices"][0]["message"]["content"]

    except Exception as e:
        # RateLimit / その他エラーは、元テキストの冒頭だけ返す
        return f"[要約不可（API制限）]\n{text[:300]}"


# === A. キーワード一致論文（電子顕微鏡関連）を要約する ===
def fetch_keyword_matches():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize(entry.summary)
                results.append(f"■ **{entry.title}**\n{summary}\nURL: {entry.link}")
    return results


# === B. 最新3件（リンクのみ・要約しない） ===
def fetch_latest_three():
    all_entries = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        all_entries.extend(feed.entries)

    def sort_key(e):
        return e.get("published_parsed") or time.gmtime(0)

    all_entries.sort(key=sort_key, reverse=True)

    latest_three = all_entries[:3]
    results = [
        f"● **{entry.title}**\nURL: {entry.link}"
        for entry in latest_three
    ]
    return results


# === GitHub Issue 作成 ===
def create_issue(title, body):
    api_url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"title": title, "body": body}

    r = requests.post(api_url, headers=headers, json=data)
    if r.status_code >= 300:
        print("ERROR:", r.status_code, r.text)
        r.raise_for_status()


# === MAIN ===
if __name__ == "__main__":
    kw_results     = fetch_keyword_matches()
    latest_results = fetch_latest_three()

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"電子顕微鏡 arXiv 日本語ウォッチ {today}"

    body = ""

    body += "## 🔍 キーワード一致論文（電子顕微鏡関連）\n"
    body += "\n".join(kw_results) if kw_results else "該当なし"

    body += "\n\n---\n\n## 🆕 新着arXiv論文（リンクのみ・最新3件）\n"
    body += "\n".join(latest_results)

    create_issue(title, body)
