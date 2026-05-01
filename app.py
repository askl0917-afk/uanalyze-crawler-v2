
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
HUBA_URL = "https://pro.uanalyze.com.tw/lab/dashboard/41873"


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


def copy_button(text: str, label: str = "一鍵複製逐字稿"):
    safe_text = json.dumps(text or "", ensure_ascii=False)
    components.html(
        f"""
        <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; margin:10px 0;">
          <button id="copyBtn" style="font-size:17px;padding:12px 16px;border-radius:10px;border:1px solid #777;background:#222;color:white;width:100%;max-width:520px;">
            📋 {label}
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
            try {{ document.execCommand('copy'); status.innerText = '已複製'; }}
            catch (fallbackErr) {{ status.innerText = '複製失敗，請改用下方文字框長按複製'; }}
            document.body.removeChild(textarea);
          }}
        }};
        </script>
        """,
        height=78,
    )


def latest_run_dirs(limit: int = 5):
    dirs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[:limit]


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [x.strip() for x in text.split("\n")]
    skip_exact = {
        "深色主題", "帳戶和訂閱", "最新公告", "我的訂閱", "商城", "使用教學", "續約", "募集達人", "我知道了",
        "全台股", "全美股", "簡報", "影音", "自建圖表", "投資組合", "優分析產業新聞", "Kelvin價值投資工具包",
    }
    skip_contains = [
        "Cookie 技術", "若您繼續使用瀏覽器", "您的電腦中存取某些資訊", "優分析 UAnalyze 特別聲明", "投資必有風險",
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
    text = clean_text(text)
    if not text:
        return ""

    starts = []
    if title_hint:
        h = title_hint.strip().split("\n")[0]
        if h and h in text:
            starts.append(text.find(h))
    for key in ["逐字稿", "法說會", "簡報", "重點摘要", "Q&A", "問答", "主持人", "公司發言", "法人提問", "日期"]:
        idx = text.find(key)
        if idx >= 0:
            starts.append(idx)
    if starts:
        text = text[max(0, min(starts) - 120):]

    ends = []
    for key in ["相關文章", "推薦文章", "熱門文章", "更多文章", "返回列表", "優分析 UAnalyze 特別聲明"]:
        idx = text.find(key)
        if idx > 500:
            ends.append(idx)
    if ends:
        text = text[:min(ends)]
    return clean_text(text)


def build_markdown(stock_code: str, article: Dict, final_title: str, final_url: str) -> str:
    return "\n".join([
        f"# UAnalyze 逐字稿爬蟲結果｜{stock_code}",
        "",
        f"- 股票代號：{stock_code}",
        f"- 擷取時間：{human_now()}",
        f"- 最後頁面標題：{final_title}",
        f"- 最後頁面網址：{final_url}",
        f"- 擷取方式：{article.get('method','')}",
        "",
        "---",
        "",
        f"## {article.get('title') or '逐字稿'}",
        "",
        f"- 來源網址：{article.get('url','')}",
        f"- 頁面標題：{article.get('page_title','')}",
        f"- 文字長度：{article.get('clean_length',0)}",
        "",
        "### 逐字稿內容",
        "",
        article.get("text", "") or "無內容",
        "",
    ])


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
        probe = subprocess.run([sys.executable, "-c", "import playwright; print('playwright-ok')"], capture_output=True, text=True, timeout=30)
        logs.append("[probe playwright]\n" + (probe.stdout or "") + (probe.stderr or ""))
        if probe.returncode != 0:
            pip_result = subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], capture_output=True, text=True, timeout=300)
            logs.append("[pip install playwright]\n" + (pip_result.stdout or "") + (pip_result.stderr or ""))
            if pip_result.returncode != 0:
                return {"ok": False, "logs": "\n".join(logs), "system_chromium": system_chromium_path() or ""}
        install = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True, timeout=300)
        logs.append("[playwright install chromium]\n" + (install.stdout or "") + (install.stderr or ""))
        sys_chrome = system_chromium_path()
        if install.returncode == 0 or sys_chrome:
            return {"ok": True, "logs": "\n".join(logs), "system_chromium": sys_chrome or ""}
        return {"ok": False, "logs": "\n".join(logs), "system_chromium": ""}
    except Exception as e:
        return {"ok": False, "logs": "\n".join(logs) + f"\n{e}", "system_chromium": system_chromium_path() or ""}


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
    for selector in ["input[placeholder*='Email']", "input[placeholder*='email']", "input[type='email']", "input[type='text']", "input:not([type])"]:
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
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top}))
                .filter(x => (x.text==='登入' || x.text==='登 入') && !x.text.includes('Google') && !x.text.includes('Facebook') && !x.text.includes('Apple'))
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


