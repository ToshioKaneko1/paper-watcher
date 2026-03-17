import os
import time
import requests
import feedparser
from datetime import datetime

# === Secrets from GitHub Actions ===
HF_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")  # Hugging Face APIトークン (hf_...)
REPO         = os.getenv("REPO")                   # "username/repo"
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

# === Hugging Face Inference API: 英語要約 & 日本語翻訳 ===
HF_MODEL_SUMMARY = "facebook/bart-large-cnn"       # 英語要約
HF_MODEL_TRANSLATE = "Helsinki-NLP/opus-mt-en-ja"  # 英語→日本語翻訳

HF_URL_SUMMARY = f"https://api-inference.huggingface.co/models/{HF_MODEL_SUMMARY}"
HF_URL_TRANSLATE = f"https://api-inference.huggingface.co/models/{HF_MODEL_TRANSLATE}"

HF_HEADERS = {"Authorization": f"Bearer {HF_API_TOKEN}"}


def hf_call(api_url: str, text: str):
    """共通の HF API 呼び出し関数。"""
    if not HF_API_TOKEN:
        return None, "[HF] APIトークンが設定されていません。"

    payload = {"inputs": text}
    try:
        resp = requests.post(api_url, headers=HF_HEADERS, json=payload, timeout=60)
        if resp.status_code == 503:
            # モデルが起動中など → 少し待ってリトライも検討可（ここではメッセージだけ）
            return None, f"[HF] モデル起動中（503）。少し時間をおいて再実行してください。"
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.RequestException as e:
        return None, f"[HF] 通信エラー: {e}"
    except Exception as e:
        return None, f"[HF] 予期せぬエラー: {e}"


def summarize_english(text: str) -> str:
    """
    英語 abstract を BART で英語要約。
    """
    prompt = (
        "Summarize the following scientific abstract in concise English (3-4 sentences):\n\n" + text
    )
    data, err = hf_call(HF_URL_SUMMARY, prompt)
    if err:
        return f"[英語要約不可] {err}\n{text[:300]}"

    # 通常は [{"summary_text": "..."}] の形式
    try:
        if isinstance(data, list) and len(data) > 0:
            if "summary_text" in data[0]:
                return data[0]["summary_text"].strip()
            elif "generated_text" in data[0]:
                return data[0]["generated_text"].strip()
        return f"[英語要約解析エラー] {str(data)[:400]}"
    except Exception as e:
        return f"[英語要約解析例外] {e}\n{str(data)[:400]}"


def translate_to_japanese(english_text: str) -> str:
    """
    英語要約を日本語に翻訳。
    """
    data, err = hf_call(HF_URL_TRANSLATE, english_text)
    if err:
        return f"[日本語翻訳不可] {err}\n{english_text[:300]}"

    # 通常は [{"translation_text": "..."}] の形式
    try:
        if isinstance(data, list) and len(data) > 0 and "translation_text" in data[0]:
            return data[0]["translation_text"].strip()
        return f"[翻訳結果解析エラー] {str(data)[:400]}"
    except Exception as e:
        return f"[翻訳結果解析例外] {e}\n{str(data)[:400]}"


def summarize_en_to_ja(text: str) -> str:
    """
    英語 abstract → 英語要約 → 日本語翻訳 の2段方式。
    """
    eng_sum = summarize_english(text)
    # もし英語要約がすでにエラーメッセージなら、そのまま返す
    if eng_sum.startswith("[英語要約不可]") or eng_sum.startswith("[英語要約解析"):
        return eng_sum
    ja = translate_to_japanese(eng_sum)
    return ja


# === A. キーワード一致論文（電子顕微鏡関連） ===
def fetch_keyword_matches():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                ja_summary = summarize_en_to_ja(entry.summary)
                results.append(f"■ **{entry.title}**\n{ja_summary}\nURL: {entry.link}")
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
    kw_results     = fetch_keyword_matches()
    latest_results = fetch_latest_three()

    today = datetime.now().strftime("%Y-%m-%d")
    title = f"電子顕微鏡 arXiv 日本語ウォッチ (HF 2段要約) {today}"

    body_parts = []

    body_parts.append("## 🔍 キーワード一致論文（電子顕微鏡関連: HF二段要約）")
    body_parts.append("\n".join(kw_results) if kw_results else "該当なし")

    body_parts.append("\n\n---\n\n## 🆕 新着arXiv論文（リンクのみ・最新3件）")
    body_parts.append("\n".join(latest_results))

    body = "\n".join(body_parts)
    create_issue(title, body)
