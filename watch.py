import os
import json
import time
import requests
import feedparser
import openai
from datetime import datetime
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from io import BytesIO
from openai.error import RateLimitError, OpenAIError

# === Secrets ===
# GitHub Actions から渡される環境変数（Secrets）名に合わせています
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")   # OpenAI の API キー
GITHUB_TOKEN   = os.getenv("TOKEN_1")          # Fine-grained PAT（Issues: Read+Write）
REPO           = os.getenv("REPO")             # "ユーザー名/リポジトリ名" 形式

openai.api_key = OPENAI_API_KEY

# === arXiv 監視キーワード（電子顕微鏡系） ===
KEYWORDS = [
    "4D-STEM", "vibrational EELS", "monochromated EELS",
    "phase contrast TEM", "DPC", "ptychography", "NBD"
]

ARXIV_FEEDS = [
    "https://export.arxiv.org/rss/cond-mat.mtrl-sci",
    "https://export.arxiv.org/rss/physics.app-ph",
    "https://export.arxiv.org/rss/physics.ins-det"
]

# === メーカーサイト（URL は必要に応じて調整してください） ===
MANUFACTURER_SITES = [
    {"name": "JEOL",             "url": "https://www.jeol.co.jp/news/"},
    {"name": "Thermo Fisher",    "url": "https://www.thermofisher.com/blog/"},
    {"name": "Hitachi High-Tech","url": "https://www.hitachi-hightech.com/global/en/news/"}
]

# === 国内大学・研究機関サイト（必要に応じて調整） ===
UNIVERSITY_SITES = [
    {"name": "UTokyo",   "url": "https://www.u-tokyo.ac.jp/focus/ja/"},
    {"name": "KyotoU",   "url": "https://www.kyoto-u.ac.jp/ja/research-news"},
    {"name": "TohokuU",  "url": "https://www.tohoku.ac.jp/japanese/2024/10/news-research.html"},  # 例
    {"name": "OsakaU",   "url": "https://resou.osaka-u.ac.jp/ja"},
    {"name": "KyushuU",  "url": "https://www.kyushu-u.ac.jp/ja/researches/view/"}
    # NIMS, AIST なども追加可能
]