def click_huba_quick_view(page) -> List[str]:
    actions = []
    try:
        page.goto(HUBA_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        actions.append("goto huba dashboard direct")
        return actions
    except Exception as e:
        actions.append(f"direct huba goto failed: {str(e)[:80]}")
    try:
        loc = page.get_by_text("虎八速覽", exact=False)
        if loc.count() > 0:
            loc.first.click(timeout=6000)
            actions.append("clicked text 虎八速覽")
            page.wait_for_timeout(9000)
            return actions
    except Exception:
        pass
    try:
        clicked = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span,li'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, len:(el.innerText||'').trim().length}))
                .filter(x => x.text.includes('虎八速覽'))
                .sort((a,b)=>a.len-b.len || a.left-b.left || a.top-b.top);
              if(!nodes.length) return false;
              nodes[0].el.click();
              return true;
            }
            """
        )
        if clicked:
            actions.append("JS clicked visible 虎八速覽")
            page.wait_for_timeout(9000)
            return actions
    except Exception:
        pass
    actions.append("failed to open huba")
    return actions



def click_sidebar_database_after_stock(page) -> List[str]:
    """切好股票後，照指定流程點左側收縮欄的「優分析產業資料庫」。"""
    actions = []
    before_url = page.url
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
    except Exception:
        pass
    try:
        has_left_item = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              return Array.from(document.querySelectorAll('a,button,div,span,li'))
                .some(el => visible(el) && (el.innerText||'').trim().includes('優分析產業資料庫') && el.getBoundingClientRect().left < 380);
            }
            """
        )
    except Exception:
        has_left_item = False
    if not has_left_item:
        try:
            page.mouse.click(30, 30)
            page.wait_for_timeout(1500)
            actions.append("opened left collapsed sidebar")
        except Exception as e:
            actions.append(f"open sidebar failed: {str(e)[:80]}")
    try:
        clicked = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const nodes = Array.from(document.querySelectorAll('a,button,div,span,li'))
                .filter(visible)
                .map(el => {
                  const r=el.getBoundingClientRect();
                  const text=(el.innerText||'').replace(/\s+/g,' ').trim();
                  return {el, text, top:r.top, left:r.left, len:text.length};
                })
                .filter(x => x.text.includes('優分析產業資料庫'))
                .filter(x => x.left < 380)
                .sort((a,b)=>a.left-b.left || a.top-b.top || a.len-b.len);
              if(!nodes.length) return false;
              nodes[0].el.click();
              return true;
            }
            """
        )
        if clicked:
            actions.append("clicked left-sidebar 優分析產業資料庫 after stock switch")
            page.wait_for_timeout(7000)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
        else:
            actions.append("left-sidebar 優分析產業資料庫 not found")
    except Exception as e:
        actions.append(f"click left-sidebar database failed: {str(e)[:100]}")
    try:
        cur_title = page.title()
        cur_url = page.url
        actions.append(f"after database click: {cur_title} / {cur_url}")
        if "/e-com/product-detail/" in cur_url or "商城" in cur_title:
            actions.append("detected e-com mall page; rollback to stock huba page before transcript click")
            page.goto(before_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(5000)
    except Exception as e:
        actions.append(f"database post-check failed: {str(e)[:100]}")
    return actions

def detect_current_stock_code(text: str) -> str:
    text = text or ""
    patterns = [
        r"股票代碼[：:]\s*\n\s*(\d{4,6})",
        r"股票代碼[：:]\s*(\d{4,6})",
        r"個股研究筆記[\s\S]{0,150}?股票代碼[：:]\s*\n\s*(\d{4,6})",
        r"\n(\d{4,6})\n[^\n]{0,20}\+[\d.]+%",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def switch_stock(page, stock_code: str) -> List[str]:
    actions = []
    code = normalize_stock_code(stock_code)
    if not code:
        actions.append("no stock code")
        return actions
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
    except Exception:
        pass

    def confirmed(tag: str) -> bool:
        cur = detect_current_stock_code(extract_body_text(page))
        if cur == code:
            actions.append(f"confirmed current stock {cur} after {tag}")
            return True
        return False

    if confirmed("initial check"):
        return actions

    selectors = [
        "input[placeholder*='股票代碼或名稱']",
        "input[placeholder*='搜尋代碼或名稱']",
        "input[placeholder*='搜尋代碼']",
        "input[placeholder*='股票代碼']",
        "input[placeholder*='代碼']",
        "input[placeholder*='搜尋']",
        "input[role='combobox']",
        "input[type='search']",
        "input[type='text']",
    ]
    used = False
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=5000)
                loc.click(timeout=5000)
                loc.fill(code, timeout=5000)
                actions.append(f"filled stock {code} by {selector}")
                page.wait_for_timeout(1800)
                try:
                    loc.press("Enter", timeout=5000)
                    actions.append("pressed Enter on stock input")
                except Exception:
                    page.keyboard.press("Enter")
                    actions.append("pressed global Enter")
                page.wait_for_timeout(10000)
                used = True
                if confirmed("Enter"):
                    return actions
                break
        except Exception as e:
            actions.append(f"selector failed {selector}: {str(e)[:60]}")

    try:
        clicked = page.evaluate(
            """
            (code) => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const nodes = Array.from(document.querySelectorAll('button,a,div,span,li'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, len:(el.innerText||'').trim().length}))
                .filter(x => x.text.includes(code))
                .sort((a,b)=>a.len-b.len || a.top-b.top || a.left-b.left);
              if(!nodes.length) return false;
              nodes[0].el.click();
              return true;
            }
            """,
            code,
        )
        if clicked:
            actions.append(f"clicked first result containing {code}")
            page.wait_for_timeout(10000)
            confirmed("clicked result")
    except Exception as e:
        actions.append(f"click result failed: {str(e)[:80]}")
    return actions


def find_transcript_links(page) -> List[Dict]:
    try:
        links = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const out=[];
              const nodes = Array.from(document.querySelectorAll('a,button,div,span,li'))
                .filter(visible)
                .map((el, idx) => {
                  const r=el.getBoundingClientRect();
                  const text=(el.innerText||'').replace(/\s+/g,' ').trim();
                  const a = el.closest('a');
                  return {idx, text, top:r.top, left:r.left, width:r.width, height:r.height, cx:r.left+r.width/2, cy:r.top+r.height/2, href:a ? a.href : ''};
                })
                .filter(x => x.text.includes('逐字稿'))
                .filter(x => x.text.length <= 160)
                .sort((a,b)=>a.top-b.top || a.left-b.left || a.text.length-b.text.length);
              const seen = new Set();
              for (const x of nodes){
                const key = x.text + '|' + x.href;
                if(seen.has(key)) continue;
                seen.add(key); out.push(x);
              }
              return out.slice(0,20);
            }
            """
        )
        return links if isinstance(links, list) else []
    except Exception:
        return []


