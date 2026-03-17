import os
import json
import requests
import feedparser
import openai
from datetime import datetime

# === Secrets ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")  # "username/paper-watcher"

openai.api_key = OPENAI_API_KEY

# === Watched keywords ===
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-mat.mtrl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]

# === AI Summary ===
def summarize(text):
    prompt = f"""
電子顕微鏡研究者向けに以下の論文を350字以内で要約してください。
・新規性（できるだけ数値）
・分解能（必ず）
・技術的ポイント（4D-STEM/ptycho/EELS/検出器など）
・応用

本文:
{text}
"""
    res = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return res["choices"][0]["message"]["content"]

# === Fetch arXiv ===
def fetch_arxiv():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize(entry.summary)
                results.append(f"■ **{entry.title}**\n{summary}\nURL: {entry.link}")
    return results

# === Create GitHub Issue ===
def create_issue(title, body):
    api_url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"title": title, "body": body}
    requests.post(api_url, headers=headers, json=data)

# === Main ===
if __name__ == "__main__":
    results = fetch_arxiv()

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"電子顕微鏡論文ウォッチ {today}"

    if results:
        body = "\n\n".join(results)
    else:
        body = "本日の該当論文はありませんでした。"

    create_issue(title, body)
