import io
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="UAnalyze 逐字稿爬蟲", layout="wide")

RUNS_DIR = Path("runs")
RUNS_DIR.mkdir(exist_ok=True)

DEFAULT_LOGIN_URL = "https://pro.uanalyze.com.tw/login-page"
DEFAULT_HOME_URL = "https://pro.uanalyze.com.tw/"


# -----------------------------
# UI / file helpers
# -----------------------------
def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def human_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_name(text: str, max_len: int = 90) -> str:
    text = str(text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "_", text)
    return (text[:max_len] or "untitled").strip("._-") or "untitled"


def normalize_stock_code(stock_code: str) -> str:
    m = re.search(r"\d{4,6}", str(stock_code or ""))
    return m.group(0) if m else str(stock_code or "").strip()


def build_zip_bytes(run_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path in run_dir.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(run_dir))
    buffer.seek(0)
    return buffer.getvalue()


def copy_button(text: str, label: str = "一鍵複製全部逐字稿"):
    safe_text = json.dumps(text or "", ensure_ascii=False)
    components.html(
        f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
          <button id="copyBtn" style="font-size:16px;padding:10px 16px;border-radius:10px;border:1px solid #777;background:#222;color:white;">
            {label}
          </button>
          <span id="copyStatus" style="margin-left:12px;color:#4ade80;font-size:15px;"></span>
        </div>
        <script>
        const text = {safe_text};
        const btn = document.getElementById('copyBtn');
        const status = document.getElementById('copyStatus');
        btn.onclick = async () => {{
          try {{
            await navigator.clipboard.writeText(text);
            status.innerText = '已複製';
          }} catch (err) {{
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            try {{
              document.execCommand('copy');
              status.innerText = '已複製';
            }} catch (fallbackErr) {{
              status.innerText = '複製失敗，請改用下方文字框長按複製';
            }}
            document.body.removeChild(textarea);
          }}
        }};
        </script>
        """,
        height=70,
    )


def latest_run_dirs(limit: int = 5):
    dirs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[:limit]


# -----------------------------
# Text cleaning
# -----------------------------
def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [x.strip() for x in text.split("\n")]

    skip_exact = {
        "深色主題",
        "帳戶和訂閱",
        "最新公告",
        "我的訂閱",
        "商城",
        "使用教學",
        "續約",
        "募集達人",
        "我知道了",
        "全台股",
        "全美股",
        "簡報",
        "影音",
    }
    skip_contains = [
        "Cookie 技術",
        "若您繼續使用瀏覽器瀏覽的技術",
        "您的電腦中存取某些資訊",
        "下載 App",
        "使用條款",
        "隱私權",
    ]

    lines: List[str] = []
    for line in raw_lines:
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line in skip_exact:
            continue
        if any(key in line for key in skip_contains):
            continue
        lines.append(line)

    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_body_text(page) -> str:
    try:
        return clean_text(page.locator("body").inner_text(timeout=15000))
    except Exception:
        return ""


def trim_transcript_text(text: str, title_hint: str = "") -> str:
    """盡量把頁面雜訊切掉，只留下標題與逐字稿正文。"""
    text = clean_text(text)
    if not text:
        return ""

    # 若頁面含大量左側/頂部導覽，從第一個像文章標題的地方開始。
    candidates = []
    if title_hint:
        first = title_hint.split("\n")[0].strip()
        if first and first in text:
            candidates.append(text.find(first))
    for key in ["法說逐字稿", "逐字稿", "法說會", "Q&A", "問答", "簡報檔", "日期"]:
        idx = text.find(key)
        if idx >= 0:
            candidates.append(idx)
    if candidates:
        start = max(0, min(candidates) - 80)
        text = text[start:]

    # 常見頁尾截斷。
    end_keys = ["相關文章", "推薦文章", "熱門文章", "更多文章", "優分析產業資料庫"]
    end_positions = [text.find(k) for k in end_keys if text.find(k) > 300]
    if end_positions:
        text = text[: min(end_positions)]

    return clean_text(text)


def build_markdown(stock_code: str, articles: List[Dict], page_title: str, page_url: str) -> str:
    parts = [
        f"# UAnalyze 逐字稿爬蟲結果｜{stock_code}",
        "",
        f"- 股票代號：{stock_code}",
        f"- 擷取時間：{human_now()}",
        f"- 最後頁面標題：{page_title}",
        f"- 最後頁面網址：{page_url}",
        f"- 逐字稿篇數：{len(articles)}",
        "",
        "---",
        "",
    ]
    for i, item in enumerate(articles, start=1):
        parts.extend(
            [
                f"## {i}. {item.get('title') or '未命名逐字稿'}",
                "",
                f"- 狀態：{item.get('status', '')}",
                f"- 來源網址：{item.get('url', '')}",
                f"- 擷取方式：{item.get('method', '')}",
                "",
                "### 逐字稿內容",
                "",
                item.get("text", "") or "無內容",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(parts)


# -----------------------------
# Playwright setup
# -----------------------------
def system_chromium_path() -> Optional[str]:
    for name in ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
        path = shutil.which(name)
        if path:
            return path
    return None


@st.cache_resource(show_spinner=False)
def ensure_playwright() -> Dict:
    logs = []
    try:
        probe = subprocess.run(
            [sys.executable, "-c", "import playwright; print('playwright-ok')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logs.append("[probe playwright]\n" + (probe.stdout or "") + (probe.stderr or ""))
        if probe.returncode != 0:
            pip_result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            logs.append("[pip install playwright]\n" + (pip_result.stdout or "") + (pip_result.stderr or ""))
            if pip_result.returncode != 0:
                return {"ok": False, "logs": "\n".join(logs), "system_chromium": system_chromium_path() or ""}

        install = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        logs.append("[playwright install chromium]\n" + (install.stdout or "") + (install.stderr or ""))
        sys_chrome = system_chromium_path()
        if install.returncode == 0 or sys_chrome:
            return {"ok": True, "logs": "\n".join(logs), "system_chromium": sys_chrome or ""}
        return {"ok": False, "logs": "\n".join(logs), "system_chromium": ""}
    except Exception as e:
        return {"ok": False, "logs": "\n".join(logs) + f"\n{e}", "system_chromium": system_chromium_path() or ""}


# -----------------------------
# Browser actions
# -----------------------------
def log_write(logs: List[str], log_box, run_dir: Path, message: str):
    line = f"[{human_now()}] {message}"
    logs.append(line)
    if log_box is not None:
        log_box.text("\n".join(logs[-18:]))
    try:
        (run_dir / "run_log.txt").write_text("\n".join(logs), encoding="utf-8")
    except Exception:
        pass


def close_blockers(page) -> List[str]:
    actions = []
    for text in ["我知道了", "同意", "接受", "接受所有", "OK", "關閉", "知道了"]:
        try:
            loc = page.get_by_text(text, exact=False)
            if loc.count() > 0:
                loc.last.click(timeout=2500)
                page.wait_for_timeout(1000)
                actions.append(f"clicked {text}")
                break
        except Exception:
            pass
    try:
        body = page.locator("body").inner_text(timeout=3000)
        if "系統已有更新" in body or "請重新整理" in body:
            page.reload(wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(6000)
            actions.append("reload after system update")
    except Exception:
        pass
    return actions


def fill_like_human(page, email: str, password: str) -> List[str]:
    actions = []
    email_selectors = [
        "input[placeholder*='Email']",
        "input[placeholder*='email']",
        "input[type='email']",
        "input[type='text']",
        "input:not([type])",
    ]
    for selector in email_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.click(timeout=5000)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(email, delay=45)
                actions.append(f"typed email by {selector}")
                break
        except Exception:
            pass
    try:
        loc = page.locator("input[type='password']").first
        if loc.count() > 0:
            loc.click(timeout=5000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(password, delay=55)
            actions.append("typed password")
    except Exception:
        pass
    return actions


def click_login(page) -> List[str]:
    actions = []
    try:
        btn = page.locator("button").filter(has_text="登入")
        if btn.count() > 0:
            btn.last.click(timeout=5000)
            actions.append("clicked login button")
            return actions
    except Exception:
        pass
    try:
        clicked = page.evaluate(
            """
            () => {
              function visible(el){
                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
              }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top}))
                .filter(x => (x.text === '登入' || x.text === '登 入') && !x.text.includes('Google') && !x.text.includes('Facebook') && !x.text.includes('Apple'))
                .sort((a,b)=>a.top-b.top);
              if(!nodes.length) return false;
              nodes[nodes.length-1].el.click();
              return true;
            }
            """
        )
        if clicked:
            actions.append("JS clicked login")
            return actions
    except Exception:
        pass
    try:
        page.keyboard.press("Enter")
        actions.append("pressed Enter")
    except Exception:
        pass
    return actions


def click_visible_text(page, text: str, exact: bool = False, prefer_top: bool = False, timeout_ms: int = 6000) -> List[str]:
    actions = []
    try:
        loc = page.get_by_text(text, exact=exact)
        if loc.count() > 0:
            target = loc.first if prefer_top else loc.last
            target.click(timeout=timeout_ms)
            page.wait_for_timeout(2500)
            actions.append(f"clicked text {text}")
            return actions
    except Exception:
        pass
    try:
        clicked = page.evaluate(
            """
            ({text, exact, preferTop}) => {
              function visible(el){
                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
              }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span,li'))
                .filter(visible)
                .map(el => ({el, t:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, len:(el.innerText||'').trim().length}))
                .filter(x => exact ? x.t === text : x.t.includes(text))
                .sort((a,b) => preferTop ? (a.top-b.top || a.len-b.len) : (a.len-b.len || a.top-b.top));
              if(!nodes.length) return false;
              nodes[0].el.scrollIntoView({block:'center'});
              nodes[0].el.click();
              return true;
            }
            """,
            {"text": text, "exact": exact, "preferTop": prefer_top},
        )
        if clicked:
            page.wait_for_timeout(2500)
            actions.append(f"JS clicked text {text}")
    except Exception:
        pass
    return actions


def open_industry_database(page) -> List[str]:
    actions = []
    # 優先從目前登入後頁面點入；保留目前 Session，避免重新登入。
    for text in ["優分析產業資料庫", "產業資料庫", "產業輕鬆讀"]:
        acts = click_visible_text(page, text, exact=False, prefer_top=False, timeout_ms=5000)
        if acts:
            actions.extend(acts)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(5000)
            return actions
    actions.append("industry database text not clicked")
    return actions


def choose_stock_in_database(page, stock_code: str) -> List[str]:
    actions = []
    code = normalize_stock_code(stock_code)
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
    except Exception:
        pass

    selectors = [
        "input[placeholder*='股票代碼或名稱']",
        "input[placeholder*='股票代碼']",
        "input[placeholder*='代碼']",
        "input[placeholder*='你想找什麼']",
        "input[placeholder*='搜尋']",
        "input[type='search']",
        "input[role='combobox']",
        "input[type='text']",
    ]
    filled = False
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=4000)
                loc.click(timeout=4000)
                loc.fill(code, timeout=4000)
                actions.append(f"filled stock {code} by {selector}")
                filled = True
                page.wait_for_timeout(1500)
                try:
                    loc.press("Enter", timeout=4000)
                    actions.append("pressed Enter on stock search")
                except Exception:
                    page.keyboard.press("Enter")
                    actions.append("pressed global Enter")
                page.wait_for_timeout(4000)
                break
        except Exception as e:
            actions.append(f"selector failed {selector}: {str(e)[:60]}")
    if not filled:
        actions.append("stock input not found")

    # 如果跳出清單，點第一個包含股票代號的項目。
    try:
        clicked = page.evaluate(
            """
            (code) => {
              function visible(el){
                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
              }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span,li'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, len:(el.innerText||'').trim().length}))
                .filter(x => x.text.includes(code))
                .sort((a,b)=>a.len-b.len || a.top-b.top || a.left-b.left);
              if(!nodes.length) return false;
              nodes[0].el.scrollIntoView({block:'center'});
              nodes[0].el.click();
              return true;
            }
            """,
            code,
        )
        if clicked:
            actions.append(f"clicked search result containing {code}")
            page.wait_for_timeout(5000)
    except Exception as e:
        actions.append(f"click search result failed: {str(e)[:80]}")

    return actions


def click_transcript_tab(page) -> List[str]:
    actions = []
    # 先試著點上方分類列的「逐字稿」，盡量避免點到文章卡片裡的標籤。
    try:
        clicked = page.evaluate(
            """
            () => {
              function visible(el){
                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
              }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, width:el.getBoundingClientRect().width, len:(el.innerText||'').trim().length}))
                .filter(x => x.text === '逐字稿' || x.text.includes('逐字稿'))
                .filter(x => x.top < 260 || x.text === '逐字稿')
                .sort((a,b)=>a.len-b.len || a.top-b.top || a.left-b.left);
              if(!nodes.length) return false;
              nodes[0].el.scrollIntoView({block:'center'});
              nodes[0].el.click();
              return true;
            }
            """
        )
        if clicked:
            actions.append("JS clicked transcript tab")
            page.wait_for_timeout(4000)
            return actions
    except Exception:
        pass
    actions.extend(click_visible_text(page, "逐字稿", exact=False, prefer_top=True, timeout_ms=5000))
    return actions


def collect_transcript_candidates(page, stock_code: str) -> List[Dict]:
    code = normalize_stock_code(stock_code)
    try:
        candidates = page.evaluate(
            """
            (code) => {
              function visible(el){
                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                return r.width>20 && r.height>10 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
              }
              const bad = ['全台股','全美股','搜尋','日期','小助理','追蹤成長數據','使用教學','續約','募集達人'];
              const nodes = Array.from(document.querySelectorAll('a,button,div,article,section,li'))
                .filter(visible)
                .map((el, idx) => {
                  const r = el.getBoundingClientRect();
                  const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
                  return {idx, text, top:r.top, left:r.left, width:r.width, height:r.height, cx:r.left + Math.min(40, Math.max(20, r.width*0.2)), cy:r.top + Math.min(35, Math.max(15, r.height*0.25))};
                })
                .filter(x => x.text.length >= 12 && x.text.length <= 520)
                .filter(x => x.text.includes('逐字稿') || x.text.includes('法說'))
                .filter(x => code ? x.text.includes(code) : true)
                .filter(x => !bad.some(b => x.text === b || (x.text.includes(b) && x.text.length < 30)))
                .sort((a,b) => a.top-b.top || a.left-b.left || a.text.length-b.text.length);
              const seen = new Set();
              const out = [];
              for (const x of nodes) {
                const key = x.text.slice(0, 80);
                if (seen.has(key)) continue;
                seen.add(key);
                out.push(x);
                if (out.length >= 12) break;
              }
              return out;
            }
            """,
            code,
        )
        if isinstance(candidates, list):
            return candidates
    except Exception:
        return []
    return []


def click_candidate_by_index(page, stock_code: str, index: int) -> Dict:
    candidates = collect_transcript_candidates(page, stock_code)
    if index >= len(candidates):
        return {"ok": False, "error": "candidate index out of range", "candidates": candidates}
    c = candidates[index]
    try:
        page.mouse.click(c["cx"], c["cy"])
        page.wait_for_timeout(6000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        return {"ok": True, "candidate": c, "candidate_count": len(candidates)}
    except Exception as e:
        return {"ok": False, "error": str(e), "candidate": c, "candidate_count": len(candidates)}


def scrape_visible_article_body(page, candidate_title: str) -> Dict:
    body = extract_body_text(page)
    cleaned = trim_transcript_text(body, candidate_title)
    return {
        "title": candidate_title.split(" 逐字稿")[0].strip() if candidate_title else (page.title() or "逐字稿"),
        "text": cleaned,
        "raw_length": len(body or ""),
        "clean_length": len(cleaned or ""),
        "url": page.url,
        "page_title": page.title(),
    }


def go_back_to_list(page, list_url: str):
    try:
        if page.url != list_url:
            page.go_back(wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            return
    except Exception:
        pass
    try:
        page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
    except Exception:
        pass


# -----------------------------
# Main crawler
# -----------------------------
def run_transcript_crawler(
    login_url: str,
    email: str,
    password: str,
    stock_code: str,
    max_articles: int,
    wait_after_login: int,
    show_screenshots: bool,
):
    code = normalize_stock_code(stock_code)
    run_id = f"{now_stamp()}_{safe_name(code)}_transcripts"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()
    logs: List[str] = []

    def log(msg: str):
        log_write(logs, log_box, run_dir, msg)

    if not email or not password:
        st.error("請先輸入 UAnalyze Email 和密碼。")
        return
    if not code:
        st.error("請先輸入股票代號，只填數字，例如 3037。")
        return

    install = ensure_playwright()
    if not install.get("ok"):
        st.error("Playwright / Chromium 安裝檢查失敗。")
        st.code(install.get("logs", ""))
        return

    debug: Dict = {"run_id": run_id, "stock_code": code, "started_at": human_now(), "mode": "transcript_text_no_csv"}

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            launch_kwargs = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            }
            sys_chrome = install.get("system_chromium") or system_chromium_path()
            if sys_chrome:
                launch_kwargs["executable_path"] = sys_chrome
                log(f"使用系統 Chromium：{sys_chrome}")

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                viewport={"width": 430, "height": 940},
                is_mobile=True,
                has_touch=True,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(90000)

            status_box.write("登入 UAnalyze...")
            log("登入 UAnalyze")
            page.goto(login_url or DEFAULT_LOGIN_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(6000)
            close_blockers(page)
            fill_actions = fill_like_human(page, email, password)
            login_actions = click_login(page)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(wait_after_login * 1000)
            close_blockers(page)
            progress.progress(15)
            debug["login"] = {"actions": fill_actions + login_actions, "title": page.title(), "url": page.url}
            (run_dir / "01_after_login.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "01_after_login.png").write_bytes(page.screenshot(full_page=True))
            log(f"登入後：{page.title()} / {page.url}")

            status_box.write("進入優分析產業資料庫...")
            log("進入優分析產業資料庫")
            db_actions = open_industry_database(page)
            # 如果點不到，保底先回首頁再點一次。
            if not db_actions or all("not clicked" in a for a in db_actions):
                page.goto(DEFAULT_HOME_URL, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(6000)
                close_blockers(page)
                db_actions.extend(open_industry_database(page))
            progress.progress(28)
            debug["open_database"] = {"actions": db_actions, "title": page.title(), "url": page.url}
            (run_dir / "02_database_page.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "02_database_page.png").write_bytes(page.screenshot(full_page=True))
            log(f"產業資料庫頁：{page.title()} / {page.url}")

            status_box.write(f"切換股票代號：{code}...")
            log(f"切換股票代號：{code}")
            stock_actions = choose_stock_in_database(page, code)
            close_blockers(page)
            progress.progress(40)
            debug["stock"] = {"actions": stock_actions, "title": page.title(), "url": page.url}
            (run_dir / "03_after_stock.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "03_after_stock.png").write_bytes(page.screenshot(full_page=True))
            log(f"切換股票後：{page.title()} / {page.url}")

            status_box.write("切到逐字稿分頁...")
            log("切到逐字稿分頁")
            tab_actions = click_transcript_tab(page)
            close_blockers(page)
            page.wait_for_timeout(4000)
            progress.progress(52)
            debug["transcript_tab"] = {"actions": tab_actions, "title": page.title(), "url": page.url}
            (run_dir / "04_transcript_list.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "04_transcript_list.png").write_bytes(page.screenshot(full_page=True))
            log(f"逐字稿列表頁：{page.title()} / {page.url}")

            candidates = collect_transcript_candidates(page, code)
            debug["initial_candidates"] = candidates
            (run_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
            if not candidates:
                browser.close()
                st.warning("沒有找到逐字稿文章候選項目。請下載診斷 ZIP 給我看。")
                st.download_button(
                    "下載診斷 ZIP",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_id}_no_candidates.zip",
                    mime="application/zip",
                )
                return

            list_url = page.url
            articles: List[Dict] = []
            total = min(max_articles, len(candidates))
            log(f"找到候選逐字稿：{len(candidates)} 篇；本次預計抓 {total} 篇")

            for i in range(total):
                status_box.write(f"正在抓逐字稿 {i+1}/{total}...")
                log(f"打開逐字稿 {i+1}/{total}")
                click_result = click_candidate_by_index(page, code, i)
                candidate_text = (click_result.get("candidate") or {}).get("text", f"逐字稿 {i+1}")
                page.wait_for_timeout(4000)
                article = scrape_visible_article_body(page, candidate_text)

                # 若點擊後沒有進入文章，嘗試點目前頁面中更明確的「逐字稿」按鈕。
                if article["clean_length"] < 500 or page.url == list_url:
                    try:
                        alt_clicked = page.evaluate(
                            """
                            () => {
                              function visible(el){
                                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                                return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0';
                              }
                              const nodes = Array.from(document.querySelectorAll('button,a,span,div'))
                                .filter(visible)
                                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, len:(el.innerText||'').trim().length}))
                                .filter(x => x.text === '逐字稿')
                                .sort((a,b)=>b.top-a.top || a.left-b.left);
                              if(!nodes.length) return false;
                              nodes[0].el.click();
                              return true;
                            }
                            """
                        )
                        if alt_clicked:
                            page.wait_for_timeout(5000)
                            article = scrape_visible_article_body(page, candidate_text)
                            article["method"] = "candidate click + explicit transcript chip"
                    except Exception:
                        pass

                if not article.get("method"):
                    article["method"] = "candidate click"
                article["status"] = "成功" if article["clean_length"] >= 300 else "可能失敗：文字太短，請看 raw 檔"
                article["candidate"] = click_result
                articles.append(article)

                file_base = f"{i+1:02d}_{safe_name(article.get('title') or candidate_text)}"
                (run_dir / f"{file_base}.txt").write_text(article.get("text", ""), encoding="utf-8")
                (run_dir / f"{file_base}.json").write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
                try:
                    if show_screenshots:
                        (run_dir / f"{file_base}.png").write_bytes(page.screenshot(full_page=True))
                except Exception:
                    pass

                progress.progress(52 + int(((i + 1) / max(total, 1)) * 42))
                go_back_to_list(page, list_url)
                close_blockers(page)

            final_md = build_markdown(code, articles, page.title(), page.url)
            (run_dir / "_ALL_TRANSCRIPTS.md").write_text(final_md, encoding="utf-8")
            (run_dir / "debug_info.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()

            progress.progress(100)
            status_box.write("逐字稿爬取完成。")
            st.success(f"完成：共抓到 {len(articles)} 篇逐字稿。")
            copy_button(final_md, "一鍵複製全部逐字稿 Markdown")
            st.text_area("全部逐字稿 Markdown", final_md, height=520)
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "下載全部逐字稿 Markdown",
                    data=final_md.encode("utf-8-sig"),
                    file_name=f"{run_id}_transcripts.md",
                    mime="text/markdown",
                )
            with c2:
                st.download_button(
                    "下載完整 ZIP",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_id}.zip",
                    mime="application/zip",
                )

            with st.expander("逐篇狀態", expanded=False):
                for item in articles:
                    st.write(f"- {item.get('status')}｜{item.get('title')}｜{item.get('clean_length')} 字")

    except Exception as e:
        st.error("逐字稿爬蟲失敗。")
        st.exception(e)
        try:
            (run_dir / "error.txt").write_text(str(e), encoding="utf-8")
        except Exception:
            pass
        if run_dir.exists() and any(run_dir.iterdir()):
            st.download_button(
                "下載失敗診斷 ZIP",
                data=build_zip_bytes(run_dir),
                file_name=f"{run_id}_failed.zip",
                mime="application/zip",
            )


# -----------------------------
# Page UI
# -----------------------------
st.title("UAnalyze 產業情報小助理爬蟲｜逐字稿版")
st.caption("第二區塊改成爬逐字稿文字；不再下載 CSV、不點圖表三條線、不消耗匯出/複製額度。")

with st.expander("登入與爬蟲設定", expanded=True):
    login_url = st.text_input("UAnalyze 登入頁網址", value=DEFAULT_LOGIN_URL)
    email = st.text_input("UAnalyze Email")
    password = st.text_input("UAnalyze 密碼", type="password")
    stock_code = st.text_input("股票代號（只填數字，例如 3037）", value="3037")
    stock_code = normalize_stock_code(stock_code)

    c1, c2, c3 = st.columns(3)
    with c1:
        max_articles = st.slider("最多抓幾篇逐字稿", 1, 10, 3)
    with c2:
        wait_after_login = st.slider("登入後等待秒數", 5, 90, 25)
    with c3:
        show_screenshots = st.checkbox("ZIP 內保存截圖（較慢）", value=True)

st.divider()

st.subheader("第一區塊：原本穩定爬蟲")
st.info("這一版先不動第一區塊邏輯；目前重點是把第二區塊改成逐字稿文字爬取，避開 CSV 限制。")

st.divider()
st.subheader("第二區塊：逐字稿爬文")
st.write("流程：登入一次 → 進入產業資料庫 → 切股票 → 點逐字稿 → 逐篇抓文章文字。")

if st.button("開始爬逐字稿", type="primary"):
    run_transcript_crawler(
        login_url=login_url,
        email=email,
        password=password,
        stock_code=stock_code,
        max_articles=max_articles,
        wait_after_login=wait_after_login,
        show_screenshots=show_screenshots,
    )

st.divider()
st.subheader("最近一次結果")
recent = latest_run_dirs(1)
if recent:
    run_dir = recent[0]
    md_path = run_dir / "_ALL_TRANSCRIPTS.md"
    if md_path.exists():
        md = md_path.read_text(encoding="utf-8")
        st.caption(str(run_dir))
        copy_button(md, "一鍵複製最近一次逐字稿")
        st.text_area("最近一次逐字稿", md, height=380)
        st.download_button(
            "下載最近一次完整 ZIP",
            data=build_zip_bytes(run_dir),
            file_name=f"{run_dir.name}.zip",
            mime="application/zip",
        )
    else:
        st.caption(f"最近資料夾：{run_dir}，但尚未產生 _ALL_TRANSCRIPTS.md")
else:
    st.caption("尚無逐字稿爬取結果。")