def click_latest_transcript_from_huba(page, run_dir: Path) -> Dict:
    # 從個股頁上方的「逐字稿：日期」進去；前一步已按左側欄資料庫流程。
    actions = []
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
    except Exception:
        pass
    links = find_transcript_links(page)
    (run_dir / "transcript_link_candidates.json").write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    if not links:
        return {"ok": False, "actions": actions, "error": "沒有找到虎八速覽頁面的逐字稿連結", "links": links}

    # 優先點 header 區的「逐字稿：日期」；避開商品說明或一般文字。
    preferred = []
    for x in links:
        t = x.get("text", "")
        if "逐字稿" in t and ("：" in t or ":" in t or re.search(r"20\d{2}", t)) and x.get("top", 9999) < 180:
            preferred.append(x)
    if not preferred:
        for x in links:
            t = x.get("text", "")
            if "逐字稿" in t and x.get("top", 9999) < 260:
                preferred.append(x)
    target = (preferred or links)[0]
    actions.append(f"target transcript node: {target.get('text','')[:80]}")

    before_pages = len(page.context.pages)
    before_url = page.url
    try:
        # 若有 href，先直接 goto，避免 Safari/手機版點不到小文字。
        href = target.get("href") or ""
        if href and href.startswith("http"):
            page.goto(href, wait_until="domcontentloaded", timeout=90000)
            actions.append(f"goto transcript href: {href}")
        else:
            page.mouse.click(float(target["cx"]), float(target["cy"]))
            actions.append("clicked transcript node by coordinates")
        page.wait_for_timeout(7000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        # 有些連結會開新分頁。
        if len(page.context.pages) > before_pages:
            new_page = page.context.pages[-1]
            new_page.wait_for_timeout(5000)
            actions.append("switched to new popup page")
            return {"ok": True, "actions": actions, "page": new_page, "target": target, "before_url": before_url}
        return {"ok": True, "actions": actions, "page": page, "target": target, "before_url": before_url}
    except Exception as e:
        return {"ok": False, "actions": actions, "error": str(e), "target": target, "before_url": before_url}


def scrape_current_transcript(page, title_hint: str) -> Dict:
    body = extract_body_text(page)
    text = trim_transcript_text(body, title_hint)
    title = title_hint
    try:
        # 優先抓頁面上較像文章標題的第一段長文字
        detected = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>20 && r.height>10 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const nodes = Array.from(document.querySelectorAll('h1,h2,h3,.title,[class*=title],div,span'))
                .filter(visible)
                .map(el => ({text:(el.innerText||'').replace(/\s+/g,' ').trim(), top:el.getBoundingClientRect().top, len:(el.innerText||'').trim().length}))
                .filter(x => x.len >= 8 && x.len <= 120)
                .filter(x => x.text.includes('逐字稿') || x.text.includes('法說') || x.text.includes('Q'))
                .sort((a,b)=>a.top-b.top || b.len-a.len);
              return nodes.length ? nodes[0].text : '';
            }
            """
        )
        if detected:
            title = detected
    except Exception:
        pass
    return {"title": title or page.title() or "逐字稿", "text": text, "raw_length": len(body or ""), "clean_length": len(text or ""), "url": page.url, "page_title": page.title(), "method": "虎八速覽切股 → 左側欄優分析產業資料庫 → 個股頁逐字稿日期連結"}


def run_transcript_crawler(email: str, password: str, stock_code: str, login_url: str, wait_after_login: int, show_screenshots: bool = True):
    from playwright.sync_api import sync_playwright

    code = normalize_stock_code(stock_code)
    run_id = f"transcript_leftdb_{code}_{now_stamp()}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logs: List[str] = []
    debug: Dict = {}
    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()

    def log(msg: str):
        log_write(logs, log_box, run_dir, msg)

    install = ensure_playwright()
    (run_dir / "playwright_install_log.txt").write_text(install.get("logs", ""), encoding="utf-8")
    if not install.get("ok") and not install.get("system_chromium"):
        st.error("Playwright / Chromium 安裝失敗")
        st.code(install.get("logs", ""))
        return

    with sync_playwright() as p:
        browser = None
        try:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
            sys_chrome = install.get("system_chromium") or system_chromium_path()
            if sys_chrome:
                launch_kwargs["executable_path"] = sys_chrome
                log(f"使用系統 Chromium：{sys_chrome}")
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                is_mobile=False,
                has_touch=False,
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
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
            progress.progress(18)
            debug["login"] = {"actions": fill_actions + login_actions, "title": page.title(), "url": page.url}
            (run_dir / "01_after_login.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "01_after_login.png").write_bytes(page.screenshot(full_page=True))
            log(f"登入後：{page.title()} / {page.url}")

            status_box.write("開啟虎八速覽...")
            log("開啟虎八速覽，不進商城 e-com")
            huba_actions = click_huba_quick_view(page)
            close_blockers(page)
            progress.progress(35)
            debug["huba"] = {"actions": huba_actions, "title": page.title(), "url": page.url}
            (run_dir / "02_huba_page.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "02_huba_page.png").write_bytes(page.screenshot(full_page=True))
            log(f"虎八速覽：{page.title()} / {page.url}")

            status_box.write(f"切換股票代號：{code}...")
            log(f"切換股票代號：{code}")
            stock_actions = switch_stock(page, code)
            close_blockers(page)
            progress.progress(55)
            after_stock_text = extract_body_text(page)
            current = detect_current_stock_code(after_stock_text)
            debug["stock"] = {"actions": stock_actions, "current": current, "title": page.title(), "url": page.url}
            (run_dir / "03_after_stock.txt").write_text(after_stock_text, encoding="utf-8")
            if show_screenshots:
                (run_dir / "03_after_stock.png").write_bytes(page.screenshot(full_page=True))
            log(f"切換股票後：{page.title()} / {page.url} / current={current or 'unknown'}")
            if current and current != code:
                st.error(f"股票代號沒有成功切換：目前 {current}，目標 {code}。已停止，避免爬錯公司。")
                st.download_button("下載診斷 ZIP", build_zip_bytes(run_dir), file_name=f"{run_id}_switch_failed.zip", mime="application/zip")
                return

            status_box.write("開左側收縮欄，進優分析產業資料庫...")
            log("依指定流程：切股後，開左側收縮欄並點優分析產業資料庫")
            db_actions = click_sidebar_database_after_stock(page)
            close_blockers(page)
            debug["database_after_stock"] = {"actions": db_actions, "title": page.title(), "url": page.url}
            (run_dir / "04_after_database_click.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "04_after_database_click.png").write_bytes(page.screenshot(full_page=True))
            log(f"優分析產業資料庫步驟後：{page.title()} / {page.url}")

            status_box.write("點個股頁上方的逐字稿日期連結...")
            log("尋找個股頁上方的逐字稿日期連結")
            click_info = click_latest_transcript_from_huba(page, run_dir)
            debug["click_transcript"] = {k: v for k, v in click_info.items() if k != "page"}
            target_page = click_info.get("page") or page
            close_blockers(target_page)
            progress.progress(75)
            (run_dir / "05_after_transcript_click.txt").write_text(extract_body_text(target_page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "05_after_transcript_click.png").write_bytes(target_page.screenshot(full_page=True))
            if not click_info.get("ok"):
                log(f"失敗：{click_info.get('error','unknown')}")
                st.warning("沒有成功點到逐字稿連結。請下載診斷 ZIP 給我看。")
                st.download_button("下載診斷 ZIP", build_zip_bytes(run_dir), file_name=f"{run_id}_no_transcript_link.zip", mime="application/zip")
                return
            log(f"逐字稿頁：{target_page.title()} / {target_page.url}")

            title_hint = (click_info.get("target") or {}).get("text", "逐字稿")
            article = scrape_current_transcript(target_page, title_hint)
            debug["article"] = {k: v for k, v in article.items() if k != "text"}
            (run_dir / "06_transcript_raw.txt").write_text(extract_body_text(target_page), encoding="utf-8")
            final_md = build_markdown(code, article, target_page.title(), target_page.url)
            (run_dir / "_TRANSCRIPT.md").write_text(final_md, encoding="utf-8")
            (run_dir / "debug_info.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
            progress.progress(100)
            status_box.write("逐字稿爬取完成。")

            if article.get("clean_length", 0) < 300:
                st.warning("有抓到頁面，但文字偏短；請下載 ZIP 看 04/05 檔案判斷是不是目標頁。")
            else:
                st.success("完成：已抓到逐字稿文字。")
            copy_button(final_md, "一鍵複製逐字稿 Markdown")
            st.text_area("逐字稿 Markdown", final_md, height=520)
            st.download_button("下載本次完整 ZIP", build_zip_bytes(run_dir), file_name=f"{run_id}.zip", mime="application/zip")
            st.download_button("下載逐字稿 Markdown", final_md.encode("utf-8-sig"), file_name=f"{run_id}.md", mime="text/markdown")
        except Exception as e:
            log(f"程式例外：{repr(e)}")
            try:
                if page:
                    (run_dir / "exception_page.txt").write_text(extract_body_text(page), encoding="utf-8")
                    if show_screenshots:
                        (run_dir / "exception_screenshot.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            st.error("逐字稿爬蟲失敗。")
            st.code("\n".join(logs[-30:]))
            st.download_button("下載錯誤診斷 ZIP", build_zip_bytes(run_dir), file_name=f"{run_id}_error.zip", mime="application/zip")
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass


st.title("UAnalyze 逐字稿爬蟲｜左欄資料庫流程版")
st.caption("流程：登入 → 開虎八速覽 → 切股票 → 左側收縮欄點『優分析產業資料庫』→ 點個股頁上方『逐字稿：日期』→ 抓文字。若誤入商城頁會自動回退並留下診斷。")

with st.expander("登入與設定", expanded=True):
    login_url = st.text_input("UAnalyze 登入頁網址", value=DEFAULT_LOGIN_URL)
    email = st.text_input("UAnalyze Email")
    password = st.text_input("UAnalyze 密碼", type="password")
    stock_code = normalize_stock_code(st.text_input("股票代號（只填數字，例如 3037）", value="3037"))
    wait_after_login = st.slider("登入後等待秒數", 5, 90, 25)
    show_screenshots = st.checkbox("保留診斷截圖", value=True)

st.warning("本版重點：照指定流程加入左側收縮欄的『優分析產業資料庫』步驟；不下載 CSV，只抓逐字稿文字。")

if st.button("開始爬逐字稿", type="primary"):
    if not email or not password:
        st.error("請先輸入 UAnalyze Email 和密碼。")
    elif not stock_code:
        st.error("請輸入股票代號，只填數字。")
    else:
        run_transcript_crawler(email, password, stock_code, login_url, wait_after_login, show_screenshots)

st.subheader("最近一次結果")
runs = latest_run_dirs(1)
if runs:
    latest = runs[0]
    md_path = latest / "_TRANSCRIPT.md"
    if md_path.exists():
        md = md_path.read_text(encoding="utf-8")
        copy_button(md, "一鍵複製最近一次逐字稿")
        st.text_area("最近一次逐字稿", md, height=360)
        st.download_button("下載最近一次 ZIP", build_zip_bytes(latest), file_name=f"{latest.name}.zip", mime="application/zip")
else:
    st.caption("尚無逐字稿爬取結果。")
