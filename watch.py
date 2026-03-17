import os
import json
import requests
import feedparser
import openai
from datetime import datetime

# === Secrets ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("TOKEN_1")    # ← Secret 名 TOKEN_1
REPO = os.getenv("REPO")               # ← Secret 名 REPO

openai.api_key = OPENAI_API_KEY

# === Keywords for filtering ===
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-mtrl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]


# === AI Summary ===
def summarize(text):
    prompt = f"""
電子顕微鏡研究者向けに以下の論文を要約してください。
特に以下に注意して300字以内に：

・新規性（できるだけ数値）
・分解能（値を必ず）
・技術的ポイント（4D-STEM/EELS/ptychographyなど）
・応用分野

本文:
{text}
"""
    res = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return res["choices"][0]["message"]["content"]


# === A. Keywords match mode（今までの機能） ===
def fetch_keyword_matches():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize(entry.summary)
                results.append(
                    f"■ **{entry.title}**\n{summary}\nURL: {entry.link}"
                )
    return results


# === B. New Feature：arXiv最新3件ピックアップ ===
def fetch_latest_three():
    # “全エントリ”を集める
    all_entries = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        all_entries.extend(feed.entries)

    # pubDate の新しい順にソート
    all_entries.sort(
        key=lambda x: x.get("published_parsed", datetime.min),
        reverse=True
    )

    # 上位3件
    latest_three = all_entries[:3]

    results = []
    for entry in latest_three:
        summary = summarize(entry.summary)
        results.append(
            f"● **{entry.title}**\n{summary}\nURL: {entry.link}"
        )
    return results


# === GitHub Issue 作成 ===
def create_issue(title, body):
    url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"title": title, "body": body}
    resp = requests.post(url, headers=headers, json=data)
    if resp.status_code >= 300:
        print("ERROR:", resp.status_code, resp.text)
        resp.raise_for_status()


# === Main ===
if __name__ == "__main__":
    # A. キーワード一致の論文
    keyword_results = fetch_keyword_matches()

    # B. 最新3件
    latest_three_results = fetch_latest_three()

    # Issue タイトル
    today = datetime.now().strftime("%Y-%m-%d")
    title = f"電子顕微鏡論文ウォッチ {today}"

    # Issue 本文
    body = ""

    body += "## 🔍 キーワードマッチ論文（電子顕微鏡関連）\n"
    if keyword_results:
        body += "\n".join(keyword_results)
    else:
        body += "該当なし\n"

    body += "\n\n---\n\n"
    body += "## 🆕 最新のarXiv論文（新着3件）\n"
    body += "\n".join(latest_three_results)

    # Issueを作成
    create_issue(title, body)
