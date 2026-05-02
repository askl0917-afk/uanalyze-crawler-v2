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


def is_wrong_mall_page(page) -> bool:
    """商城商品頁不是資料庫功能頁；碰到就一定要判錯。"""
    try:
        url = page.url or ""
        title = page.title() or ""
        body = extract_body_text(page)
        if "/e-com/product-detail" in url:
            return True
        if "商城" in title and "常用分析" not in body:
            return True
        if "選擇方案" in body and "常用分析" not in body and "逐字稿：獨家" not in body:
            return True
    except Exception:
        pass
    return False


def looks_like_database_feature_page(page) -> bool:
    try:
        body = extract_body_text(page)
        must = ["常用分析", "逐字稿", "法人預估", "追蹤成長數據"]
        return sum(1 for x in must if x in body) >= 3 and not is_wrong_mall_page(page)
    except Exception:
        return False


def open_huba_quick_view(page) -> List[str]:
    actions = []
    try:
        page.goto(HUBA_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        actions.append("goto 虎八速覽 direct")
        return actions
    except Exception as e:
        actions.append(f"goto 虎八速覽 failed: {str(e)[:90]}")
    actions.extend(click_visible_text(page, "虎八速覽", exact=False, prefer_top=True, timeout_ms=6000))
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(6000)
    return actions


def detect_current_stock_code(text: str) -> str:
    text = text or ""
    patterns = [
        r"股票代碼[：:]\s*\n\s*(\d{4,6})",
        r"股票代碼[：:]\s*(\d{4,6})",
        r"個股研究筆記[\s\S]{0,180}?股票代碼[：:]\s*\n\s*(\d{4,6})",
        r"\n(\d{4,6})\n[^\n]{0,30}[+-]?[\d.]+%",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def switch_stock_on_huba(page, stock_code: str) -> List[str]:
    """在虎八速覽頁切股票；只輸入數字並按 Enter。"""
    actions = []
    code = normalize_stock_code(stock_code)
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
    except Exception:
        pass
    try:
        cur = detect_current_stock_code(extract_body_text(page))
        if cur == code:
            actions.append(f"current stock already {code}")
            return actions
    except Exception:
        pass

    selectors = [
        "input[placeholder*='股票代碼或名稱']",
        "input[placeholder*='股票代碼']",
        "input[placeholder*='代碼']",
        "input[placeholder*='搜尋']",
        "input[role='combobox']",
        "input[type='search']",
        "input[type='text']",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=5000)
                loc.click(timeout=5000)
                loc.fill(code, timeout=5000)
                actions.append(f"filled huba stock {code} by {selector}")
                page.wait_for_timeout(1300)
                try:
                    loc.press("Enter", timeout=5000)
                except Exception:
                    page.keyboard.press("Enter")
                actions.append("pressed Enter on huba stock input")
                page.wait_for_timeout(9000)
                break
        except Exception as e:
            actions.append(f"huba selector failed {selector}: {str(e)[:60]}")

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
            actions.append(f"clicked huba result containing {code}")
            page.wait_for_timeout(6000)
    except Exception as e:
        actions.append(f"click huba result failed: {str(e)[:80]}")
    return actions


def open_sidebar_if_needed(page) -> List[str]:
    actions = []
    try:
        body = extract_body_text(page)
        if "我的訂閱" in body and "Kelvin價值投資工具包" in body:
            actions.append("left sidebar already visible")
            return actions
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass
    # 優先點左上角漢堡，不用文字搜尋，避免點到別的選單。
    try:
        clicked = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>12 && r.height>12 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              const nodes = Array.from(document.querySelectorAll('button,[role="button"],.v-btn,svg,i,span,div'))
                .filter(visible)
                .map(el => ({el, text:(el.innerText||'').trim(), top:el.getBoundingClientRect().top, left:el.getBoundingClientRect().left, width:el.getBoundingClientRect().width, height:el.getBoundingClientRect().height}))
                .filter(x => x.top < 100 && x.left < 90)
                .sort((a,b)=>a.top-b.top || a.left-b.left);
              if(!nodes.length) return false;
              let el = nodes[0].el.closest('button,[role="button"],.v-btn') || nodes[0].el;
              el.click();
              return true;
            }
            """
        )
        if clicked:
            actions.append("clicked top-left hamburger")
            page.wait_for_timeout(2500)
            return actions
    except Exception as e:
        actions.append(f"hamburger js failed: {str(e)[:80]}")
    try:
        page.mouse.click(28, 30)
        actions.append("mouse clicked top-left fallback")
        page.wait_for_timeout(2500)
    except Exception as e:
        actions.append(f"mouse hamburger failed: {str(e)[:80]}")
    return actions


def click_left_subscription_database(page) -> List[str]:
    """只點左側收放欄『我的訂閱』下面、Kelvin 上面的優分析產業資料庫；禁止點商城商品卡。"""
    actions = []
    actions.extend(open_sidebar_if_needed(page))
    try:
        (Path("runs") / "_noop").mkdir(exist_ok=True)
    except Exception:
        pass
    try:
        result = page.evaluate(
            """
            () => {
              function visible(el){
                const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight;
              }
              function clean(t){ return (t||'').replace(/\s+/g,'').trim(); }
              const all = Array.from(document.querySelectorAll('a,button,div,span,li'))
                .filter(visible)
                .map((el, idx) => {
                  const r=el.getBoundingClientRect();
                  const a=el.closest('a');
                  const text=(el.innerText||'').trim();
                  return {el, idx, text, c:clean(text), top:r.top, left:r.left, width:r.width, height:r.height, href:a ? a.href : '', parent:(el.parentElement && el.parentElement.innerText || '').slice(0,200)};
                });
              const kelvins = all.filter(x => clean(x.text)==='Kelvin價值投資工具包' || x.text.includes('Kelvin價值投資工具包'));
              const ktop = kelvins.length ? Math.min(...kelvins.map(x=>x.top)) : 99999;
              const candidates = all
                .filter(x => x.c === '優分析產業資料庫')
                .filter(x => !x.href.includes('/e-com/'))
                .filter(x => !x.parent.includes('選擇方案') && !x.parent.includes('產品目錄') && !x.parent.includes('篩選'))
                .filter(x => x.left < 460)
                .map(x => ({...x, score: (x.top < ktop ? -1000 : 0) + Math.abs(x.left-35) + Math.max(0, x.top-ktop)}))
                .sort((a,b)=>a.score-b.score || a.top-b.top || a.left-b.left);
              if(!candidates.length){
                return {ok:false, reason:'no strict left-sidebar candidate', all: all.filter(x=>x.c.includes('優分析產業資料庫')).slice(0,10).map(x=>({text:x.text,top:x.top,left:x.left,width:x.width,href:x.href,parent:x.parent}))};
              }
              const target = candidates[0];
              target.el.scrollIntoView({block:'center'});
              target.el.click();
              return {ok:true, text:target.text, top:target.top, left:target.left, href:target.href, ktop};
            }
            """
        )
        actions.append("left database click result: " + json.dumps(result, ensure_ascii=False)[:500])
        page.wait_for_timeout(7000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        close_blockers(page)
    except Exception as e:
        actions.append(f"click left database failed: {str(e)[:120]}")
    return actions


def open_industry_database_from_huba(page, stock_code: str) -> List[str]:
    actions = []
    if not ("/lab/dashboard/" in (page.url or "")):
        actions.extend(open_huba_quick_view(page))
    close_blockers(page)
    actions.extend(switch_stock_on_huba(page, stock_code))
    close_blockers(page)
    # 點左側訂閱入口，最多重試兩次；只要進商城就退回虎八速覽重來。
    for attempt in range(2):
        actions.append(f"open left database attempt {attempt+1}")
        actions.extend(click_left_subscription_database(page))
        page.wait_for_timeout(5000)
        if is_wrong_mall_page(page):
            actions.append("WRONG: landed on e-com mall, return to huba and retry")
            try:
                page.goto(HUBA_URL + f"?stock={normalize_stock_code(stock_code)}", wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(6000)
            except Exception:
                pass
            continue
        if looks_like_database_feature_page(page):
            actions.append("confirmed database feature page")
            return actions
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
    """
    先用上方 bar 右側白色三條線選單找「逐字稿」。
    這是目前最穩的路徑：不要去商城，也不要點正文裡的逐字稿文字。
    """
    actions: List[str] = []

    def page_state_sig() -> Dict:
        try:
            body = extract_body_text(page)
            return {"url": page.url, "title": page.title(), "head": (body or "")[:1800]}
        except Exception:
            return {"url": page.url, "title": "", "head": ""}

    def click_transcript_chip_from_open_menu(tag: str) -> Dict:
        try:
            clicked = page.evaluate(
                """
                () => {
                  function visible(el){
                    const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                    return r.width>8 && r.height>8 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight;
                  }
                  function norm(t){ return (t||'').replace(/\s+/g,'').trim(); }
                  const nodes = Array.from(document.querySelectorAll('a,button,[role="button"],.v-chip,.v-btn,span,div,li'))
                    .filter(visible)
                    .map(el => {
                      const r=el.getBoundingClientRect(); const a=el.closest('a');
                      const text=(el.innerText||'').replace(/\s+/g,' ').trim();
                      const parent=(el.parentElement && el.parentElement.innerText || '').replace(/\s+/g,' ').trim().slice(0,600);
                      return {el, text, n:norm(text), parent, top:r.top, left:r.left, width:r.width, height:r.height, href:a?a.href:''};
                    })
                    .filter(x => x.n === '逐字稿' || x.n === '⭐逐字稿')
                    .filter(x => !x.href.includes('/e-com/'))
                    .filter(x => !x.parent.includes('產品目錄') && !x.parent.includes('產品說明'))
                    .sort((a,b) => {
                      const as = (a.parent.includes('常用分析') ? -1000 : 0) + a.top/10 + a.left/1000 + a.width/10;
                      const bs = (b.parent.includes('常用分析') ? -1000 : 0) + b.top/10 + b.left/1000 + b.width/10;
                      return as-bs;
                    });
                  if(!nodes.length) return {ok:false, reason:'no exact transcript chip in menu'};
                  const t = nodes[0];
                  const clickEl = t.el.closest('a,button,[role="button"],.v-chip,.v-btn') || t.el;
                  clickEl.scrollIntoView({block:'center', inline:'center'});
                  clickEl.click();
                  const ds = t.el.dataset ? JSON.parse(JSON.stringify(t.el.dataset)) : {};
                  const onclick = (t.el.getAttribute('onclick')||'').slice(0,400);
                  const parentHref = (t.el.parentElement && t.el.parentElement.closest && t.el.parentElement.closest('a')) ? t.el.parentElement.closest('a').href : '';
                  return {ok:true, text:t.text, top:t.top, left:t.left, width:t.width, height:t.height, href:t.href, parent:t.parent.slice(0,180), dataset:ds, onclick, parentHref};
                }
                """
            )
            actions.append(f"click transcript chip from menu {tag}: " + json.dumps(clicked, ensure_ascii=False)[:600])
            if isinstance(clicked, dict) and clicked.get("ok"):
                before = page_state_sig()
                page.wait_for_timeout(6000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                after = page_state_sig()
                url_changed = (after.get("url") or "") != (before.get("url") or "")
                body_changed = (after.get("head") or "") != (before.get("head") or "")
                return {"ok": True, "clicked": clicked, "url_changed": url_changed, "body_changed": body_changed, "before": before, "after": after}
        except Exception as e:
            actions.append(f"click transcript chip from menu failed {tag}: {str(e)[:120]}")
        return {"ok": False}

    def open_transcript_from_menu_href(tag: str) -> bool:
        try:
            target = page.evaluate(
                """
                () => {
                  function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>8 && r.height>8 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
                  function norm(t){ return (t||'').replace(/\\s+/g,'').trim(); }
                  const nodes = Array.from(document.querySelectorAll('a,button,[role=\"button\"],.v-chip,.v-btn,span,div,li'))
                    .filter(visible)
                    .map(el => {
                      const text=(el.innerText||'').replace(/\\s+/g,' ').trim();
                      const n=norm(text);
                      const a=el.closest('a');
                      const href=a?a.href:'';
                      const onclick=(el.getAttribute('onclick')||'') + ' ' + ((el.parentElement && el.parentElement.getAttribute && el.parentElement.getAttribute('onclick')) || '');
                      const html=((el.outerHTML||'') + ' ' + ((el.parentElement && el.parentElement.outerHTML) || '')).slice(0,1500);
                      return {text, n, href, onclick, html};
                    })
                    .filter(x => x.n === '逐字稿' || x.n === '⭐逐字稿');
                  const direct = nodes.find(x => /\\/lab\\/dashboard\\/[^\\s\"']+\\/\\d{3,}/.test((x.href||'') + ' ' + x.onclick + ' ' + x.html));
                  const blob = direct ? ((direct.href||'') + ' ' + direct.onclick + ' ' + direct.html) : nodes.map(x => (x.href||'') + ' ' + x.onclick + ' ' + x.html).join(' ');
                  const m = blob.match(/\\/lab\\/dashboard\\/[^\\s\"']+\\/\\d{3,}/);
                  if (m) return {ok:true, path:m[0]};
                  const hrefNode = nodes.find(x => x.href && x.href.includes('/lab/dashboard/') && !x.href.includes('/e-com/'));
                  if (hrefNode) return {ok:true, path:hrefNode.href};
                  return {ok:false};
                }
                """
            )
            actions.append(f"resolve transcript href from menu {tag}: " + json.dumps(target, ensure_ascii=False)[:600])
            if isinstance(target, dict) and target.get("ok") and target.get("path"):
                path = str(target.get("path"))
                if path.startswith("/"):
                    path = "https://pro.uanalyze.com.tw" + path
                before = page_state_sig()
                page.goto(path, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(5000)
                after = page_state_sig()
                actions.append(f"goto transcript href {tag}: {before.get('url')} -> {after.get('url')}")
                return after.get("url") != before.get("url")
        except Exception as e:
            actions.append(f"open transcript from href failed {tag}: {str(e)[:120]}")
        return False

    def open_top_bar_menu(tag: str) -> bool:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
        try:
            opened = page.evaluate(
                """
                () => {
                  function visible(el){
                    const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                    return r.width>10 && r.height>10 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight;
                  }
                  function txt(el){ return (el.innerText||el.getAttribute('aria-label')||el.getAttribute('title')||'').replace(/\s+/g,' ').trim(); }
                  function htmlHint(el){ return ((el.className||'') + ' ' + (el.outerHTML||'').slice(0,500)).toString(); }
                  const vw = window.innerWidth || 1440;
                  const nodes = Array.from(document.querySelectorAll('button,[role="button"],.v-btn,i,svg,span,div'))
                    .filter(visible)
                    .map(el => { const r=el.getBoundingClientRect(); const h=htmlHint(el); return {el, text:txt(el), hint:h, top:r.top, left:r.left, width:r.width, height:r.height, cx:r.left+r.width/2, cy:r.top+r.height/2}; })
                    .filter(x => x.top >= 0 && x.top < 95)
                    .filter(x => x.left > Math.min(260, vw*0.18) && x.left < vw - 120)
                    .filter(x => x.width <= 80 && x.height <= 70)
                    .filter(x => /mdi-menu|menu|bars|hamburger|fa-bars|三條|選單/i.test(x.hint + ' ' + x.text) || (x.text === '' && x.width >= 18 && x.height >= 18))
                    .sort((a,b) => {
                      const ah = /mdi-menu|menu|bars|hamburger|fa-bars/i.test(a.hint) ? -1000 : 0;
                      const bh = /mdi-menu|menu|bars|hamburger|fa-bars/i.test(b.hint) ? -1000 : 0;
                      const ar = Math.abs(a.left - vw*0.74);
                      const br = Math.abs(b.left - vw*0.74);
                      return (ah-bh) || (ar-br) || (a.width-b.width);
                    });
                  if(nodes.length){
                    const t = nodes[0];
                    const clickEl = t.el.closest('button,[role="button"],.v-btn') || t.el;
                    clickEl.click();
                    return {ok:true, method:'dom-menu-icon', text:t.text, top:t.top, left:t.left, width:t.width, height:t.height, hint:t.hint.slice(0,120)};
                  }
                  return {ok:false, reason:'no menu icon candidate'};
                }
                """
            )
            actions.append(f"open top bar menu {tag}: " + json.dumps(opened, ensure_ascii=False)[:600])
            if isinstance(opened, dict) and opened.get("ok"):
                page.wait_for_timeout(1800)
                return True
        except Exception as e:
            actions.append(f"open top bar menu failed {tag}: {str(e)[:120]}")

        # 座標備援：桌面版白色三條線大約在上方 bar 右側，約視窗寬 76% 位置。
        try:
            size = page.viewport_size or {"width": 1440, "height": 1000}
            x = int(size.get("width", 1440) * 0.765)
            y = 44
            page.mouse.click(x, y)
            page.wait_for_timeout(1800)
            actions.append(f"open top bar menu {tag}: coordinate fallback x={x}, y={y}")
            body = extract_body_text(page)
            return "常用分析" in body and "逐字稿" in body
        except Exception as e:
            actions.append(f"coordinate fallback failed {tag}: {str(e)[:120]}")
            return False

    # A. 先試使用者指出的右側白色三條線選單。
    for attempt in range(3):
        if open_top_bar_menu(f"attempt-{attempt+1}"):
            click_ret = click_transcript_chip_from_open_menu(f"attempt-{attempt+1}")
            actions.append(f"verify transcript click state attempt-{attempt+1}: " + json.dumps(click_ret, ensure_ascii=False)[:600])
            if isinstance(click_ret, dict) and click_ret.get("ok") and (click_ret.get("url_changed") or click_ret.get("body_changed")):
                return actions
            if open_transcript_from_menu_href(f"attempt-{attempt+1}"):
                return actions
        page.wait_for_timeout(1000)

    # B. 備援：如果「逐字稿」本來就在上方 bar 可見，直接點。
    def click_visible_top_tab(tag: str) -> bool:
        try:
            clicked = page.evaluate(
                """
                () => {
                  function visible(el){
                    const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
                    return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight;
                  }
                  function norm(t){ return (t||'').replace(/\s+/g,'').trim(); }
                  const nodes = Array.from(document.querySelectorAll('a,button,[role="button"],.v-tab,.v-btn,div,span,li'))
                    .filter(visible)
                    .map(el => { const r=el.getBoundingClientRect(); const a=el.closest('a'); const text=(el.innerText||'').replace(/\s+/g,' ').trim(); return {el, text, n:norm(text), top:r.top, left:r.left, width:r.width, height:r.height, href:a?a.href:''}; })
                    .filter(x => x.top >= 0 && x.top < 125)
                    .filter(x => x.n === '⭐逐字稿' || x.n === '逐字稿' || x.n.endsWith('逐字稿'))
                    .filter(x => !/[：:]20\d{2}/.test(x.text))
                    .filter(x => !x.text.includes('獨家提供') && !x.text.includes('法說會全文'))
                    .filter(x => !x.href.includes('/e-com/'))
                    .sort((a,b) => (a.n === '⭐逐字稿' ? -100 : 0) - (b.n === '⭐逐字稿' ? -100 : 0) || a.top-b.top || a.left-b.left);
                  if(!nodes.length) return {ok:false, reason:'no visible top tab'};
                  const t = nodes[0];
                  const clickEl = t.el.closest('a,button,[role="button"],.v-tab,.v-btn') || t.el;
                  clickEl.click();
                  return {ok:true, text:t.text, top:t.top, left:t.left, href:t.href};
                }
                """
            )
            actions.append(f"fallback visible top transcript tab {tag}: " + json.dumps(clicked, ensure_ascii=False)[:500])
            if isinstance(clicked, dict) and clicked.get("ok"):
                page.wait_for_timeout(5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                return True
        except Exception as e:
            actions.append(f"fallback visible top transcript tab failed {tag}: {str(e)[:120]}")
        return False

    click_visible_top_tab("last")
    return actions

def looks_like_intro_or_product_page(page) -> bool:
    try:
        body = extract_body_text(page)
        if "/e-com/product-detail" in (page.url or ""):
            return True
        intro_hits = sum(1 for x in ["產品目錄", "產品說明", "模組功能表", "Powered by", "選擇方案"] if x in body)
        article_hits = sum(1 for x in ["法說逐字稿", "法說會", "簡報", "影音"] if x in body)
        return intro_hits >= 2 and article_hits < 3
    except Exception:
        return False


def looks_like_transcript_article_list(page, stock_code: str) -> bool:
    code = normalize_stock_code(stock_code)
    try:
        body = extract_body_text(page)
        if looks_like_intro_or_product_page(page):
            return False
        if code and code not in body:
            return False
        strong = ("法說逐字稿" in body) or ("逐字稿" in body and "法說會" in body)
        cardish = bool(re.search(r"20\d{2}[/.-]\d{1,2}[/.-]\d{1,2}", body)) and ("簡報" in body or "影音" in body or "法說會" in body)
        return strong and cardish
    except Exception:
        return False




def force_open_transcript_list_url(page) -> List[str]:
    """最後保險：直接開使用者已驗證的 lab 逐字稿分頁，不走商城。"""
    actions = []
    try:
        page.goto("https://pro.uanalyze.com.tw/lab/dashboard/lynch-tengrower/44308", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        close_blockers(page)
        actions.append(f"direct transcript list url: {page.title()} / {page.url}")
    except Exception as e:
        actions.append(f"direct transcript list url failed: {str(e)[:120]}")
    return actions


def is_real_transcript_article(article: Dict, list_url: str) -> bool:
    """嚴格阻擋假成功：導覽頁、列表頁、虎八速覽頁、商城頁一律不算。"""
    text = article.get("text") or ""
    url = article.get("url") or ""
    if not text or len(text) < 1200:
        return False
    if url == list_url or url.endswith("/lab/dashboard/lynch-tengrower") or url.endswith("/lab/dashboard/lynch-tengrower/44308"):
        return False
    if "/lab/dashboard/41873" in url or "/e-com/" in url:
        return False
    bad = ["個股導航員", "新手必看 5 步驟", "STEP 1", "自動導航\n企業透視", "產業情報小助理", "常用分析\n自動導航", "產品目錄", "選擇方案"]
    if any(x in text for x in bad):
        return False
    transcript_keys = ["法說會", "Q&A", "問：", "答：", "管理層", "法人提問", "營收", "毛利率", "資本支出", "ABF", "IC載板"]
    if not any(x in text for x in transcript_keys):
        return False
    # 強化正文長度門檻：優先 >3000；若 >=1800 必須有足夠逐字稿特徵
    if len(text) < 3000:
        strong_hits = sum(1 for x in transcript_keys if x in text)
        if len(text) < 1800 or strong_hits < 4:
            return False
    if any(x in text for x in ["虎八速覽", "EPS法人預估", "累計月營收追蹤", "個股導航員", "新手必看 5 步驟", "優分析官方數據庫"]):
        return False
    return True


def build_failure_debug_bundle(page, run_dir: Path, reason: str, click_logs: List[Dict], menu_opened: bool):
    ts = human_now()
    try:
        (run_dir / "FAIL_REASON.txt").write_text(reason, encoding="utf-8")
    except Exception:
        pass
    try:
        (run_dir / "debug_clicked_elements.json").write_text(json.dumps(click_logs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    try:
        (run_dir / "debug_page_meta.json").write_text(
            json.dumps({"time": ts, "url": page.url, "title": page.title(), "menu_opened": menu_opened}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        body = page.evaluate("() => (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 8000)")
        (run_dir / "debug_body_8000.txt").write_text(body or "", encoding="utf-8")
    except Exception:
        pass
    try:
        candidates = page.evaluate(
            """
            () => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>2 && r.height>2 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0'; }
              return Array.from(document.querySelectorAll('a,button,[role="button"],div,span,li,p,h1,h2,h3'))
                .map(el => {
                  const t=(el.innerText||'').trim();
                  const r=el.getBoundingClientRect();
                  const a=el.closest('a');
                  return {innerText:t.slice(0,300), tagName:el.tagName, href:a?a.href:'', boundingBox:{x:r.x,y:r.y,width:r.width,height:r.height}, visible:visible(el)};
                })
                .filter(x => x.innerText.includes('逐字稿'))
                .slice(0,120);
            }
            """
        )
        (run_dir / "debug_transcript_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    try:
        menu_dom = page.evaluate(
            """
            () => {
              const bodyText=(document.body && document.body.innerText ? document.body.innerText : '').slice(0, 5000);
              const menuNodes = Array.from(document.querySelectorAll('nav,[role="menu"],.menu,.v-menu__content,.v-overlay__content,.v-list,.v-navigation-drawer'))
                .map(el => (el.innerText||'').trim())
                .filter(Boolean)
                .slice(0, 20);
              return {bodyText, menuNodes};
            }
            """
        )
        (run_dir / "debug_menu_dump.json").write_text(json.dumps(menu_dom, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    try:
        (run_dir / "debug_failed.png").write_bytes(page.screenshot(full_page=True))
    except Exception:
        pass

def activate_stock_on_transcript_tab(page, stock_code: str) -> List[str]:
    """逐字稿 tab 會先停在「個股導航員」首頁；這裡再點一次股票 chip，例如 3037 欣興。"""
    actions: List[str] = []
    code = normalize_stock_code(stock_code)

    def click_stock_chip(tag: str) -> bool:
        try:
            clicked = page.evaluate(
                """
                (code) => {
                  function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight; }
                  const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],.v-chip,.v-btn,div,span,li'))
                    .filter(visible)
                    .map(el => { const r=el.getBoundingClientRect(); const text=(el.innerText||'').replace(/\s+/g,' ').trim(); const a=el.closest('a'); return {el, text, top:r.top, left:r.left, width:r.width, height:r.height, href:a?a.href:''}; })
                    .filter(x => x.text.includes(code))
                    .filter(x => x.text.length <= 40)
                    .filter(x => x.top > 90)
                    .filter(x => !x.href.includes('/e-com/'))
                    .sort((a,b)=>a.text.length-b.text.length || a.top-b.top || a.left-b.left);
                  if(!nodes.length) return {ok:false, reason:'no stock chip'};
                  const t=nodes[0];
                  const clickEl = t.el.closest('a,button,[role="button"],.v-chip,.v-btn') || t.el;
                  clickEl.scrollIntoView({block:'center', inline:'center'});
                  clickEl.click();
                  return {ok:true, text:t.text, top:t.top, left:t.left, href:t.href};
                }
                """,
                code,
            )
            actions.append(f"click stock chip {tag}: " + json.dumps(clicked, ensure_ascii=False)[:500])
            if isinstance(clicked, dict) and clicked.get("ok"):
                page.wait_for_timeout(6500)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                return True
        except Exception as e:
            actions.append(f"click stock chip failed {tag}: {str(e)[:100]}")
        return False

    if looks_like_transcript_article_list(page, code):
        actions.append("transcript article list already visible")
        return actions
    for attempt in range(2):
        if click_stock_chip(f"attempt-{attempt+1}") and looks_like_transcript_article_list(page, code):
            actions.append("confirmed article list after stock chip")
            return actions

    selectors = ["input[placeholder*='股票代碼或名稱']", "input[placeholder*='股票代碼']", "input[placeholder*='代碼']", "input[placeholder*='搜尋']", "input[type='search']", "input[role='combobox']", "input[type='text']"]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=4000); loc.click(timeout=4000); loc.fill(code, timeout=4000)
                actions.append(f"filled transcript stock {code} by {selector}")
                page.wait_for_timeout(1200)
                try: loc.press("Enter", timeout=4000)
                except Exception: page.keyboard.press("Enter")
                page.wait_for_timeout(5500)
                click_stock_chip("after-search")
                if looks_like_transcript_article_list(page, code):
                    actions.append("confirmed article list after search")
                    return actions
                break
        except Exception as e:
            actions.append(f"transcript stock search failed {selector}: {str(e)[:80]}")
    return actions


def collect_transcript_candidates(page, stock_code: str) -> List[Dict]:
    """只抓真正逐字稿列表上的文章卡；排除產品介紹頁與虎八速覽全文。"""
    code = normalize_stock_code(stock_code)
    try:
        candidates = page.evaluate(
            """
            (code) => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>40 && r.height>15 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight; }
              function clean(t){ return (t||'').replace(/\s+/g,' ').trim(); }
              const badWords = ['產品目錄','產品說明','模組功能表','選擇方案','自動導航','企業透視','小助理','追蹤成長數據','搜尋雷達','使用教學','續約','募集達人','Cookie 技術','收盤價','上市','股本','最新財報','月營收'];
              const raw = Array.from(document.querySelectorAll('a,button,[role="button"],article,section,.v-card,.card,div,li'))
                .filter(visible)
                .map((el, idx) => { const r = el.getBoundingClientRect(); const text = clean(el.innerText || ''); const a = el.closest('a'); return {el, idx, text, top:r.top, left:r.left, width:r.width, height:r.height, href:a?a.href:'', cx:r.left + Math.min(Math.max(r.width*0.22, 24), Math.max(r.width-10, 25)), cy:r.top + Math.min(Math.max(r.height*0.35, 18), Math.max(r.height-10, 20))}; })
                .filter(x => x.text.length >= 18 && x.text.length <= 700)
                .filter(x => x.top >= 120)
                .filter(x => x.top > 140 || x.height >= 80)
                .filter(x => code ? x.text.includes(code) : true)
                .filter(x => x.text.includes('法說') || x.text.includes('逐字稿'))
                .filter(x => x.text.includes('法說逐字稿') || (x.text.includes('法說會') && x.text.includes('逐字稿')) || (x.text.includes('簡報') && x.text.includes('影音') && x.text.includes('法說')))
                .filter(x => !badWords.some(b => x.text.includes(b)))
                .filter(x => !/法說會[：:]\s*20\\d{2}[\\/-]\\d{1,2}[\\/-]\\d{1,2}/.test(x.text))
                .filter(x => !/逐字稿[：:]\s*20\\d{2}[\\/-]\\d{1,2}[\\/-]\\d{1,2}/.test(x.text))
                .sort((a,b) => { const as = (a.text.includes('法說逐字稿') ? -100 : 0) + (a.text.includes('簡報') ? -20 : 0) + a.text.length/50 + a.top/10; const bs = (b.text.includes('法說逐字稿') ? -100 : 0) + (b.text.includes('簡報') ? -20 : 0) + b.text.length/50 + b.top/10; return as-bs; });
              const seen = new Set(); const out = [];
              for (const x of raw) { let title = x.text; const m = title.match(new RegExp('([^\\n]{0,120}'+code+'[^\\n]{0,220}?法說[^\\n]{0,220})')); if (m) title = m[1].trim(); const key = title.slice(0, 100); if (seen.has(key)) continue; seen.add(key); out.push({idx:x.idx, text:x.text, title, top:x.top, left:x.left, width:x.width, height:x.height, cx:x.cx, cy:x.cy, href:x.href}); if (out.length >= 10) break; }
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
        clicked = page.evaluate(
            """
            ({cx, cy}) => {
              function visible(el){ const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>5 && r.height>5 && s.display!=='none' && s.visibility!=='hidden' && s.opacity!=='0' && r.bottom>0 && r.top<window.innerHeight; }
              const all = Array.from(document.querySelectorAll('button,a,[role="button"],.v-chip,.v-btn,span,div,li'))
                .filter(visible)
                .map(el => { const r=el.getBoundingClientRect(); return {el, text:(el.innerText||'').replace(/\s+/g,' ').trim(), top:r.top, left:r.left, width:r.width, height:r.height}; });
              const chips = all.filter(x => x.text === '逐字稿' || x.text.includes('逐字稿')).filter(x => Math.abs((x.top + x.height/2) - cy) < 120).sort((a,b)=>Math.abs((a.top+a.height/2)-cy)-Math.abs((b.top+b.height/2)-cy));
              if(chips.length){ const t=chips[0]; (t.el.closest('a,button,[role="button"],.v-chip,.v-btn') || t.el).click(); return {ok:true, method:'near transcript chip', text:t.text, top:t.top, left:t.left}; }
              return {ok:false, reason:'no nearby transcript chip'};
            }
            """,
            {"cx": c.get("cx"), "cy": c.get("cy")},
        )
        before_url = page.url
        before_head = (extract_body_text(page) or "")[:1800]
        if isinstance(clicked, dict) and clicked.get("ok"):
            page.wait_for_timeout(6000)
            try: page.wait_for_load_state("networkidle", timeout=20000)
            except Exception: pass
            after_url = page.url
            after_head = (extract_body_text(page) or "")[:1800]
            if (not c.get("href")) and after_url == before_url and after_head == before_head:
                return {"ok": False, "candidate": c, "candidate_count": len(candidates), "click": clicked, "error": "blank href and no page state change"}
            return {"ok": True, "candidate": c, "candidate_count": len(candidates), "click": clicked}
    except Exception:
        pass
    try:
        page.mouse.click(c["cx"], c["cy"])
        page.wait_for_timeout(6000)
        try: page.wait_for_load_state("networkidle", timeout=20000)
        except Exception: pass
        return {"ok": True, "candidate": c, "candidate_count": len(candidates), "click": {"method": "card coordinate"}}
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
    click_logs: List[Dict] = []

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
            # 用桌面版 viewport 跑，跟 iPad / 桌面看到的上方 bar 與右側三條線選單一致，
            # 避免手機版 layout 把「逐字稿」藏到另一層造成誤判。
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                is_mobile=False,
                has_touch=False,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
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

            status_box.write("開虎八速覽、切股票，再從左側欄進優分析產業資料庫...")
            log("開虎八速覽，不從商城進入")
            huba_actions = open_huba_quick_view(page)
            click_logs.append({"time": human_now(), "step": "open_huba", "actions": huba_actions, "url": page.url})
            close_blockers(page)
            log(f"虎八速覽：{page.title()} / {page.url}")
            log(f"切換股票代號：{code}")
            huba_stock_actions = switch_stock_on_huba(page, code)
            click_logs.append({"time": human_now(), "step": "switch_stock_huba", "actions": huba_stock_actions, "url": page.url})
            close_blockers(page)
            (run_dir / "02_huba_after_stock.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "02_huba_after_stock.png").write_bytes(page.screenshot(full_page=True))
            log(f"虎八速覽切股後：{page.title()} / {page.url} / current={detect_current_stock_code(extract_body_text(page)) or 'unknown'}")

            status_box.write("從左側收放欄點『優分析產業資料庫』...")
            log("只鎖定左側欄：我的訂閱 → 優分析產業資料庫；禁止 e-com 商城")
            db_actions = open_industry_database_from_huba(page, code)
            click_logs.append({"time": human_now(), "step": "open_database_sidebar", "actions": db_actions, "url": page.url})
            progress.progress(34)
            debug["open_database"] = {"huba_actions": huba_actions, "huba_stock_actions": huba_stock_actions, "db_actions": db_actions, "title": page.title(), "url": page.url}
            (run_dir / "03_database_page.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "03_database_page.png").write_bytes(page.screenshot(full_page=True))
            log(f"產業資料庫頁：{page.title()} / {page.url}")
            if is_wrong_mall_page(page):
                browser.close()
                st.error("仍然誤入商城 / e-com 商品頁，已停止；沒有輸出假成功。")
                build_failure_debug_bundle(page, run_dir, "誤入 /e-com 商城頁", click_logs, menu_opened=False)
                st.download_button("下載診斷 ZIP", data=build_zip_bytes(run_dir), file_name=f"{run_id}_wrong_ecom.zip", mime="application/zip")
                return
            if not looks_like_database_feature_page(page):
                # 仍可往下試，但先記錄警告。
                log("WARNING: database feature page not fully confirmed; continue to try transcript tab")

            # 理論上股票已在虎八速覽切好；若資料庫頁看不到股票代號，才補一次搜尋。
            db_body = extract_body_text(page)
            stock_actions = []
            if code not in db_body:
                status_box.write(f"資料庫頁補確認股票代號：{code}...")
                stock_actions = choose_stock_in_database(page, code)
                close_blockers(page)
                page.wait_for_timeout(3000)
            progress.progress(46)
            debug["stock"] = {"actions": stock_actions, "title": page.title(), "url": page.url}
            (run_dir / "04_database_after_stock_confirm.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "04_database_after_stock_confirm.png").write_bytes(page.screenshot(full_page=True))

            status_box.write("切到逐字稿分頁...")
            log("切到逐字稿分頁")
            tab_actions = click_transcript_tab(page)
            click_logs.append({"time": human_now(), "step": "click_transcript_tab", "actions": tab_actions, "url": page.url})
            close_blockers(page)
            page.wait_for_timeout(3500)
            log(f"逐字稿 tab 點擊後：{page.title()} / {page.url}")

            # 逐字稿 tab 常會先停在「個股導航員」首頁；必須再點一次 3037 欣興 chip 才會出現文章列表。
            activate_actions = activate_stock_on_transcript_tab(page, code)
            click_logs.append({"time": human_now(), "step": "activate_stock_on_transcript_tab", "actions": activate_actions, "url": page.url})
            close_blockers(page)
            page.wait_for_timeout(3500)
            progress.progress(52)
            debug["transcript_tab"] = {"tab_actions": tab_actions, "activate_actions": activate_actions, "title": page.title(), "url": page.url, "looks_like_article_list": looks_like_transcript_article_list(page, code), "looks_like_intro": looks_like_intro_or_product_page(page)}
            (run_dir / "05_transcript_list.txt").write_text(extract_body_text(page), encoding="utf-8")
            if show_screenshots:
                (run_dir / "05_transcript_list.png").write_bytes(page.screenshot(full_page=True))
            log(f"逐字稿列表頁驗證：article_list={looks_like_transcript_article_list(page, code)} / intro={looks_like_intro_or_product_page(page)} / {page.title()} / {page.url}")

            if not looks_like_transcript_article_list(page, code):
                log("逐字稿列表尚未確認；維持固定流程（虎八速覽→左側優分析產業資料庫→上方三條線→逐字稿），不使用直連捷徑")

            candidates = collect_transcript_candidates(page, code)
            debug["initial_candidates"] = candidates
            (run_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
            if not candidates or not looks_like_transcript_article_list(page, code):
                browser.close()
                build_failure_debug_bundle(page, run_dir, "無法進入真正逐字稿列表（可能仍在虎八速覽/個股導航員/商城）", click_logs, menu_opened=True)
                st.warning("沒有進到真正的逐字稿文章列表；已停止，沒有輸出假成功。請下載診斷 ZIP 給我看。")
                st.write("重點檢查：05_transcript_list.txt / 05_transcript_list.png / candidates.json")
                st.download_button(
                    "下載診斷 ZIP",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_id}_no_real_transcript_list.zip",
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
                click_logs.append({"time": human_now(), "step": f"open_candidate_{i+1}", "actions": click_result, "url": page.url})
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
                article["candidate"] = click_result

                real_ok = is_real_transcript_article(article, list_url)
                article["status"] = "成功" if real_ok else "失敗：不是逐字稿文章正文，已阻擋假成功"
                if not real_ok:
                    file_base = f"{i+1:02d}_FAILED_NOT_REAL_ARTICLE"
                    (run_dir / f"{file_base}.txt").write_text(article.get("text", ""), encoding="utf-8")
                    (run_dir / f"{file_base}.json").write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
                    log(f"阻擋假成功：{article.get('url')} / clean_length={article.get('clean_length')}")
                    go_back_to_list(page, list_url)
                    close_blockers(page)
                    continue

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

            if not articles:
                browser.close()
                build_failure_debug_bundle(page, run_dir, "所有候選文章都未通過逐字稿正文驗證", click_logs, menu_opened=True)
                st.warning("已阻擋假成功：沒有任何一篇通過『真正逐字稿文章正文』檢查。請下載診斷 ZIP 給我看。")
                st.write("重點檢查：05_transcript_list.txt、05b_transcript_list_after_direct.txt、candidates.json、FAILED_NOT_REAL_ARTICLE 檔案。")
                st.download_button(
                    "下載診斷 ZIP",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_id}_blocked_fake_success.zip",
                    mime="application/zip",
                )
                return

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
st.title("UAnalyze 產業情報小助理爬蟲｜逐字稿嚴格驗證版")
st.caption("第二區塊改成逐字稿文字爬取；本版改走上方 bar 右側白色三條線選單，再點「逐字稿」，並阻擋虎八速覽／自動導航／商城頁假成功。")

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
st.info("這一版不下載 CSV；重點是修正左側欄入口，避免再點到商城的「優分析產業資料庫」商品頁。")

st.divider()
st.subheader("第二區塊：逐字稿爬文")
st.write("流程：登入一次 → 虎八速覽切股票 → 左側收放欄點優分析產業資料庫 → 上方 bar 右側三條線選單 → 點逐字稿 → 逐篇抓文章文字。")

if st.button("抓取逐字稿", type="primary"):
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
