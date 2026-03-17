import feedparser
import requests
import json
import os
import openai

# ---- API Key / Teams Webhook ----
openai.api_key = os.getenv("OPENAI_API_KEY")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

# ---- 監視キーワード ----
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-mat.mtrl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]

# ---- AI 要約 ----
def summarize(text):
    prompt = f"""
電子顕微鏡技術者向けに以下の論文を350字以内で要約してください。
・新規性
・分解能（数値があれば必ず）
・技術的ポイント
・応用
本文:
{text}
"""
    res = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return res["choices"][0]["message"]["content"]

# ---- arXiv処理 ----
def fetch_arxiv():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize(entry.summary)
                results.append(f"■ **{entry.title}**\n{summary}\n{entry.link}")
    return results

# ---- Teams 投稿 ----
def post_to_teams(messages):
    text = "\n\n".join(messages)
    payload = {"text": text}
    requests.post(
        TEAMS_WEBHOOK_URL,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"}
    )

# ---- メイン ----
if __name__ == "__main__":
    arxiv_results = fetch_arxiv()

    if arxiv_results:
        post_to_teams(arxiv_results)
    else:
        post_to_teams(["本日の新着論文はありませんでした。"])
