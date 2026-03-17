import os
import time
import requests
import feedparser
from datetime import datetime

# === Secrets from GitHub Actions ===
HF_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")  # ← Secrets で登録したトークン
REPO        = os.getenv("REPO")                    # "username/repo"
GITHUB_TOKEN = os.getenv("TOKEN_1")                # GitHub PAT（Issues作成用）

# === arXiv キーワード（電子顕微鏡関連） ===
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-mat.mtrl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]

# === Hugging Face Inference API 設定 ===
HF_MODEL = "google/mt5-large"
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
HF_HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"}


def summarize_with_hf(text: str) -> str:
    """
    英語の abstract を、google/mt5-large で日本語要約する。
    """
    if not HF_API_TOKEN:
        return "[要約不可: Hugging Face API トークンが設定されていません]\n" + text[:300]

    # mt5 用の「指示＋本文」プロンプト（簡易）
    prompt = (
        "以下の英語の学術的な要約文を、電子顕微鏡研究者向けに日本語で300字以内に要約してください。\n\n"
        + text
    )

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 256,
            "do_sample": False
        }
    }

    try:
        resp = requests.post(HF_API_URL, headers=HF_HEADERS, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # data は [{"generated_text": "..."}] の形式が多い
        if isinstance(data, list) and len(data) > 0 and "generated_text" in data[0]:
            return data[0]["generated_text"].strip()
        else:
            # モデルや設定によっては別形式もありえるので、その場合は生JSONを一部表示
            return "[要約結果の解析に失敗しました]\n" + str(data)[:400]

    except requests.exceptions.RequestException as e:
        return f"[要約不可: HF API 通信エラー] {e}\n" + text[:300]
    except Exception as e:
        return f"[要約不可: HF API 予期せぬエラー] {e}\n" + text[:300]


# === A. キーワード一致論文（電子顕微鏡関連） ===
def fetch_keyword_matches():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize_with_hf(entry.summary)
                results.append(f"■ **{entry.title}**\n{summary}\nURL: {entry.link}")
    return results


# === B. 最新3件（リンクのみ） ===
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
        results.append(f"● **{entry.title}**\nURL: {entry.link}")
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
    title = f"電子顕微鏡 arXiv 日本語ウォッチ (HF版) {today}"

    body_parts = []

    body_parts.append("## 🔍 キーワード一致論文（電子顕微鏡関連: HF要約）")
    body_parts.append("\n".join(kw_results) if kw_results else "該当なし")

    body_parts.append("\n\n---\n\n## 🆕 新着arXiv論文（リンクのみ・最新3件）")
    body_parts.append("\n".join(latest_results))

    body = "\n".join(body_parts)
    create_issue(title, body)