# === 共通：AI 要約（RateLimit エラーでも落ちない版） ===
def summarize(text, context="論文/ニュース"):
    prompt = f"""
電子顕微鏡研究者向けに、以下の{context}を300字以内で要約してください。
特に以下に注意してください：
・新規性（できるだけ数値）
・分解能（値があれば必ず記載）
・技術的ポイント（観察法・検出器・加速電圧など）
・応用分野

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
        # クォータ超過時：ワークフローを止めず、元テキストの先頭だけ返す
        print("WARN: OpenAI RateLimitError（クォータ超過）。元テキストの先頭のみを返します。")
        head = (text or "")[:400]
        return f"[AI要約省略: クォータ超過]\n{head}"
    except OpenAIError as e:
        # その他の OpenAI API エラー（認証、入力エラーなど）
        print("WARN: OpenAI API Error:", repr(e))
        head = (text or "")[:400]
        return f"[AI要約エラー]\n{head}"
    except Exception as e:
        # 予期しないエラー
        print("WARN: Unexpected Error in summarize:", repr(e))
        head = (text or "")[:400]
        return f"[要約処理で予期せぬエラー]\n{head}"


# === A. arXiv キーワードマッチ論文 ===
def fetch_keyword_matches():
    results = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if any(k.lower() in entry.title.lower() for k in KEYWORDS):
                summary = summarize(entry.summary, context="arXiv論文（キーワード一致）")
                results.append(
                    f"■ **{entry.title}**\n{summary}\nURL: {entry.link}"
                )
    return results


# === B. arXiv 最新3件（フィルタなし） ===
def fetch_latest_three():
    all_entries = []
    for url in ARXIV_FEEDS:
        feed = feedparser.parse(url)
        all_entries.extend(feed.entries)

    # published_parsed (time.struct_time) の新しい順でソート
    def sort_key(e):
        # 無い場合は最も古い時間として扱う
        return e.get("published_parsed") or time.gmtime(0)

    all_entries.sort(key=sort_key, reverse=True)
    latest_three = all_entries[:3]

    results = []
    for entry in latest_three:
        summary = summarize(entry.summary, context="arXiv新着論文（上位3件）")
        results.append(
            f"● **{entry.title}**\n{summary}\nURL: {entry.link}"
        )
    return results


# === C. メーカー技術ニュース + PDF URL 抽出（要約は各社1件だけ） ===
def fetch_manufacturer_news():
    news_results = []
    pdf_urls = []

    for site in MANUFACTURER_SITES:
        name = site["name"]
        url = site["url"]
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            news_results.append(f"【{name}】ニュース取得エラー: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=True)
        count = 0

        for a in links:
            href = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            # 相対パスを絶対URLに変換
            if href.startswith("/"):
                base = url.rstrip("/")
                href = base + href

            # PDF リンクを収集
            if href.lower().endswith(".pdf"):
                pdf_urls.append(href)

            # 各サイト 1件だけ AI要約、残りはタイトル＋URL のみ
            if count < 1:
                summary = summarize(title, context=f"{name} 技術ニュース（タイトルベース）")
                news_results.append(f"【{name}】{summary}\nURL: {href}")
                count += 1
            else:
                news_results.append(f"【{name}】{title}\nURL: {href}")

    return news_results, pdf_urls


# === D. 大学・研究機関ニュース + PDF URL 抽出（要約は各機関1件だけ） ===
def fetch_university_news():
    news_results = []
    pdf_urls = []

    for site in UNIVERSITY_SITES:
        name = site["name"]
        url = site["url"]
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            news_results.append(f"【{name}】ニュース取得エラー: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=True)
        count = 0

        for a in links:
            href = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            if href.startswith("/"):
                base = url.rstrip("/")
                href = base + href

            if href.lower().endswith(".pdf"):
                pdf_urls.append(href)

            # 各機関 1件だけ AI要約、残りはタイトル＋URL のみ
            if count < 1:
                summary = summarize(title, context=f"{name} 研究ニュース（タイトルベース）")
                news_results.append(f"【{name}】{summary}\nURL: {href}")
                count += 1
            else:
                news_results.append(f"【{name}】{title}\nURL: {href}")

    return news_results, pdf_urls


# === E. PDF 自動ダウンロード → AI 要約（最大1件） ===
def summarize_pdfs(pdf_urls, max_pdfs=1):
    summaries = []
    for i, url in enumerate(pdf_urls[:max_pdfs]):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            pdf_bytes = BytesIO(resp.content)
            reader = PdfReader(pdf_bytes)

            # 最初の数ページだけからテキスト抽出（重すぎ防止）
            text = ""
            for page in reader.pages[:3]:
                text += page.extract_text() or ""

            if not text.strip():
                summaries.append(f"PDF要約失敗（テキスト抽出不可）: {url}")
                continue

            summary = summarize(text[:6000], context="PDF技術資料")
            summaries.append(f"◆ PDF 要約\n{summary}\nURL: {url}")
        except Exception as e:
            summaries.append(f"PDF取得/要約エラー: {e}\nURL: {url}")
    return summaries


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
    # A. arXiv キーワードマッチ
    keyword_results = fetch_keyword_matches()

    # B. arXiv 最新3件
    latest_three_results = fetch_latest_three()

    # C. メーカー技術ニュース
    manufacturer_news, manufacturer_pdfs = fetch_manufacturer_news()

    # D. 大学・研究機関ニュース
    university_news, university_pdfs = fetch_university_news()

    # E. PDF要約（メーカー + 大学から拾った PDF の中から最大1件）
    pdf_summaries = summarize_pdfs(manufacturer_pdfs + university_pdfs, max_pdfs=1)

    # Issueタイトル
    today = datetime.now().strftime("%Y-%m-%d")
    title = f"電子顕微鏡論文ウォッチ {today}"

    # Issue本文構成
    body_parts = []

    body_parts.append("## 🔍 キーワードマッチ論文（電子顕微鏡関連）")
    if keyword_results:
        body_parts.append("\n".join(keyword_results))
    else:
        body_parts.append("該当なし")

    body_parts.append("\n\n---\n\n## 🆕 最新のarXiv論文（新着3件）")
    if latest_three_results:
        body_parts.append("\n".join(latest_three_results))
    else:
        body_parts.append("取得なし")

    body_parts.append("\n\n---\n\n## 🏭 メーカー技術ニュース（JEOL / Thermo / Hitachi）")
    if manufacturer_news:
        body_parts.append("\n".join(manufacturer_news))
    else:
        body_parts.append("ニュース取得なし")

    body_parts.append("\n\n---\n\n## 🏛 国内大学・研究機関ニュース（東大・京大・東北大・阪大・九大 ほか）")
    if university_news:
        body_parts.append("\n".join(university_news))
    else:
        body_parts.append("ニュース取得なし")

    body_parts.append("\n\n---\n\n## 📄 新着PDFの要約（メーカー + 大学）")
    if pdf_summaries:
        body_parts.append("\n".join(pdf_summaries))
    else:
        body_parts.append("新着PDFなし")

    body = "\n".join(body_parts)

    # Issue 作成
    create_issue(title, body)
