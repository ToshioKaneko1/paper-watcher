import os
import json
import time
import requests
import feedparser
import openai
from datetime import datetime
from openai.error import RateLimitError, OpenAIError

# === Secrets ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")   # OpenAI の APIキー
GITHUB_TOKEN   = os.getenv("TOKEN_1")          # GitHub PAT（Issues: Read/Write）
REPO           = os.getenv("REPO")             # "ユーザー名/リポジトリ名"

openai.api_key = OPENAI_API_KEY

# === arXiv 監視キーワード（電子顕微鏡系） ===
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-matl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]

# === OpenAI 要約（RateLimitでも落ちない / 日本語専門家向け） ===
def summarize(text, context="arXiv論文"):
    prompt = f"""
電子顕微鏡研究者向けに以下の{context}を専門的に日本語で400字以内に要約してください。
特に以下に注意してまとめてください：
・新規性（従来との差異を具体的に）
・分解能や電子線条件（数値あれば必ず）
・観察・測定の技術的ポイント（4D-STEM/EELS/ptychography/DPC等）
・装置構成（検出器/モノクロ/収差補正）
・応用範囲や意義

本文:
{text}
"""

    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return res["choices"][0]["message"]["content"]

    except RateLimitError:
        return f"[AI要約省略: クォータ超過]\n{text[:400]}"

    except OpenAIError as e:
        return f"[AI要約エラー]\n{text[:400]}"

    except Exception as e:
        return f"[予期せぬ要約エラー]\n{text[:400]}"


# === A. arXiv キーワードマッチ ===
def fetch_keyword_matches():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize(entry.summary, context="電子顕微鏡関連arXiv論文")
                results.append(f"■ **{entry.title}**\n{summary}\nURL: {entry.link}")
    return results


# === B. arXiv 全体の最新3件 ===
def fetch_latest_three():
    all_entries = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        all_entries.extend(feed.entries)

    def sort_key(e):
        return e.get("published_parsed") or time.gmtime(0)

    all_entries.sort(key=sort_key, reverse=True)
    latest_three = all_entries[:3]

    results = []
    for entry in latest_three:
        summary = summarize(entry.summary, context="arXiv新着論文（上位3件）")
        results.append(f"● **{entry.title}**\n{summary}\nURL: {entry.link}")
    return results


# === GitHub Issue 作成 ===
def create_issue(title, body):
    api_url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"title": title, "body": body}

    resp = requests.post(api_url, headers=headers, json=data)
    if resp.status_code >= 300:
        print("ERROR:", resp.status_code, resp.text)
        resp.raise_for_status()


# === Main ===
if __name__ == "__main__":
    kw_results = fetch_keyword_matches()
    latest_results = fetch_latest_three()

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"電子顕微鏡 arXiv ウォッチ {today}"

    body_parts = []

    body_parts.append("## 🔍 キーワードマッチ論文（電子顕微鏡関連）")
    body_parts.append("\n".join(kw_results) if kw_results else "該当なし")

    body_parts.append("\n\n---\n\n## 🆕 新着arXiv論文（最新3件）")
    body_parts.append("\n".join(latest_results))

    body = "\n".join(body_parts)
    create_issue(title, body)
