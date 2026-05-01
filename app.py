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

import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(page_title="UAnalyze 產業情報長時間爬蟲", layout="wide")

RUNS_DIR = Path("runs")
RUNS_DIR.mkdir(exist_ok=True)

TOPICS = [
    "近況發展",
    "產業趨勢",
    "產品線分析",
    "長短期展望",
    "供需分析",
    "觀察重點",
    "利多因素",
    "利空因素",
    "接單狀況",
    "資本支出",
    "新產品",
    "時間表",
    "相關公司",
    "同業競爭",
    "護城河分析",
    "併購分析",
    "重要數字",
    "公司概覽",
    "銷售地區",
    "名詞解釋",
]


# -----------------------------
# UI helpers
# -----------------------------

def safe_name(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text[:90] or "untitled"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def human_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def copy_button(text: str, label: str = "一鍵複製全部爬蟲結果"):
    safe_text = json.dumps(text or "", ensure_ascii=False)

    components.html(
        f"""
        <div style="margin: 12px 0;">
            <button
                onclick="copyTextToClipboard()"
                style="
                    background-color:#ff9800;
                    color:#111;
                    border:none;
                    border-radius:10px;
                    padding:14px 18px;
                    font-size:18px;
                    font-weight:700;
                    cursor:pointer;
                    width:100%;
                    max-width:520px;
                "
            >
                📋 {label}
            </button>
            <div id="copy-status" style="margin-top:10px;color:#20c997;font-size:16px;"></div>
        </div>

        <script>
        const textToCopy = {safe_text};

        async function copyTextToClipboard() {{
            const status = document.getElementById("copy-status");

            try {{
                await navigator.clipboard.writeText(textToCopy);
                status.innerText = "已複製到剪貼簿";
            }} catch (err) {{
                const textarea = document.createElement("textarea");
                textarea.value = textToCopy;
                textarea.style.position = "fixed";
                textarea.style.left = "0";
                textarea.style.top = "0";
                textarea.style.width = "1px";
                textarea.style.height = "1px";
                textarea.style.opacity = "0";
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();

                try {{
                    document.execCommand("copy");
                    status.innerText = "已複製到剪貼簿";
                }} catch (fallbackErr) {{
                    status.innerText = "複製失敗，請改用下方文字框長按複製";
                }}

                document.body.removeChild(textarea);
            }}
        }}
        </script>
        """,
        height=105,
    )


def build_zip_bytes(run_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for path in run_dir.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(run_dir))
    buffer.seek(0)
    return buffer.getvalue()


def latest_run_dirs(limit: int = 5):
    dirs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[:limit]


# -----------------------------
# Playwright helpers
# -----------------------------

def system_chromium_path():
    """Streamlit Cloud 有時候 apt 會安裝系統 chromium；這裡當備援瀏覽器。"""
    for name in ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
        path = shutil.which(name)
        if path:
            return path
    return None


@st.cache_resource(show_spinner=False)
def ensure_playwright_chromium() -> dict:
    """
    長時間版保險流程：
    1) 先確認 Python playwright 套件存在。
    2) 如果 Streamlit 沒吃到 requirements.txt，就在 App 內自動 pip install playwright。
    3) 再安裝 Playwright Chromium。
    4) 若 Playwright Chromium 下載失敗，但系統 chromium 存在，就改用系統 chromium。
    """
    logs = []

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
            return {
                "returncode": pip_result.returncode,
                "stdout": "\n".join(logs),
                "stderr": "pip install playwright failed",
                "system_chromium": system_chromium_path() or "",
            }

    install = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    logs.append("[playwright install chromium]\n" + (install.stdout or "") + (install.stderr or ""))

    sys_chrome = system_chromium_path()
    if install.returncode == 0 or sys_chrome:
        return {
            "returncode": 0,
            "stdout": "\n".join(logs),
            "stderr": install.stderr or "",
            "system_chromium": sys_chrome or "",
        }

    return {
        "returncode": install.returncode,
        "stdout": "\n".join(logs),
        "stderr": install.stderr,
        "system_chromium": "",
    }


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    skip_exact = {
        "深色主題",
        "帳戶和訂閱",
        "最新公告",
        "我的訂閱",
        "商城",
        "使用教學",
        "幫助",
        "產業達人",
    }

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line in skip_exact:
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def extract_body_text(page) -> str:
    try:
        return clean_text(page.locator("body").inner_text(timeout=15000))
    except Exception:
        return ""


def close_blockers(page):
    actions = []

    try:
        if page.get_by_text("重新整理", exact=False).count() > 0:
            page.get_by_text("重新整理", exact=False).first.click(timeout=5000)
            actions.append("clicked 重新整理")
            page.wait_for_timeout(7000)
    except Exception:
        pass

    try:
        body = page.locator("body").inner_text(timeout=5000)
        if "系統已有更新" in body or "請重新整理" in body:
            page.reload(wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(8000)
            actions.append("page.reload")
    except Exception:
        pass

    for t in ["我知道了", "同意", "接受", "接受所有", "OK"]:
        try:
            if page.get_by_text(t, exact=False).count() > 0:
                page.get_by_text(t, exact=False).last.click(timeout=5000)
                actions.append(f"clicked {t}")
                page.wait_for_timeout(2000)
                break
        except Exception:
            pass

    return actions


def fill_like_human(page, email: str, password: str):
    actions = []

    email_candidates = [
        "input[placeholder*='Email']",
        "input[placeholder*='email']",
        "input[type='email']",
        "input:not([type])",
        "input[type='text']",
    ]

    email_filled = False
    for selector in email_candidates:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.click(timeout=6000)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(email, delay=55)
                actions.append(f"typed email by {selector}")
                email_filled = True
                break
        except Exception:
            pass

    password_filled = False
    try:
        loc = page.locator("input[type='password']").first
        if loc.count() > 0:
            loc.click(timeout=6000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(password, delay=65)
            actions.append("typed password by input[type=password]")
            password_filled = True
    except Exception:
        pass

    page.wait_for_timeout(1500)

    return {
        "email_filled": email_filled,
        "password_filled": password_filled,
        "actions": actions,
    }


def click_login(page):
    methods = []

    try:
        buttons = page.locator("button").filter(has_text="登入")
        if buttons.count() > 0:
            buttons.last.click(timeout=6000)
            methods.append("clicked button has_text 登入")
            return methods
    except Exception:
        pass

    try:
        clicked = page.evaluate(
            """
            () => {
                function visible(el) {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 5 &&
                           r.height > 5 &&
                           s.display !== 'none' &&
                           s.visibility !== 'hidden' &&
                           s.opacity !== '0';
                }

                const nodes = Array.from(document.querySelectorAll('button, div, span, a'))
                    .filter(visible)
                    .map(el => ({
                        el,
                        text: (el.innerText || '').trim(),
                        top: el.getBoundingClientRect().top,
                    }))
                    .filter(x =>
                        (x.text === '登入' || x.text === '登 入') &&
                        !x.text.includes('Google') &&
                        !x.text.includes('Facebook') &&
                        !x.text.includes('Apple')
                    )
                    .sort((a, b) => a.top - b.top);

                if (!nodes.length) return false;

                nodes[nodes.length - 1].el.scrollIntoView({block: 'center'});
                nodes[nodes.length - 1].el.click();
                return true;
            }
            """
        )
        if clicked:
            methods.append("JS clicked native login")
            return methods
    except Exception:
        pass

    try:
        page.locator("input[type='password']").first.click(timeout=6000)
        page.keyboard.press("Enter")
        methods.append("pressed Enter in password field")
        return methods
    except Exception:
        pass

    return methods


def click_huba_quick_view(page):
    actions = []
    page.wait_for_timeout(3000)

    try:
        if page.get_by_text("虎八速覽", exact=False).count() > 0:
            page.get_by_text("虎八速覽", exact=False).first.click(timeout=6000)
            actions.append("clicked text 虎八速覽")
            page.wait_for_timeout(9000)
            return actions
    except Exception:
        pass

    try:
        clicked = page.evaluate(
            """
            () => {
                function visible(el) {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 5 &&
                           r.height > 5 &&
                           s.display !== 'none' &&
                           s.visibility !== 'hidden' &&
                           s.opacity !== '0';
                }

                const nodes = Array.from(document.querySelectorAll('button, a, div, span, li'))
                    .filter(visible)
                    .map(el => ({
                        el,
                        text: (el.innerText || '').trim(),
                        top: el.getBoundingClientRect().top,
                        left: el.getBoundingClientRect().left,
                        len: ((el.innerText || '').trim()).length
                    }))
                    .filter(x => x.text.includes('虎八速覽'))
                    .sort((a, b) => a.len - b.len || a.left - b.left || a.top - b.top);

                if (!nodes.length) return false;

                nodes[0].el.scrollIntoView({block: 'center'});
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

    actions.append("failed to click 虎八速覽")
    return actions


def normalize_stock_code(stock_code: str) -> str:
    """股票欄位只接受數字；例如輸入 3030_德律 也會自動轉成 3030。"""
    m = re.search(r"\d{4,6}", str(stock_code or ""))
    return m.group(0) if m else str(stock_code or "").strip()


def detect_current_stock_code(text: str) -> str:
    """從頁面文字抓目前個股研究筆記的股票代碼，避免爬錯還一路爬完。"""
    text = text or ""
    patterns = [
        r"股票代碼[：:]\s*\n\s*(\d{4,6})",
        r"股票代碼[：:]\s*(\d{4,6})",
        r"個股研究筆記[\s\S]{0,120}?股票代碼[：:]\s*\n\s*(\d{4,6})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def switch_stock(page, stock_code: str):
    actions = []
    query = normalize_stock_code(stock_code)

    if not query:
        actions.append("no stock code")
        return actions

    page.wait_for_timeout(3000)

    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1200)
    except Exception:
        pass

    search_selectors = [
        "input[placeholder*='搜尋代碼或名稱']",
        "input[placeholder*='搜尋代碼']",
        "input[placeholder*='股票代碼']",
        "input[placeholder*='代碼']",
        "input[placeholder*='搜尋']",
        "input[role='combobox']",
        "input[type='search']",
    ]

    def try_confirm_current(tag: str) -> bool:
        try:
            body = extract_body_text(page)
            current = detect_current_stock_code(body)
            if current == query:
                actions.append(f"confirmed current stock {current} after {tag}")
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    pass
                return True
        except Exception:
            pass
        return False

    if try_confirm_current("initial check"):
        return actions

    used_selector = ""

    # 先用 Playwright fill，這比純 keyboard.type 更容易觸發前端框架的 input/change event。
    for selector in search_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=6000)
                loc.click(timeout=6000)
                loc.fill(query, timeout=6000)
                used_selector = selector
                actions.append(f"filled stock code {query} by {selector}")
                page.wait_for_timeout(1800)

                # 這版重點：輸入股票代號後直接按 Enter。
                try:
                    loc.press("Enter", timeout=6000)
                    actions.append("pressed Enter on stock input")
                except Exception:
                    page.keyboard.press("Enter")
                    actions.append("pressed global Enter after stock input")

                page.wait_for_timeout(10000)
                if try_confirm_current("direct Enter"):
                    return actions

                break
        except Exception as e:
            actions.append(f"selector failed {selector}: {str(e)[:80]}")

    if not used_selector:
        # Fallback：用畫面上方搜尋框位置，手機 / 桌機版都盡量點上方中央偏右。
        for x, y in [(1050, 110), (980, 120), (900, 140), (720, 120)]:
            try:
                page.mouse.click(x, y)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(query, delay=70)
                actions.append(f"typed stock code {query} by coordinate fallback {x},{y}")
                page.wait_for_timeout(1600)
                page.keyboard.press("Enter")
                actions.append("pressed Enter by coordinate fallback")
                page.wait_for_timeout(10000)
                if try_confirm_current(f"coordinate {x},{y}"):
                    return actions
            except Exception as e:
                actions.append(f"coordinate failed {x},{y}: {str(e)[:80]}")

    # 若 Enter 沒吃到，再試一次：點第一個包含股票代號的搜尋結果。
    try:
        clicked = page.evaluate(
            """
            (code) => {
                function visible(el) {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 5 && r.height > 5 &&
                           s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                }
                const nodes = Array.from(document.querySelectorAll('button, a, div, span, li'))
                    .filter(visible)
                    .map(el => ({
                        el,
                        text: (el.innerText || '').trim(),
                        top: el.getBoundingClientRect().top,
                        left: el.getBoundingClientRect().left,
                        len: ((el.innerText || '').trim()).length
                    }))
                    .filter(x => x.text.includes(code))
                    .sort((a,b) => a.len - b.len || a.top - b.top || a.left - b.left);
                if (!nodes.length) return false;
                nodes[0].el.scrollIntoView({block:'center'});
                nodes[0].el.click();
                return true;
            }
            """,
            query,
        )
        if clicked:
            actions.append(f"JS clicked first result containing {query}")
            page.wait_for_timeout(12000)
            if try_confirm_current("JS clicked result"):
                return actions
    except Exception as e:
        actions.append(f"JS result click failed: {str(e)[:80]}")

    # 最後再補一次 ArrowDown + Enter。
    try:
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(800)
        page.keyboard.press("Enter")
        actions.append("pressed ArrowDown + Enter as final fallback")
        page.wait_for_timeout(12000)
        try_confirm_current("final ArrowDown Enter")
    except Exception as e:
        actions.append(f"final ArrowDown Enter failed: {str(e)[:80]}")

    return actions

def click_topic(page, topic: str):
    actions = []

    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
    except Exception:
        pass

    try:
        if page.get_by_text(topic, exact=True).count() > 0:
            page.get_by_text(topic, exact=True).last.click(timeout=6000)
            actions.append(f"clicked exact topic: {topic}")
            page.wait_for_timeout(2500)
            return actions
    except Exception:
        pass

    try:
        clicked = page.evaluate(
            """
            (topic) => {
                function visible(el) {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 5 &&
                           r.height > 5 &&
                           s.display !== 'none' &&
                           s.visibility !== 'hidden' &&
                           s.opacity !== '0';
                }

                const nodes = Array.from(document.querySelectorAll('button, a, div, span, li'))
                    .filter(visible)
                    .map(el => ({
                        el,
                        text: (el.innerText || '').trim(),
                        top: el.getBoundingClientRect().top,
                        left: el.getBoundingClientRect().left,
                        len: ((el.innerText || '').trim()).length
                    }))
                    .filter(x => x.text === topic || x.text.includes(topic))
                    .sort((a, b) => a.len - b.len || a.left - b.left || a.top - b.top);

                if (!nodes.length) return false;

                nodes[0].el.scrollIntoView({block: 'center'});
                nodes[0].el.click();
                return true;
            }
            """,
            topic,
        )
        if clicked:
            actions.append(f"JS clicked topic: {topic}")
            page.wait_for_timeout(2500)
            return actions
    except Exception:
        pass

    actions.append(f"failed to click topic: {topic}")
    return actions


def build_topic_markdown(company_label: str, topic_item: dict) -> str:
    return "\n".join([
        f"# {topic_item['topic']}",
        "",
        f"- 公司：{company_label}",
        f"- 擷取時間：{human_now()}",
        f"- 頁面標題：{topic_item.get('title', '')}",
        f"- 頁面網址：{topic_item.get('url', '')}",
        f"- 點擊狀態：{', '.join(topic_item.get('actions', []))}",
        "",
        "---",
        "",
        topic_item.get("text", "") or "無內容",
        "",
    ])


def build_all_markdown(company_label: str, topic_results: list, final_title: str, final_url: str) -> str:
    parts = [
        "# UAnalyze 產業情報小助理爬蟲結果",
        "",
        f"- 公司：{company_label}",
        f"- 擷取時間：{human_now()}",
        f"- 最後頁面標題：{final_title}",
        f"- 最後頁面網址：{final_url}",
        "",
        "---",
        "",
    ]

    for item in topic_results:
        parts.append(f"## {item['topic']}")
        parts.append("")
        parts.append(f"- 點擊狀態：{', '.join(item.get('actions', []))}")
        parts.append(f"- 頁面網址：{item.get('url', '')}")
        parts.append("")
        parts.append(item.get("text", "") or "無內容")
        parts.append("")
        parts.append("---")
        parts.append("")

    return "\n".join(parts)


def write_run_files(run_dir: Path, company_label: str, topic_results: list, final_title: str, final_url: str, debug: dict):
    run_dir.mkdir(parents=True, exist_ok=True)

    all_md = build_all_markdown(company_label, topic_results, final_title, final_url)
    (run_dir / "_ALL_CONTENT.md").write_text(all_md, encoding="utf-8")
    (run_dir / "debug_info.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in topic_results:
        topic_md = build_topic_markdown(company_label, item)
        (run_dir / f"{safe_name(item['topic'])}.md").write_text(topic_md, encoding="utf-8")

    return all_md



# -----------------------------
# Revenue CSV helpers（第二區塊專用；不改第一區塊爬蟲流程）
# -----------------------------

REVENUE_CHART_KEYWORD = "累計月營收追蹤"


def build_revenue_csv_markdown(company_label: str, csv_text: str, chart_title: str, page_title: str, page_url: str, method: str) -> str:
    return "\n".join([
        "# UAnalyze 累計月營收追蹤 CSV 擷取結果",
        "",
        f"- 公司：{company_label}",
        f"- 擷取時間：{human_now()}",
        f"- 頁面標題：{page_title}",
        f"- 頁面網址：{page_url}",
        f"- 圖表標題：{chart_title}",
        f"- 擷取方式：{method}",
        "",
        "---",
        "",
        csv_text or "",
        "",
    ])



def dismiss_page_overlays(page):
    """關閉搜尋下拉與 cookie 浮層。"""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass
    for t in ["我知道了", "OK", "同意", "接受"]:
        try:
            loc = page.get_by_text(t, exact=False)
            if loc.count() > 0:
                loc.last.click(timeout=2500)
                page.wait_for_timeout(800)
                break
        except Exception:
            pass


def scroll_revenue_section_into_view(page, keyword: str = REVENUE_CHART_KEYWORD) -> dict:
    """UAnalyze 的內容區常是內層捲動；用文字定位與滑鼠滾輪把第二區塊捲進畫面。"""
    dismiss_page_overlays(page)
    meta = {"ok": False, "method": "none"}
    try:
        loc = page.get_by_text(keyword, exact=False).last
        if loc.count() > 0:
            loc.scroll_into_view_if_needed(timeout=12000)
            page.wait_for_timeout(2500)
            return {"ok": True, "method": "text locator scroll_into_view"}
    except Exception as e:
        meta = {"ok": False, "method": "text locator failed", "error": str(e)[:180]}

    # 備援：在主內容區滾輪，這比 window.scrollTo 更適合 UAnalyze 這種內層捲動頁。
    try:
        page.mouse.move(1180, 820)
        for i in range(14):
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(700)
            visible = page.evaluate(
                """
                (keyword) => {
                    function visible(el){
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width > 5 && r.height > 5 && r.bottom > 60 && r.top < window.innerHeight - 60 && s.display !== 'none' && s.visibility !== 'hidden';
                    }
                    return Array.from(document.querySelectorAll('body *')).some(el => visible(el) && ((el.innerText || el.textContent || '').includes(keyword)));
                }
                """,
                keyword,
            )
            if visible:
                return {"ok": True, "method": f"mouse wheel {i+1}"}
    except Exception as e:
        return {"ok": False, "method": "mouse wheel failed", "error": str(e)[:180], "last_meta": meta}
    return {"ok": False, "method": "not found after mouse wheel", "last_meta": meta}


def find_revenue_export_button_coord(page, keyword: str = REVENUE_CHART_KEYWORD) -> dict:
    """找第二區塊那張 Highcharts 的右上角匯出按鈕座標。"""
    try:
        return page.evaluate(
            """
            (keyword) => {
                function rectObj(el){ const r=el.getBoundingClientRect(); return {top:r.top,left:r.left,width:r.width,height:r.height,bottom:r.bottom,right:r.right,x:r.left+r.width/2,y:r.top+r.height/2}; }
                const containers = Array.from(document.querySelectorAll('.highcharts-container'))
                    .map((el,index)=>{
                        const text=(el.innerText||el.textContent||'').trim();
                        const r=rectObj(el);
                        let score=0;
                        if(text.includes(keyword)) score+=1000;
                        if(text.includes('累計今年月營收')) score+=350;
                        if(text.includes('法人共識估計值')) score+=250;
                        if(text.includes('我的估計值')) score+=200;
                        if(text.includes('累計營收超法人預期')) score+=180;
                        if(text.includes('EPS')) score-=350;
                        if(text.includes('評等')) score-=250;
                        if(r.bottom>80 && r.top<window.innerHeight-80) score+=100;
                        return {el,index,text:text.slice(0,220),rect:r,score};
                    })
                    .filter(x=>x.rect.width>100 && x.rect.height>100)
                    .sort((a,b)=>b.score-a.score);
                const target = containers.find(x=>x.score>0);
                if(!target) return {ok:false,error:'target chart container not found',containers:containers.slice(0,6).map(x=>({score:x.score,text:x.text,rect:x.rect}))};
                const buttons = Array.from(target.el.querySelectorAll('.highcharts-contextbutton, .highcharts-exporting-group, g.highcharts-button, [aria-label*="Chart context menu"], [aria-label*="menu"]'))
                    .map(el=>({el,cls:el.getAttribute('class')||'',aria:el.getAttribute('aria-label')||'',rect:rectObj(el)}))
                    .filter(x=>x.rect.width>5 && x.rect.height>5)
                    .sort((a,b)=>{
                        const as=(a.cls.includes('contextbutton')?100:0)+(a.cls.includes('exporting')?50:0)+a.rect.left/1000;
                        const bs=(b.cls.includes('contextbutton')?100:0)+(b.cls.includes('exporting')?50:0)+b.rect.left/1000;
                        return bs-as;
                    });
                if(!buttons.length) return {ok:false,error:'export button not found',target:{score:target.score,text:target.text,rect:target.rect}};
                return {ok:true,x:buttons[0].rect.x,y:buttons[0].rect.y,button:buttons[0].rect,button_class:buttons[0].cls,button_aria:buttons[0].aria,target:{score:target.score,text:target.text,rect:target.rect}};
            }
            """,
            keyword,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def download_revenue_csv_via_menu(page, keyword: str = REVENUE_CHART_KEYWORD) -> dict:
    """不依賴 window.Highcharts；實際點右上角三條線再點 Download CSV。"""
    scroll_meta = scroll_revenue_section_into_view(page, keyword)
    coord = find_revenue_export_button_coord(page, keyword)
    if not coord.get("ok"):
        return {"ok": False, "error": "export button not found", "scroll_meta": scroll_meta, "coord": coord}
    try:
        page.mouse.click(coord["x"], coord["y"])
        page.wait_for_timeout(1000)
    except Exception as e:
        return {"ok": False, "error": "click export button failed: " + str(e)[:220], "scroll_meta": scroll_meta, "coord": coord}

    menu_debug = []
    try:
        items = page.locator(".highcharts-menu-item")
        for i in range(items.count()):
            item = items.nth(i)
            try:
                txt = item.inner_text(timeout=1000).strip()
            except Exception:
                txt = ""
            menu_debug.append(txt)
            upper = txt.upper().replace(" ", "")
            if "CSV" in upper and ("DOWNLOAD" in upper or "下載" in txt or "匯出" in txt):
                with page.expect_download(timeout=20000) as download_info:
                    item.click(timeout=6000)
                download = download_info.value
                path = download.path()
                raw = Path(path).read_bytes() if path else b""
                for enc in ["utf-8-sig", "utf-8", "cp950", "big5", "latin1"]:
                    try:
                        csv_text = raw.decode(enc)
                        break
                    except Exception:
                        csv_text = ""
                if not csv_text:
                    csv_text = raw.decode("utf-8", errors="replace")
                return {"ok": True, "csv": csv_text, "chart_title": keyword, "method": "Export menu Download CSV", "scroll_meta": scroll_meta, "coord": coord, "menu_items": menu_debug, "suggested_filename": download.suggested_filename}
    except Exception as e:
        menu_debug.append("menu item path failed: " + str(e)[:220])

    for txt in ["Download CSV", "下載 CSV", "下載CSV"]:
        try:
            loc = page.get_by_text(txt, exact=True).last
            if loc.count() > 0:
                with page.expect_download(timeout=20000) as download_info:
                    loc.click(timeout=6000)
                download = download_info.value
                path = download.path()
                raw = Path(path).read_bytes() if path else b""
                csv_text = raw.decode("utf-8-sig", errors="replace")
                return {"ok": True, "csv": csv_text, "chart_title": keyword, "method": f"text menu item {txt}", "scroll_meta": scroll_meta, "coord": coord, "menu_items": menu_debug, "suggested_filename": download.suggested_filename}
        except Exception as e:
            menu_debug.append(f"text {txt} failed: {str(e)[:120]}")

    return {"ok": False, "error": "CSV menu item not clicked/downloaded", "scroll_meta": scroll_meta, "coord": coord, "menu_items": menu_debug}

def find_revenue_highcharts_csv(page, keyword: str = REVENUE_CHART_KEYWORD) -> dict:
    try:
        result = page.evaluate(
            r"""
            (keyword) => {
                const hc = window.Highcharts;
                if (!hc || !hc.charts) return {ok:false, error:'Highcharts not found'};
                const charts = hc.charts.map((chart, index) => ({chart, index})).filter(x => x.chart);
                const candidates = charts.map(x => {
                    const c = x.chart;
                    const title = (c.title && (c.title.textStr || c.title.element?.textContent)) || '';
                    const subtitle = (c.subtitle && (c.subtitle.textStr || c.subtitle.element?.textContent)) || '';
                    const renderText = (c.renderTo && c.renderTo.innerText) || '';
                    return {index:x.index, title, subtitle, renderText, haystack:[title, subtitle, renderText].join('\n')};
                });
                const target = candidates.find(x => x.haystack.includes(keyword));
                if (!target) return {ok:false, error:'target chart not found', charts:candidates.map(x => ({index:x.index, title:x.title, subtitle:x.subtitle, text:x.renderText.slice(0,120)}))};
                const chart = hc.charts[target.index];
                if (typeof chart.getCSV === 'function') {
                    const csv = chart.getCSV();
                    return {ok:true, csv, chart_title: target.title || target.subtitle || keyword, chart_index: target.index, method:'Highcharts.getCSV'};
                }
                if (typeof chart.getDataRows === 'function') {
                    const rows = chart.getDataRows();
                    const escapeCell = (value) => {
                        if (value === null || value === undefined) return '';
                        const s = String(value);
                        if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
                        return s;
                    };
                    const csv = rows.map(row => row.map(escapeCell).join(',')).join('\n');
                    return {ok:true, csv, chart_title: target.title || target.subtitle || keyword, chart_index: target.index, method:'Highcharts.getDataRows'};
                }
                return {ok:false, error:'target chart found but CSV API unavailable', chart_index: target.index, chart_title: target.title || keyword};
            }
            """,
            keyword,
        )
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "unexpected JS result"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_revenue_csv_with_scroll(page, keyword: str = REVENUE_CHART_KEYWORD) -> dict:
    """第二區塊 CSV：先抓 Highcharts API；若沒有 window.Highcharts，就改用實際下載選單。"""
    dismiss_page_overlays(page)
    try:
        page.wait_for_timeout(2500)
    except Exception:
        pass

    scroll_meta = scroll_revenue_section_into_view(page, keyword)
    last = find_revenue_highcharts_csv(page, keyword)
    if last.get("ok") and (last.get("csv") or "").strip():
        last["scroll_meta"] = scroll_meta
        return last

    menu_result = download_revenue_csv_via_menu(page, keyword)
    if menu_result.get("ok") and (menu_result.get("csv") or "").strip():
        menu_result["previous_js_result"] = {k: v for k, v in last.items() if k != "csv"}
        return menu_result

    for i in range(8):
        try:
            page.keyboard.press("Escape")
            page.mouse.move(1180, 840)
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        last = find_revenue_highcharts_csv(page, keyword)
        if last.get("ok") and (last.get("csv") or "").strip():
            last["scroll_loop"] = i + 1
            return last
        menu_result = download_revenue_csv_via_menu(page, keyword)
        if menu_result.get("ok") and (menu_result.get("csv") or "").strip():
            menu_result["scroll_loop"] = i + 1
            menu_result["previous_js_result"] = {k: v for k, v in last.items() if k != "csv"}
            return menu_result

    return {"ok": False, "error": "all revenue CSV methods failed", "scroll_meta": scroll_meta, "js_result": {k: v for k, v in last.items() if k != "csv"}, "menu_result": {k: v for k, v in menu_result.items() if k != "csv"}}


def write_revenue_run_files(run_dir: Path, company_label: str, csv_text: str, markdown_text: str, debug: dict):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "revenue_tracking.csv").write_text(csv_text or "", encoding="utf-8")
    (run_dir / "revenue_tracking.md").write_text(markdown_text or "", encoding="utf-8")
    (run_dir / "debug_info.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")



def run_revenue_csv_only(login_url: str, email: str, password: str, stock_code: str, wait_seconds: int, show_intermediate_images: bool):
    """第二區塊獨立流程：只登入、開虎八速覽、切股票、抓累計月營收 CSV；不跑第一區塊 TOPICS。"""
    company_label = normalize_stock_code(stock_code)
    run_id = f"{now_stamp()}_{safe_name(company_label)}_revenue_only"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()
    logs = []

    def log(msg: str):
        line = f"[{human_now()}] {msg}"
        logs.append(line)
        log_box.text("\n".join(logs[-12:]))
        try:
            (run_dir / "run_log.txt").write_text("\n".join(logs), encoding="utf-8")
        except Exception:
            pass

    try:
        if not email or not password:
            st.error("請先在上方輸入 UAnalyze Email 和密碼。")
            st.stop()
        if not company_label:
            st.error("請先在上方輸入股票代號，只填數字，例如 3030。")
            st.stop()

        st.info("第二區塊獨立執行：只抓累計月營收 CSV，不會跑第一區塊欄位。")
        install = ensure_playwright_chromium()
        if install["returncode"] != 0:
            st.error("Playwright Chromium 安裝 / 檢查失敗。")
            st.code(install["stdout"] + "\n" + install["stderr"])
            st.stop()

        from playwright.sync_api import sync_playwright

        debug = {
            "run_id": run_id,
            "company_label": company_label,
            "mode": "revenue_only_independent",
            "started_at": human_now(),
        }

        with sync_playwright() as p:
            sys_chrome = install.get("system_chromium") or system_chromium_path()
            launch_kwargs = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if sys_chrome:
                launch_kwargs["executable_path"] = sys_chrome
                log(f"使用系統 Chromium：{sys_chrome}")

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1440, "height": 1000},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(90000)

            status_box.write("登入 UAnalyze 中...")
            log("登入 UAnalyze")
            page.goto(login_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)
            blocker_actions = close_blockers(page)
            fill_result = fill_like_human(page, email, password)
            login_methods = click_login(page)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(wait_seconds * 1000)
            progress.progress(20)
            debug.update({
                "blocker_actions": blocker_actions,
                "fill_result": fill_result,
                "login_methods": login_methods,
                "login_title": page.title(),
                "login_url_after": page.url,
            })
            (run_dir / "debug_login_text.txt").write_text(extract_body_text(page), encoding="utf-8")
            log(f"登入後：{page.title()} / {page.url}")
            if show_intermediate_images:
                try:
                    st.image(page.screenshot(full_page=True), caption="第二區塊：登入後截圖")
                except Exception:
                    pass

            status_box.write("開啟虎八速覽中...")
            log("開啟虎八速覽")
            huba_actions = click_huba_quick_view(page)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(7000)
            progress.progress(35)
            debug.update({
                "huba_actions": huba_actions,
                "huba_title": page.title(),
                "huba_url": page.url,
            })
            (run_dir / "debug_huba_text.txt").write_text(extract_body_text(page), encoding="utf-8")
            log(f"虎八速覽：{page.title()} / {page.url}")

            status_box.write(f"切換股票代號：{company_label} ...")
            log(f"切換股票代號：{company_label}")
            stock_actions = switch_stock(page, company_label)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(8000)
            after_stock_text = extract_body_text(page)
            current_code_after_switch = detect_current_stock_code(after_stock_text)
            debug.update({
                "stock_actions": stock_actions,
                "after_stock_title": page.title(),
                "after_stock_url": page.url,
                "current_code_after_switch": current_code_after_switch,
            })
            (run_dir / "debug_after_stock_text.txt").write_text(after_stock_text, encoding="utf-8")
            try:
                (run_dir / "after_stock_screenshot.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            progress.progress(55)
            log(f"切換股票後：{page.title()} / {page.url} / current={current_code_after_switch or 'unknown'}")

            if current_code_after_switch and current_code_after_switch != company_label:
                st.error(f"股票代號沒有成功切換：目前仍是 {current_code_after_switch}，目標是 {company_label}。已停止抓 CSV，避免抓錯公司。")
                st.download_button(
                    label="下載第二區塊切換失敗診斷 ZIP",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_id}_switch_failed.zip",
                    mime="application/zip",
                )
                browser.close()
                st.stop()
            elif not current_code_after_switch:
                st.warning("無法從頁面文字確認目前股票代號，仍會繼續抓 CSV；若結果不是目標股票，請下載 ZIP 查看 after_stock_screenshot.png。")

            status_box.write("尋找並擷取『累計月營收追蹤』CSV...")
            log("尋找累計月營收追蹤 Highcharts CSV")
            csv_result = get_revenue_csv_with_scroll(page, REVENUE_CHART_KEYWORD)
            debug["revenue_csv_result_meta"] = {k: v for k, v in csv_result.items() if k != "csv"}

            if csv_result.get("ok") and (csv_result.get("csv") or "").strip():
                csv_text = csv_result.get("csv") or ""
                md_text = build_revenue_csv_markdown(
                    company_label,
                    csv_text,
                    csv_result.get("chart_title") or REVENUE_CHART_KEYWORD,
                    page.title(),
                    page.url,
                    csv_result.get("method") or "Highcharts CSV",
                )
                write_revenue_run_files(run_dir, company_label, csv_text, md_text, debug)
                try:
                    (run_dir / "revenue_page_screenshot.png").write_bytes(page.screenshot(full_page=True))
                except Exception:
                    pass
                browser.close()
                progress.progress(100)
                status_box.write("第二區塊完成。")
                log("第二區塊完成：CSV 已取得")

                st.success(f"第二區塊完成：已抓到 {company_label} 的累計月營收追蹤 CSV。")
                copy_button(csv_text, "一鍵複製累計月營收 CSV")
                st.text_area("累計月營收 CSV", csv_text, height=420)
                c1, c2 = st.columns(2)
                with c1:
                    st.download_button(
                        label="下載累計月營收 CSV",
                        data=csv_text.encode("utf-8-sig"),
                        file_name=f"{run_id}_revenue_tracking.csv",
                        mime="text/csv",
                    )
                with c2:
                    st.download_button(
                        label="下載第二區塊診斷 ZIP",
                        data=build_zip_bytes(run_dir),
                        file_name=f"{run_id}.zip",
                        mime="application/zip",
                    )
                return

            debug["revenue_csv_failed"] = {k: v for k, v in csv_result.items() if k != "csv"}
            (run_dir / "revenue_csv_failed.json").write_text(json.dumps(debug["revenue_csv_failed"], ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                (run_dir / "revenue_failed_screenshot.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            browser.close()
            progress.progress(100)
            st.warning("第二區塊沒有成功取得累計月營收 CSV。請下載診斷 ZIP，裡面有 revenue_csv_failed.json 與截圖。")
            st.download_button(
                label="下載第二區塊診斷 ZIP",
                data=build_zip_bytes(run_dir),
                file_name=f"{run_id}_revenue_failed.zip",
                mime="application/zip",
            )

    except Exception as e:
        st.error("第二區塊獨立流程失敗。")
        st.exception(e)
        try:
            (run_dir / "error.txt").write_text(str(e), encoding="utf-8")
        except Exception:
            pass
        if run_dir.exists() and any(run_dir.iterdir()):
            st.download_button(
                label="下載第二區塊暫存 ZIP",
                data=build_zip_bytes(run_dir),
                file_name=f"{run_id}_partial.zip",
                mime="application/zip",
            )


# -----------------------------
# 第二區塊：多圖表 CSV 下載 helpers（新增；不動第一區塊 TOPICS）
# -----------------------------

SECOND_BLOCK_CHART_SPECS = [
    {"key":"revenue_tracking","label":"累計月營收追蹤(實際營收vs法人vs我的預估)-新版","keyword":"累計月營收追蹤","filename":"01_累計月營收追蹤.csv","match_keywords":["累計今年月營收","法人共識估計值","我的估計值","累計營收超法人預期"],"exclude_keywords":["EPS","評等"]},
    {"key":"quarter_eps","label":"季EPS表現追蹤(實際VS法人共識)","keyword":"季EPS表現追蹤","filename":"02_季EPS表現追蹤.csv","match_keywords":["實際EPS","法人共識","季股價","季EPS超乎法人預期"],"exclude_keywords":["累計月營收","營收趨勢","毛利率表現"]},
    {"key":"quarter_revenue","label":"季營收表現追蹤(實際VS法人共識)","keyword":"季營收表現追蹤","filename":"03_季營收表現追蹤.csv","match_keywords":["實際營收","法人共識","季營收","季營收超乎法人預期"],"exclude_keywords":["累計月營收","EPS","毛利率表現"]},
    {"key":"quarter_gm","label":"季毛利率表現追蹤(實際VS法人共識)","keyword":"季毛利率表現追蹤","filename":"04_季毛利率表現追蹤.csv","match_keywords":["實際毛利率","法人共識","毛利率","季毛利率"],"exclude_keywords":["累計月營收","EPS","季營收表現"]},
    {"key":"revenue_profit_quarter","label":"營收趨勢與利潤率比較圖（季度）","keyword":"營收趨勢與利潤率比較圖","filename":"05_營收趨勢與利潤率比較圖_季度.csv","match_keywords":["營業收入淨額","毛利率","營業利益率","稅後淨利率"],"exclude_keywords":["累計月營收","法人共識"],"pre_click_text":"季度"},
    {"key":"inventory_sales_ratio","label":"存貨銷售比(月)(每季更新一次)","keyword":"存貨銷售比","filename":"06_存貨銷售比.csv","match_keywords":["存貨銷售比","每季更新一次","月"],"exclude_keywords":["合約負債","存貨細項"]},
    {"key":"contract_liability","label":"合約負債VS佔營收比重VS季營收","keyword":"合約負債","filename":"07_合約負債VS佔營收比重VS季營收.csv","match_keywords":["合約負債","佔營收比重","季營收"],"exclude_keywords":["存貨銷售比","存貨細項"]},
    {"key":"inventory_detail_raw","label":"存貨細項(原始科目)","keyword":"存貨細項","filename":"08_存貨細項_原始科目.csv","match_keywords":["原始科目","存貨細項","原料","在製品","製成品"],"exclude_keywords":["存貨銷售比","合約負債"]},
]


def decode_downloaded_bytes(raw: bytes) -> str:
    for enc in ["utf-8-sig", "utf-8", "cp950", "big5", "latin1"]:
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def scroll_chart_section_into_view_multi(page, spec: dict) -> dict:
    keyword = spec.get("keyword") or spec.get("label") or ""
    dismiss_page_overlays(page)
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
    except Exception:
        pass

    # 先用 JS 找短標題，scrollIntoView 對內層捲動容器比較有效。
    try:
        meta = page.evaluate(
            """
            (keyword) => {
                function txt(el){ return (el.innerText || el.textContent || '').trim(); }
                function rect(el){ const r=el.getBoundingClientRect(); return {top:r.top,left:r.left,bottom:r.bottom,right:r.right,width:r.width,height:r.height}; }
                const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p'))
                    .map(el => ({el, text:txt(el), rect:rect(el)}))
                    .filter(x => x.text && x.text.includes(keyword) && x.text.length < 280 && x.rect.width > 5 && x.rect.height > 5)
                    .sort((a,b) => a.text.length - b.text.length || a.rect.top - b.rect.top);
                if (!nodes.length) return {ok:false, method:'js title not found'};
                nodes[0].el.scrollIntoView({block:'center', inline:'nearest'});
                return {ok:true, method:'js scrollIntoView title', text:nodes[0].text.slice(0,160), rect:nodes[0].rect};
            }
            """,
            keyword,
        )
        page.wait_for_timeout(2200)
        if isinstance(meta, dict) and meta.get("ok"):
            return meta
    except Exception as e:
        meta = {"ok": False, "method": "js scroll failed", "error": str(e)[:180]}

    # 備援：用 Playwright 文字定位。
    try:
        loc = page.get_by_text(keyword, exact=False).last
        if loc.count() > 0:
            loc.scroll_into_view_if_needed(timeout=12000)
            page.wait_for_timeout(2200)
            return {"ok": True, "method": "playwright locator scroll"}
    except Exception as e:
        meta = {"ok": False, "method": "locator failed", "error": str(e)[:180]}

    # 最後備援：滑鼠滾輪找。
    try:
        page.mouse.move(1180, 820)
        for i in range(26):
            page.mouse.wheel(0, 760)
            page.wait_for_timeout(650)
            visible = page.evaluate(
                """
                (keyword) => {
                    function visible(el){
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width > 5 && r.height > 5 && r.bottom > 80 && r.top < window.innerHeight - 60 && s.display !== 'none' && s.visibility !== 'hidden';
                    }
                    return Array.from(document.querySelectorAll('body *')).some(el => visible(el) && ((el.innerText || el.textContent || '').includes(keyword)));
                }
                """,
                keyword,
            )
            if visible:
                return {"ok": True, "method": f"mouse wheel {i+1}"}
    except Exception as e:
        return {"ok": False, "method": "mouse wheel failed", "error": str(e)[:180], "last_meta": meta}
    return {"ok": False, "method": "not found after mouse wheel", "last_meta": meta}


def click_section_button_multi(page, spec: dict, button_text: str) -> dict:
    keyword = spec.get("keyword") or spec.get("label") or ""
    try:
        result = page.evaluate(
            """
            ({keyword, buttonText}) => {
                function visible(el){
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 5 && r.height > 5 && r.bottom > 40 && r.top < window.innerHeight - 30 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
                }
                function rect(el){ const r=el.getBoundingClientRect(); return {top:r.top,left:r.left,bottom:r.bottom,right:r.right,width:r.width,height:r.height,x:r.left+r.width/2,y:r.top+r.height/2}; }
                function txt(el){ return (el.innerText || el.textContent || '').trim(); }
                const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p'))
                    .map(el => ({el, text:txt(el), rect:rect(el)}))
                    .filter(x => x.text && x.text.includes(keyword) && x.text.length < 280)
                    .sort((a,b) => a.text.length - b.text.length || a.rect.top - b.rect.top);
                const h = headings[0] || null;
                const nodes = Array.from(document.querySelectorAll('button, a, div, span'))
                    .filter(visible)
                    .map(el => ({el, text:txt(el), rect:rect(el)}))
                    .filter(x => x.text === buttonText || x.text.replace(/\s+/g,'') === buttonText);
                let candidates = nodes;
                if (h) candidates = nodes.filter(x => x.rect.top >= h.rect.top - 40 && x.rect.top <= h.rect.bottom + 300);
                if (!candidates.length) candidates = nodes;
                candidates.sort((a,b) => {
                    const da = h ? Math.abs(a.rect.top - h.rect.bottom) : Math.abs(a.rect.top - 180);
                    const db = h ? Math.abs(b.rect.top - h.rect.bottom) : Math.abs(b.rect.top - 180);
                    return da - db || a.rect.left - b.rect.left;
                });
                if (!candidates.length) return {ok:false, error:'button not found', heading:h ? {text:h.text, rect:h.rect} : null};
                candidates[0].el.click();
                return {ok:true, method:'js click nearby button', text:candidates[0].text, rect:candidates[0].rect, heading:h ? {text:h.text, rect:h.rect} : null};
            }
            """,
            {"keyword": keyword, "buttonText": button_text},
        )
        page.wait_for_timeout(2400)
        if isinstance(result, dict):
            return result
    except Exception as e:
        result = {"ok": False, "error": str(e)[:220]}
    try:
        loc = page.get_by_text(button_text, exact=True).last
        if loc.count() > 0:
            loc.click(timeout=5000)
            page.wait_for_timeout(2400)
            return {"ok": True, "method": "playwright text fallback"}
    except Exception:
        pass
    return result


def find_chart_export_button_coord_multi(page, spec: dict) -> dict:
    try:
        return page.evaluate(
            """
            (spec) => {
                const keyword = spec.keyword || spec.label || '';
                const matchKeywords = [keyword].concat(spec.match_keywords || []).filter(Boolean);
                const excludeKeywords = spec.exclude_keywords || [];
                function rect(el){ const r=el.getBoundingClientRect(); return {top:r.top,left:r.left,width:r.width,height:r.height,bottom:r.bottom,right:r.right,x:r.left+r.width/2,y:r.top+r.height/2}; }
                function txt(el){ return (el.innerText || el.textContent || '').trim(); }
                function visibleRect(r){ return r.width > 60 && r.height > 60 && r.bottom > 40 && r.top < window.innerHeight - 30; }
                const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p'))
                    .map(el => ({el, text:txt(el), rect:rect(el)}))
                    .filter(x => x.text && x.text.includes(keyword) && x.text.length < 280)
                    .sort((a,b) => a.text.length - b.text.length || a.rect.top - b.rect.top);
                const heading = headings[0] || null;
                const containers = Array.from(document.querySelectorAll('.highcharts-container'))
                    .map((el,index)=>{
                        const text=txt(el);
                        const r=rect(el);
                        let score=0;
                        for (const kw of matchKeywords) if (kw && text.includes(kw)) score += (kw === keyword ? 1150 : 260);
                        for (const ex of excludeKeywords) if (ex && text.includes(ex)) score -= 380;
                        if (visibleRect(r)) score += 140;
                        if (heading) {
                            const dist = r.top - heading.rect.bottom;
                            if (dist > -160 && dist < 820) score += Math.max(0, 680 - Math.abs(dist));
                        }
                        return {el,index,text:text.slice(0,340),rect:r,score};
                    })
                    .filter(x=>x.rect.width>100 && x.rect.height>100)
                    .sort((a,b)=>b.score-a.score || a.rect.top-b.rect.top);
                let target = containers.find(x => x.score > 0);
                if (!target && heading) {
                    target = containers.filter(x => x.rect.top >= heading.rect.top - 180)
                        .sort((a,b)=>Math.abs(a.rect.top-heading.rect.bottom)-Math.abs(b.rect.top-heading.rect.bottom))[0];
                }
                if(!target) return {ok:false,error:'target chart container not found',keyword,heading:heading ? {text:heading.text, rect:heading.rect} : null,containers:containers.slice(0,8).map(x=>({score:x.score,text:x.text,rect:x.rect}))};
                const buttons = Array.from(target.el.querySelectorAll('.highcharts-contextbutton, .highcharts-exporting-group, g.highcharts-button, [aria-label*="Chart context menu"], [aria-label*="menu"]'))
                    .map(el=>({el,cls:el.getAttribute('class')||'',aria:el.getAttribute('aria-label')||'',rect:rect(el)}))
                    .filter(x=>x.rect.width>5 && x.rect.height>5)
                    .sort((a,b)=>{
                        const as=(a.cls.includes('contextbutton')?100:0)+(a.cls.includes('exporting')?50:0)+a.rect.left/1000;
                        const bs=(b.cls.includes('contextbutton')?100:0)+(b.cls.includes('exporting')?50:0)+b.rect.left/1000;
                        return bs-as;
                    });
                if(buttons.length) return {ok:true,x:buttons[0].rect.x,y:buttons[0].rect.y,button:buttons[0].rect,button_class:buttons[0].cls,button_aria:buttons[0].aria,target:{score:target.score,text:target.text,rect:target.rect},heading:heading ? {text:heading.text, rect:heading.rect} : null};
                return {ok:true,x:Math.max(target.rect.left + 20, target.rect.right - 28),y:target.rect.top + 28,estimated:true,target:{score:target.score,text:target.text,rect:target.rect},heading:heading ? {text:heading.text, rect:heading.rect} : null};
            }
            """,
            spec,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def try_highcharts_csv_api_multi(page, spec: dict) -> dict:
    try:
        result = page.evaluate(
            r"""
            (spec) => {
                const hc = window.Highcharts;
                const keyword = spec.keyword || spec.label || '';
                const matchKeywords = [keyword].concat(spec.match_keywords || []).filter(Boolean);
                const excludeKeywords = spec.exclude_keywords || [];
                if (!hc || !hc.charts) return {ok:false, error:'Highcharts not found'};
                const charts = hc.charts.map((chart, index) => ({chart, index})).filter(x => x.chart);
                const candidates = charts.map(x => {
                    const c = x.chart;
                    const title = (c.title && (c.title.textStr || c.title.element?.textContent)) || '';
                    const subtitle = (c.subtitle && (c.subtitle.textStr || c.subtitle.element?.textContent)) || '';
                    const renderText = (c.renderTo && (c.renderTo.innerText || c.renderTo.textContent)) || '';
                    const haystack = [title, subtitle, renderText].join('\n');
                    let score = 0;
                    for (const kw of matchKeywords) if (kw && haystack.includes(kw)) score += (kw === keyword ? 1000 : 220);
                    for (const ex of excludeKeywords) if (ex && haystack.includes(ex)) score -= 320;
                    return {index:x.index, title, subtitle, text:renderText.slice(0,220), score};
                }).sort((a,b)=>b.score-a.score);
                const target = candidates.find(x => x.score > 0);
                if (!target) return {ok:false, error:'target chart not found', charts:candidates.slice(0,8)};
                const chart = hc.charts[target.index];
                if (typeof chart.getCSV === 'function') return {ok:true, csv:chart.getCSV(), chart_title:target.title || target.subtitle || keyword, chart_index:target.index, method:'Highcharts.getCSV'};
                if (typeof chart.getDataRows === 'function') {
                    const rows = chart.getDataRows();
                    const esc = (v) => {
                        if (v === null || v === undefined) return '';
                        const s = String(v);
                        if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
                        return s;
                    };
                    return {ok:true, csv:rows.map(row => row.map(esc).join(',')).join('\n'), chart_title:target.title || target.subtitle || keyword, chart_index:target.index, method:'Highcharts.getDataRows'};
                }
                return {ok:false, error:'target chart found but CSV API unavailable', chart_index:target.index, chart_title:target.title || keyword};
            }
            """,
            spec,
        )
        return result if isinstance(result, dict) else {"ok": False, "error": "unexpected JS result"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}





def install_browser_download_capture_patch(page) -> dict:
    """在頁面內攔截 Highcharts 下載 CSV 產生的 data/blob URL。
    重點：不點「顯示數值」，只攔截「下載為 CSV 檔」本身產生的檔案內容。
    """
    try:
        return page.evaluate(
            r"""
            () => {
                window.__uanalyzeDownloads = [];
                window.__uanalyzeBlobTexts = {};
                window.__uanalyzeLastCsvText = '';
                window.__uanalyzeLastCsvFilename = '';

                function pushDownload(d) {
                    try {
                        d.ts = Date.now();
                        window.__uanalyzeDownloads.push(d);
                    } catch(e) {}
                }

                function looksCsvText(t) {
                    if (!t || typeof t !== 'string') return false;
                    const head = t.slice(0, 800);
                    return head.includes(',') || head.includes('\n') || head.includes('Date') || head.includes('日期') || head.includes('營收') || head.includes('EPS') || head.includes('毛利') || head.includes('存貨') || head.includes('合約負債');
                }

                function decodeDataUrl(href) {
                    try {
                        const comma = href.indexOf(',');
                        if (comma < 0) return '';
                        const meta = href.slice(5, comma);
                        const payload = href.slice(comma + 1);
                        if (meta.includes(';base64')) {
                            try {
                                return new TextDecoder('utf-8').decode(Uint8Array.from(atob(payload), c => c.charCodeAt(0)));
                            } catch(e) { return atob(payload); }
                        }
                        return decodeURIComponent(payload);
                    } catch(e) { return ''; }
                }

                if (!window.__uanalyzeDownloadPatchInstalledV2) {
                    window.__uanalyzeDownloadPatchInstalledV2 = true;

                    const origCreateObjectURL = URL.createObjectURL.bind(URL);
                    URL.createObjectURL = function(obj) {
                        const url = origCreateObjectURL(obj);
                        try {
                            if (obj && typeof obj.text === 'function') {
                                const meta = {url, type:obj.type || '', size:obj.size || 0, source:'URL.createObjectURL'};
                                obj.text().then(t => {
                                    window.__uanalyzeBlobTexts[url] = {...meta, text:t, ts:Date.now()};
                                    if (looksCsvText(t)) {
                                        window.__uanalyzeLastCsvText = t;
                                        pushDownload({href:url, download:window.__uanalyzeLastCsvFilename || '', source:'blob.text', type:obj.type || '', size:obj.size || 0});
                                    }
                                }).catch(e => {
                                    window.__uanalyzeBlobTexts[url] = {...meta, error:String(e), ts:Date.now()};
                                });
                            }
                        } catch(e) {}
                        return url;
                    };

                    const origAnchorClick = HTMLAnchorElement.prototype.click;
                    HTMLAnchorElement.prototype.click = function() {
                        try {
                            const href = this.href || this.getAttribute('href') || '';
                            const download = this.download || this.getAttribute('download') || '';
                            if (download) window.__uanalyzeLastCsvFilename = download;
                            pushDownload({href, download, source:'HTMLAnchorElement.click'});
                            if (href.startsWith('data:')) {
                                const text = decodeDataUrl(href);
                                if (looksCsvText(text)) window.__uanalyzeLastCsvText = text;
                            } else if (href.startsWith('blob:')) {
                                setTimeout(async () => {
                                    try {
                                        const resp = await fetch(href);
                                        const text = await resp.text();
                                        window.__uanalyzeBlobTexts[href] = {text, ts:Date.now(), source:'anchor.blob.fetch'};
                                        if (looksCsvText(text)) window.__uanalyzeLastCsvText = text;
                                    } catch(e) {}
                                }, 0);
                            }
                        } catch(e) {}
                        return origAnchorClick.apply(this, arguments);
                    };

                    const origSetAttribute = Element.prototype.setAttribute;
                    Element.prototype.setAttribute = function(name, value) {
                        try {
                            if (this && this.tagName === 'A') {
                                const n = String(name || '').toLowerCase();
                                if (n === 'download') window.__uanalyzeLastCsvFilename = String(value || '');
                            }
                        } catch(e) {}
                        return origSetAttribute.apply(this, arguments);
                    };

                    const origAppendChild = Node.prototype.appendChild;
                    Node.prototype.appendChild = function(child) {
                        try {
                            if (child && child.tagName === 'A') {
                                const href = child.href || child.getAttribute('href') || '';
                                const download = child.download || child.getAttribute('download') || '';
                                if (download) window.__uanalyzeLastCsvFilename = download;
                                if (href || download) pushDownload({href, download, source:'Node.appendChild(a)'});
                            }
                        } catch(e) {}
                        return origAppendChild.apply(this, arguments);
                    };

                    document.addEventListener('click', function(ev) {
                        try {
                            const a = ev.target && ev.target.closest ? ev.target.closest('a') : null;
                            if (!a) return;
                            const href = a.href || a.getAttribute('href') || '';
                            const download = a.download || a.getAttribute('download') || '';
                            if (download) window.__uanalyzeLastCsvFilename = download;
                            if (href || download) pushDownload({href, download, source:'document.click.capture'});
                        } catch(e) {}
                    }, true);
                }
                return {ok:true, patched:true, version:'downloadfix-v2'};
            }
            """
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:220]}


def click_csv_menu_item_by_js_capture(page) -> dict:
    """只點「下載為 CSV 檔」。不用顯示數值、不解析圖片。"""
    try:
        return page.evaluate(
            r"""
            () => {
                window.__uanalyzeDownloads = [];
                window.__uanalyzeBlobTexts = {};
                window.__uanalyzeLastCsvText = '';
                function txt(el){ return (el.innerText || el.textContent || '').trim(); }
                const items = Array.from(document.querySelectorAll('.highcharts-menu-item'));
                const menuItems = items.map((el, index) => txt(el));
                const target = items.find(el => {
                    const t = txt(el);
                    const u = t.toUpperCase().replace(/\s+/g,'');
                    return u.includes('CSV') && (u.includes('DOWNLOAD') || t.includes('下載') || t.includes('匯出'));
                });
                if (!target) return {ok:false, error:'csv menu item not found by js', menuItems};
                try { target.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
                const r = target.getBoundingClientRect();
                const x = r.left + r.width / 2;
                const y = r.top + r.height / 2;
                const opts = {bubbles:true, cancelable:true, composed:true, view:window, clientX:x, clientY:y, button:0};
                const events = ['pointerover','pointerenter','mouseover','mouseenter','pointerdown','mousedown','pointerup','mouseup','click'];
                for (const name of events) {
                    try {
                        const Ev = name.startsWith('pointer') && window.PointerEvent ? PointerEvent : MouseEvent;
                        target.dispatchEvent(new Ev(name, opts));
                    } catch(e) {}
                }
                try { target.click(); } catch(e) {}
                return {ok:true, text:txt(target), rect:{top:r.top,left:r.left,width:r.width,height:r.height,bottom:r.bottom,right:r.right}, menuItems};
            }
            """
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:260]}


def read_captured_browser_download(page, timeout_ms: int = 12000) -> dict:
    """讀取剛剛 CSV 下載產生的文字。不依賴 Playwright download event。"""
    try:
        end = time.time() + timeout_ms / 1000
        last = None
        while time.time() < end:
            last = page.evaluate(
                r"""
                async () => {
                    const downloads = window.__uanalyzeDownloads || [];
                    const blobTexts = window.__uanalyzeBlobTexts || {};
                    const lastCsvText = window.__uanalyzeLastCsvText || '';
                    const lastCsvFilename = window.__uanalyzeLastCsvFilename || '';
                    if (lastCsvText && String(lastCsvText).trim()) {
                        return {ok:true, text:lastCsvText, filename:lastCsvFilename, method:'captured csv text from page hook', downloads};
                    }
                    const d = downloads.length ? downloads[downloads.length - 1] : null;
                    if (!d) return {ok:false, waiting:'no captured download yet', downloads:[]};
                    const href = d.href || '';
                    try {
                        if (href.startsWith('data:')) {
                            const comma = href.indexOf(',');
                            const meta = href.slice(5, comma);
                            const payload = href.slice(comma + 1);
                            let text = '';
                            if (meta.includes(';base64')) {
                                try { text = new TextDecoder('utf-8').decode(Uint8Array.from(atob(payload), c => c.charCodeAt(0))); }
                                catch(e) { text = atob(payload); }
                            } else {
                                text = decodeURIComponent(payload);
                            }
                            return {ok:true, text, filename:d.download || lastCsvFilename || '', method:'captured data url', download:d, downloads};
                        }
                        if (href.startsWith('blob:')) {
                            if (blobTexts[href] && blobTexts[href].text) {
                                return {ok:true, text:blobTexts[href].text, filename:d.download || lastCsvFilename || '', method:'captured blob text cache', download:d, downloads};
                            }
                            try {
                                const resp = await fetch(href);
                                const text = await resp.text();
                                if (text) return {ok:true, text, filename:d.download || lastCsvFilename || '', method:'captured blob fetch', download:d, downloads};
                            } catch(e) {
                                return {ok:false, waiting:'blob fetch failed', error:String(e), download:d, blobText:blobTexts[href] || null, downloads};
                            }
                            return {ok:false, waiting:'blob exists but text not ready', download:d, blobText:blobTexts[href] || null, downloads};
                        }
                        return {ok:false, waiting: href ? 'captured href is not data/blob' : 'captured download without href', download:d, downloads};
                    } catch(e) {
                        return {ok:false, error:String(e), download:d, downloads};
                    }
                }
                """
            )
            if isinstance(last, dict) and last.get("ok") and (last.get("text") or "").strip():
                return last
            page.wait_for_timeout(400)
        return last if isinstance(last, dict) else {"ok": False, "error": "no captured download result"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:260]}


def click_show_data_and_parse_table_multi(page, spec: dict, coord: dict, scroll_meta: dict, pre_click_meta=None, patch_meta=None) -> dict:
    """Highcharts 在 Streamlit Cloud headless 有時不會產生 Playwright download event。
    這個備援不下載檔案，而是點選單的「顯示數值」，讓 Highcharts 把資料表渲染到 DOM，
    再把 table 轉成 CSV。這比抓瀏覽器下載事件穩定。
    """
    try:
        # 先清掉上一張圖可能留下的資料表，避免解析到舊表。
        page.evaluate("""
        () => {
            document.querySelectorAll('.highcharts-data-table').forEach(el => el.remove());
        }
        """)
    except Exception:
        pass

    try:
        # 確保選單打開。
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
        except Exception:
            pass
        page.mouse.click(coord["x"], coord["y"])
        page.wait_for_timeout(700)
    except Exception as e:
        return {"ok": False, "error": "open menu for show data failed: " + str(e)[:220]}

    menu_items = []
    try:
        click_meta = page.evaluate(
            r"""
            () => {
                function txt(el){ return (el.innerText || el.textContent || '').trim(); }
                const items = Array.from(document.querySelectorAll('.highcharts-menu-item'));
                const menuItems = items.map((el, index) => ({index, text:txt(el)}));
                const target = items.find(el => {
                    const t = txt(el);
                    return t.includes('顯示數值') || t.toLowerCase().includes('view data') || t.toLowerCase().includes('show data');
                });
                if (!target) return {ok:false, error:'show data menu item not found', menuItems};
                const r = target.getBoundingClientRect();
                try { target.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
                const opts = {bubbles:true, cancelable:true, view:window, clientX:r.left+r.width/2, clientY:r.top+r.height/2};
                try { target.dispatchEvent(new MouseEvent('mouseover', opts)); } catch(e) {}
                try { target.dispatchEvent(new MouseEvent('mousedown', opts)); } catch(e) {}
                try { target.dispatchEvent(new MouseEvent('mouseup', opts)); } catch(e) {}
                try { target.dispatchEvent(new MouseEvent('click', opts)); } catch(e) {}
                try { target.click(); } catch(e) {}
                return {ok:true, text:txt(target), rect:{top:r.top,left:r.left,width:r.width,height:r.height,bottom:r.bottom,right:r.right}, menuItems};
            }
            """
        )
        if isinstance(click_meta, dict):
            menu_items = [x.get('text','') for x in click_meta.get('menuItems', []) if x.get('text')]
            if not click_meta.get('ok'):
                return {"ok": False, "error": click_meta.get("error") or "show data click failed", "menu_items": menu_items, "click_meta": click_meta}
    except Exception as e:
        return {"ok": False, "error": "show data JS click failed: " + str(e)[:260], "menu_items": menu_items}

    try:
        page.wait_for_timeout(1600)
    except Exception:
        pass

    try:
        parsed = page.evaluate(
            r"""
            (spec) => {
                const keyword = spec.keyword || spec.label || '';
                const matchKeywords = [keyword].concat(spec.match_keywords || []).filter(Boolean);
                const excludeKeywords = spec.exclude_keywords || [];
                function txt(el){ return (el.innerText || el.textContent || '').trim(); }
                function rect(el){ const r=el.getBoundingClientRect(); return {top:r.top,left:r.left,width:r.width,height:r.height,bottom:r.bottom,right:r.right,x:r.left+r.width/2,y:r.top+r.height/2}; }
                function esc(v){
                    if (v === null || v === undefined) return '';
                    const s = String(v).replace(/\r\n/g,'\n').replace(/\r/g,'\n').trim();
                    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
                    return s;
                }
                const tables = Array.from(document.querySelectorAll('.highcharts-data-table table, table'))
                    .map((table, index) => {
                        const text = txt(table);
                        const r = rect(table);
                        let score = 0;
                        for (const kw of matchKeywords) if (kw && text.includes(kw)) score += (kw === keyword ? 1000 : 220);
                        for (const ex of excludeKeywords) if (ex && text.includes(ex)) score -= 260;
                        if (table.closest('.highcharts-data-table')) score += 500;
                        if (text.length > 20) score += 50;
                        return {table, index, text:text.slice(0,360), rect:r, score};
                    })
                    .filter(x => x.text && x.score > 0)
                    .sort((a,b)=>b.score-a.score || b.text.length-a.text.length);
                const target = tables[0];
                if (!target) {
                    const all = Array.from(document.querySelectorAll('.highcharts-data-table table, table')).map((table,index)=>({index,text:txt(table).slice(0,240), rect:rect(table)}));
                    return {ok:false, error:'data table not found after show data', tables:all.slice(0,8)};
                }
                const rows = Array.from(target.table.querySelectorAll('tr')).map(tr =>
                    Array.from(tr.querySelectorAll('th,td')).map(cell => esc(txt(cell)))
                ).filter(row => row.length);
                if (!rows.length) return {ok:false, error:'data table has no rows', target:{score:target.score,text:target.text,rect:target.rect}};
                const csv = rows.map(row => row.join(',')).join('\n');
                return {ok:true, csv, method:'Highcharts show data table -> DOM table -> CSV', target:{score:target.score,text:target.text,rect:target.rect}, row_count:rows.length};
            }
            """,
            spec,
        )
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        if isinstance(parsed, dict) and parsed.get("ok") and (parsed.get("csv") or "").strip():
            return {
                "ok": True,
                "csv": parsed.get("csv") or "",
                "chart_title": spec.get("label") or spec.get("keyword"),
                "method": parsed.get("method") or "Highcharts show data table",
                "scroll_meta": scroll_meta,
                "pre_click_meta": pre_click_meta,
                "patch_meta": patch_meta,
                "coord": coord,
                "menu_items": menu_items,
                "table_meta": {k:v for k,v in parsed.items() if k != "csv"},
                "suggested_filename": "",
            }
        return {"ok": False, "error": (parsed or {}).get("error") if isinstance(parsed, dict) else "table parse failed", "menu_items": menu_items, "table_meta": parsed}
    except Exception as e:
        return {"ok": False, "error": "parse shown data table failed: " + str(e)[:260], "menu_items": menu_items}

def download_chart_csv_via_menu_multi(page, spec: dict) -> dict:
    scroll_meta = scroll_chart_section_into_view_multi(page, spec)
    pre_click_meta = None
    if spec.get("pre_click_text"):
        pre_click_meta = click_section_button_multi(page, spec, spec.get("pre_click_text"))
        scroll_meta = scroll_chart_section_into_view_multi(page, spec)

    # 關鍵修正：先在頁面內裝下載攔截器。Highcharts 常用 data/blob URL 觸發下載，
    # Streamlit Cloud + Headless Chromium 有時不會丟給 Playwright download event。
    patch_meta = install_browser_download_capture_patch(page)

    coord = find_chart_export_button_coord_multi(page, spec)
    if not coord.get("ok"):
        return {"ok": False, "error": "export button not found", "scroll_meta": scroll_meta, "pre_click_meta": pre_click_meta, "patch_meta": patch_meta, "coord": coord}
    try:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
        except Exception:
            pass
        page.mouse.click(coord["x"], coord["y"])
        page.wait_for_timeout(900)
    except Exception as e:
        return {"ok": False, "error": "click export button failed: " + str(e)[:220], "scroll_meta": scroll_meta, "pre_click_meta": pre_click_meta, "patch_meta": patch_meta, "coord": coord}

    menu_debug = []
    js_click_meta = click_csv_menu_item_by_js_capture(page)
    if isinstance(js_click_meta, dict):
        menu_debug.extend(js_click_meta.get("menuItems") or [])
    captured = read_captured_browser_download(page, timeout_ms=10000)
    if captured.get("ok") and (captured.get("text") or "").strip():
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return {
            "ok": True,
            "csv": captured.get("text") or "",
            "chart_title": spec.get("label") or spec.get("keyword"),
            "method": "JS menu click + captured Highcharts CSV",
            "scroll_meta": scroll_meta,
            "pre_click_meta": pre_click_meta,
            "patch_meta": patch_meta,
            "coord": coord,
            "menu_items": menu_debug,
            "js_click_meta": {k:v for k,v in js_click_meta.items() if k != "menuItems"} if isinstance(js_click_meta, dict) else js_click_meta,
            "captured_meta": {k:v for k,v in captured.items() if k != "text"},
            "suggested_filename": captured.get("filename") or "",
        }

    try:
        items = page.locator(".highcharts-menu-item")
        for i in range(items.count()):
            item = items.nth(i)
            try:
                txt = item.inner_text(timeout=1000).strip()
            except Exception:
                txt = ""
            if txt and txt not in menu_debug:
                menu_debug.append(txt)
            upper = txt.upper().replace(" ", "")
            if "CSV" in upper and ("DOWNLOAD" in upper or "下載" in txt or "匯出" in txt):
                with page.expect_download(timeout=18000) as download_info:
                    item.click(timeout=6000, force=True)
                download = download_info.value
                path = download.path()
                raw = Path(path).read_bytes() if path else b""
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return {"ok": True, "csv": decode_downloaded_bytes(raw), "chart_title": spec.get("label") or spec.get("keyword"), "method": "Export menu Download CSV force", "scroll_meta": scroll_meta, "pre_click_meta": pre_click_meta, "patch_meta": patch_meta, "coord": coord, "menu_items": menu_debug, "js_click_meta": js_click_meta, "captured_meta": {k:v for k,v in captured.items() if k != "text"}, "suggested_filename": download.suggested_filename}
    except Exception as e:
        menu_debug.append("force menu item path failed: " + str(e)[:220])

    for txt in ["Download CSV", "下載 CSV", "下載CSV", "下載為 CSV 檔"]:
        try:
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)
                page.mouse.click(coord["x"], coord["y"])
                page.wait_for_timeout(600)
            except Exception:
                pass
            loc = page.get_by_text(txt, exact=True).last
            if loc.count() > 0:
                install_browser_download_capture_patch(page)
                with page.expect_download(timeout=12000) as download_info:
                    loc.click(timeout=5000, force=True)
                download = download_info.value
                path = download.path()
                raw = Path(path).read_bytes() if path else b""
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return {"ok": True, "csv": decode_downloaded_bytes(raw), "chart_title": spec.get("label") or spec.get("keyword"), "method": f"text menu item {txt} force", "scroll_meta": scroll_meta, "pre_click_meta": pre_click_meta, "patch_meta": patch_meta, "coord": coord, "menu_items": menu_debug, "js_click_meta": js_click_meta, "captured_meta": {k:v for k,v in captured.items() if k != "text"}, "suggested_filename": download.suggested_filename}
        except Exception as e:
            menu_debug.append(f"text {txt} force failed: {str(e)[:140]}")
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return {"ok": False, "error": "CSV menu item not clicked/downloaded", "scroll_meta": scroll_meta, "pre_click_meta": pre_click_meta, "patch_meta": patch_meta, "coord": coord, "menu_items": menu_debug, "js_click_meta": js_click_meta, "captured_meta": {k:v for k,v in captured.items() if k != "text"}}


def get_chart_csv_multi(page, spec: dict) -> dict:
    dismiss_page_overlays(page)
    scroll_meta = scroll_chart_section_into_view_multi(page, spec)
    api_result = try_highcharts_csv_api_multi(page, spec)
    if api_result.get("ok") and (api_result.get("csv") or "").strip():
        api_result["scroll_meta"] = scroll_meta
        return api_result
    menu_result = download_chart_csv_via_menu_multi(page, spec)
    if menu_result.get("ok") and (menu_result.get("csv") or "").strip():
        menu_result["previous_api_result"] = {k: v for k, v in api_result.items() if k != "csv"}
        return menu_result
    return {"ok": False, "error": "chart CSV failed", "api_result": {k: v for k, v in api_result.items() if k != "csv"}, "menu_result": {k: v for k, v in menu_result.items() if k != "csv"}}


def build_second_block_combined_text(company_label: str, results: list) -> str:
    parts = ["# UAnalyze 第二區塊 CSV 擷取結果", "", f"- 公司：{company_label}", f"- 擷取時間：{human_now()}", f"- 成功：{sum(1 for r in results if r.get('ok'))}/{len(results)}", "", "---", ""]
    for idx, r in enumerate(results, start=1):
        spec = r.get("spec") or {}
        label = spec.get("label") or spec.get("keyword") or f"CSV {idx}"
        parts += [f"## {idx}. {label}", ""]
        if r.get("ok"):
            parts += [f"- 檔名：{spec.get('filename')}", f"- 擷取方式：{r.get('method') or ''}"]
            if r.get("suggested_filename"):
                parts.append(f"- 原始下載檔名：{r.get('suggested_filename')}")
            parts += ["", "```csv", r.get("csv") or "", "```"]
        else:
            parts += ["- 狀態：失敗", f"- 原因：{r.get('error') or 'unknown'}"]
        parts += ["", "---", ""]
    return "\n".join(parts)


def write_second_block_files(run_dir: Path, company_label: str, results: list, debug: dict):
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = run_dir / "second_block_csv"
    csv_dir.mkdir(exist_ok=True)
    manifest = []
    for result in results:
        spec = result.get("spec") or {}
        filename = spec.get("filename") or f"{safe_name(spec.get('label') or spec.get('key') or 'chart')}.csv"
        manifest.append({"key": spec.get("key"), "label": spec.get("label"), "filename": filename, "ok": bool(result.get("ok")), "method": result.get("method"), "error": result.get("error"), "suggested_filename": result.get("suggested_filename")})
        if result.get("ok") and (result.get("csv") or "").strip():
            (csv_dir / filename).write_text(result.get("csv") or "", encoding="utf-8-sig")
        else:
            (csv_dir / (Path(filename).stem + "_FAILED.json")).write_text(json.dumps({k: v for k, v in result.items() if k != "csv"}, ensure_ascii=False, indent=2), encoding="utf-8")
    combined_text = build_second_block_combined_text(company_label, results)
    (run_dir / "_SECOND_BLOCK_ALL_CSV.md").write_text(combined_text, encoding="utf-8")
    (run_dir / "second_block_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "debug_info.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    return combined_text, manifest


def display_second_block_results(run_dir: Path, company_label: str, results: list, debug: dict):
    combined_text, manifest = write_second_block_files(run_dir, company_label, results, debug)
    ok_count = sum(1 for r in results if r.get("ok"))
    total = len(results)
    if ok_count == total:
        st.success(f"第二區塊完成：{ok_count}/{total} 個 CSV 全部取得。")
    elif ok_count > 0:
        st.warning(f"第二區塊部分完成：{ok_count}/{total} 個 CSV 取得。失敗項目已放進診斷 ZIP。")
    else:
        st.error("第二區塊沒有成功取得 CSV。請下載診斷 ZIP。")
    copy_button(combined_text, "一鍵複製第二區塊全部 CSV")
    st.text_area("第二區塊全部 CSV / 診斷摘要", combined_text, height=520)
    st.download_button(label="下載第二區塊完整 ZIP", data=build_zip_bytes(run_dir), file_name=f"{run_dir.name}.zip", mime="application/zip")

    for idx, result in enumerate(results, start=1):
        spec = result.get("spec") or {}
        label = spec.get("label") or spec.get("keyword") or f"CSV {idx}"
        with st.expander(("✅ " if result.get("ok") else "❌ ") + label, expanded=False):
            if result.get("ok"):
                csv_text = result.get("csv") or ""
                copy_button(csv_text, f"一鍵複製：{label}")
                st.text_area(f"{label} CSV", csv_text, height=260, key=f"csv_area_{run_dir.name}_{idx}")
                st.download_button(label=f"下載 CSV：{label}", data=csv_text.encode("utf-8-sig"), file_name=spec.get("filename") or f"{safe_name(label)}.csv", mime="text/csv", key=f"download_csv_{run_dir.name}_{idx}")
            else:
                st.json({k: v for k, v in result.items() if k != "csv"})


def capture_second_block_csvs(page, company_label: str, run_dir: Path, debug: dict, progress=None, base_progress: int = 55, log_func=None, status_box=None):
    results = []
    total = len(SECOND_BLOCK_CHART_SPECS)
    for idx, spec in enumerate(SECOND_BLOCK_CHART_SPECS, start=1):
        if status_box:
            status_box.write(f"第二區塊 {idx}/{total}：{spec['label']}")
        if log_func:
            log_func(f"第二區塊 {idx}/{total}：{spec['label']}")
        result = get_chart_csv_multi(page, spec)
        result["spec"] = spec
        result["captured_at"] = human_now()
        results.append(result)
        try:
            (run_dir / f"second_block_{idx:02d}_{safe_name(spec.get('key'))}.png").write_bytes(page.screenshot(full_page=True))
        except Exception:
            pass
        if log_func:
            log_func(("完成：" if result.get("ok") else "失敗：") + spec["label"])
        if progress:
            progress.progress(min(98, base_progress + int(idx / total * (98 - base_progress))))
    debug["second_block_results_meta"] = [{k: v for k, v in r.items() if k != "csv"} for r in results]
    return results


def run_second_block_csvs_only(login_url: str, email: str, password: str, stock_code: str, wait_seconds: int, show_intermediate_images: bool):
    company_label = normalize_stock_code(stock_code)
    run_id = f"{now_stamp()}_{safe_name(company_label)}_second_block_csvs"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()
    logs = []

    def log(msg: str):
        line = f"[{human_now()}] {msg}"
        logs.append(line)
        log_box.text("\n".join(logs[-14:]))
        try:
            (run_dir / "run_log.txt").write_text("\n".join(logs), encoding="utf-8")
        except Exception:
            pass

    try:
        if not email or not password:
            st.error("請先在上方輸入 UAnalyze Email 和密碼。")
            st.stop()
        if not company_label:
            st.error("請先在上方輸入股票代號，只填數字，例如 3030。")
            st.stop()
        st.info("第二區塊獨立執行：登入一次、切換一次股票，接著一次下載全部指定 CSV。")
        install = ensure_playwright_chromium()
        if install["returncode"] != 0:
            st.error("Playwright Chromium 安裝 / 檢查失敗。")
            st.code(install["stdout"] + "\n" + install["stderr"])
            st.stop()
        from playwright.sync_api import sync_playwright
        debug = {"run_id": run_id, "company_label": company_label, "mode": "second_block_csvs_only", "chart_specs": SECOND_BLOCK_CHART_SPECS, "started_at": human_now()}
        with sync_playwright() as p:
            sys_chrome = install.get("system_chromium") or system_chromium_path()
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if sys_chrome:
                launch_kwargs["executable_path"] = sys_chrome
                log(f"使用系統 Chromium：{sys_chrome}")
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            page = context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(90000)

            status_box.write("登入 UAnalyze 中...")
            log("登入 UAnalyze")
            page.goto(login_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)
            blocker_actions = close_blockers(page)
            fill_result = fill_like_human(page, email, password)
            login_methods = click_login(page)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(wait_seconds * 1000)
            progress.progress(15)
            debug.update({"blocker_actions": blocker_actions, "fill_result": fill_result, "login_methods": login_methods, "login_title": page.title(), "login_url_after": page.url})
            (run_dir / "debug_login_text.txt").write_text(extract_body_text(page), encoding="utf-8")
            log(f"登入後：{page.title()} / {page.url}")
            if show_intermediate_images:
                try:
                    st.image(page.screenshot(full_page=True), caption="第二區塊：登入後截圖")
                except Exception:
                    pass

            status_box.write("開啟虎八速覽中...")
            log("開啟虎八速覽")
            huba_actions = click_huba_quick_view(page)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(7000)
            progress.progress(30)
            debug.update({"huba_actions": huba_actions, "huba_title": page.title(), "huba_url": page.url})
            (run_dir / "debug_huba_text.txt").write_text(extract_body_text(page), encoding="utf-8")
            log(f"虎八速覽：{page.title()} / {page.url}")

            status_box.write(f"切換股票代號：{company_label} ...")
            log(f"切換股票代號：{company_label}")
            stock_actions = switch_stock(page, company_label)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(8000)
            after_stock_text = extract_body_text(page)
            current_code_after_switch = detect_current_stock_code(after_stock_text)
            debug.update({"stock_actions": stock_actions, "after_stock_title": page.title(), "after_stock_url": page.url, "current_code_after_switch": current_code_after_switch})
            (run_dir / "debug_after_stock_text.txt").write_text(after_stock_text, encoding="utf-8")
            try:
                (run_dir / "after_stock_screenshot.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            progress.progress(45)
            log(f"切換股票後：{page.title()} / {page.url} / current={current_code_after_switch or 'unknown'}")
            if current_code_after_switch and current_code_after_switch != company_label:
                st.error(f"股票代號沒有成功切換：目前仍是 {current_code_after_switch}，目標是 {company_label}。已停止抓 CSV，避免抓錯公司。")
                st.download_button(label="下載第二區塊切換失敗診斷 ZIP", data=build_zip_bytes(run_dir), file_name=f"{run_id}_switch_failed.zip", mime="application/zip")
                browser.close()
                st.stop()
            elif not current_code_after_switch:
                st.warning("無法從頁面文字確認目前股票代號，仍會繼續抓 CSV；若結果不是目標股票，請下載 ZIP 查看 after_stock_screenshot.png。")

            results = capture_second_block_csvs(page, company_label, run_dir, debug, progress=progress, base_progress=48, log_func=log, status_box=status_box)
            try:
                (run_dir / "second_block_final_screenshot.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            browser.close()
            debug["finished_at"] = human_now()
            progress.progress(100)
            status_box.write("第二區塊完成。")
            log("第二區塊完成")
            display_second_block_results(run_dir, company_label, results, debug)
            return
    except Exception as e:
        st.error("第二區塊獨立流程失敗。")
        st.exception(e)
        try:
            (run_dir / "error.txt").write_text(str(e), encoding="utf-8")
        except Exception:
            pass
        if run_dir.exists() and any(run_dir.iterdir()):
            st.download_button(label="下載第二區塊暫存 ZIP", data=build_zip_bytes(run_dir), file_name=f"{run_id}_partial.zip", mime="application/zip")


# -----------------------------
# Page UI
# -----------------------------

st.title("UAnalyze 產業情報小助理：v2 測試版 multi-csv tablefix")
st.caption("第一區塊維持原本穩定爬蟲；第二區塊可獨立一次下載多張圖表 CSV。若下載事件抓不到，會改用「顯示數值」資料表轉 CSV。")

with st.expander("登入與爬蟲設定", expanded=True):
    login_url = st.text_input("UAnalyze 登入頁網址", value="https://pro.uanalyze.com.tw/login-page")
    email = st.text_input("UAnalyze Email")
    password = st.text_input("UAnalyze 密碼", type="password")

    stock_code = st.text_input("股票代號（只填數字，例如 3030）", value="3030")
    stock_code = normalize_stock_code(stock_code)

    selected_topics = st.multiselect("選擇要爬的欄位", TOPICS, default=TOPICS)

    col3, col4 = st.columns(2)
    with col3:
        wait_seconds = st.slider("登入後等待秒數", 5, 90, 25)
    with col4:
        topic_wait_seconds = st.slider("每個欄位點擊後等待秒數", 3, 60, 15)

    save_screenshots = st.checkbox("ZIP 內同時保存每個欄位截圖（較慢，不建議手機長時間爬時開）", value=False)
    show_intermediate_images = st.checkbox("頁面上顯示登入 / 切換公司截圖（較慢）", value=False)

st.divider()

# Show latest cached runs first, useful after app reconnects.
latest_runs = latest_run_dirs()
if latest_runs:
    with st.expander("最近完成 / 暫存結果", expanded=False):
        for run_dir in latest_runs:
            all_md_path = run_dir / "_ALL_CONTENT.md"
            if all_md_path.exists():
                all_md = all_md_path.read_text(encoding="utf-8")
                st.write(f"結果資料夾：`{run_dir.name}`")
                copy_button(all_md, f"一鍵複製 {run_dir.name}")
                st.download_button(
                    label=f"下載 ZIP：{run_dir.name}",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_dir.name}.zip",
                    mime="application/zip",
                    key=f"zip_{run_dir.name}",
                )

            rev_csv_path = run_dir / "revenue_tracking.csv"
            if rev_csv_path.exists() and rev_csv_path.read_text(encoding="utf-8").strip():
                rev_csv = rev_csv_path.read_text(encoding="utf-8")
                st.write(f"累計月營收 CSV：`{run_dir.name}`")
                copy_button(rev_csv, f"一鍵複製累計月營收 CSV：{run_dir.name}")
                st.download_button(
                    label=f"下載累計月營收 CSV：{run_dir.name}",
                    data=rev_csv.encode("utf-8-sig"),
                    file_name=f"{run_dir.name}_revenue_tracking.csv",
                    mime="text/csv",
                    key=f"rev_csv_{run_dir.name}",
                )


if st.button("開始長時間爬取產業情報欄位"):
    if not email or not password:
        st.error("請先輸入 Email 和密碼。")
        st.stop()
    if not stock_code:
        st.error("請先輸入股票代號，且只輸入數字，例如 3030。")
        st.stop()
    if not selected_topics:
        st.error("請至少選一個要爬的欄位。")
        st.stop()

    company_label = stock_code
    run_id = f"{now_stamp()}_{safe_name(company_label)}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    st.info("開始檢查 Playwright Chromium。第一次部署後可能需要 1～3 分鐘，之後會快很多。")

    install = ensure_playwright_chromium()
    if install["returncode"] != 0:
        st.error("Playwright Chromium 安裝失敗。")
        st.code(install["stdout"] + "\n" + install["stderr"])
        st.stop()

    st.success("Playwright Chromium 安裝 / 檢查完成。")

    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()
    logs = []

    def log(msg: str):
        line = f"[{human_now()}] {msg}"
        logs.append(line)
        log_box.text("\n".join(logs[-12:]))
        try:
            (run_dir / "run_log.txt").write_text("\n".join(logs), encoding="utf-8")
        except Exception:
            pass

    revenue_csv_text = ""
    revenue_markdown_text = ""
    revenue_debug_meta = {}

    try:
        from playwright.sync_api import sync_playwright

        topic_results = []
        screenshots_dir = run_dir / "screenshots"
        if save_screenshots:
            screenshots_dir.mkdir(exist_ok=True)

        debug = {
            "run_id": run_id,
            "company_label": company_label,
            "selected_topics": selected_topics,
            "started_at": human_now(),
        }

        with sync_playwright() as p:
            sys_chrome = install.get("system_chromium") or system_chromium_path()
            launch_kwargs = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            if sys_chrome:
                launch_kwargs["executable_path"] = sys_chrome
                log(f"使用系統 Chromium：{sys_chrome}")

            browser = p.chromium.launch(**launch_kwargs)

            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1440, "height": 1000},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

            page = context.new_page()
            page.set_default_timeout(60000)
            page.set_default_navigation_timeout(90000)

            log("登入 UAnalyze 中")
            status_box.write("登入 UAnalyze 中...")
            page.goto(login_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)

            blocker_actions = close_blockers(page)
            fill_result = fill_like_human(page, email, password)
            login_methods = click_login(page)

            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass

            page.wait_for_timeout(wait_seconds * 1000)

            login_title = page.title()
            login_url_after = page.url
            login_text = extract_body_text(page)
            debug.update({
                "blocker_actions": blocker_actions,
                "fill_result": fill_result,
                "login_methods": login_methods,
                "login_title": login_title,
                "login_url_after": login_url_after,
            })
            (run_dir / "debug_login_text.txt").write_text(login_text, encoding="utf-8")
            progress.progress(10)
            log(f"登入後：{login_title} / {login_url_after}")

            if show_intermediate_images:
                st.image(page.screenshot(full_page=True), caption="登入後截圖")

            log("開啟虎八速覽")
            status_box.write("開啟虎八速覽中...")
            huba_actions = click_huba_quick_view(page)

            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass

            page.wait_for_timeout(7000)

            huba_title = page.title()
            huba_url = page.url
            huba_text = extract_body_text(page)
            debug.update({
                "huba_actions": huba_actions,
                "huba_title": huba_title,
                "huba_url": huba_url,
            })
            (run_dir / "debug_huba_text.txt").write_text(huba_text, encoding="utf-8")
            progress.progress(20)
            log(f"虎八速覽：{huba_title} / {huba_url}")

            log(f"切換股票代號：{stock_code}")
            status_box.write(f"切換股票代號：{stock_code} ...")
            stock_actions = switch_stock(page, stock_code)

            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass

            page.wait_for_timeout(8000)

            after_stock_title = page.title()
            after_stock_url = page.url
            after_stock_text = extract_body_text(page)
            debug.update({
                "stock_actions": stock_actions,
                "after_stock_title": after_stock_title,
                "after_stock_url": after_stock_url,
            })
            (run_dir / "debug_after_stock_text.txt").write_text(after_stock_text, encoding="utf-8")
            current_code_after_switch = detect_current_stock_code(after_stock_text)
            debug["current_code_after_switch"] = current_code_after_switch
            try:
                after_stock_screenshot = page.screenshot(full_page=True)
                (run_dir / "after_stock_screenshot.png").write_bytes(after_stock_screenshot)
                if show_intermediate_images:
                    st.image(after_stock_screenshot, caption="切換股票後截圖")
            except Exception:
                pass

            progress.progress(30)
            log(f"切換股票後：{after_stock_title} / {after_stock_url} / current={current_code_after_switch or 'unknown'}")

            if current_code_after_switch and current_code_after_switch != stock_code:
                st.error(f"股票代號沒有成功切換：目前仍是 {current_code_after_switch}，目標是 {stock_code}。我已停止爬蟲，避免又爬到錯的公司。")
                st.download_button(
                    label="下載切換失敗診斷 ZIP",
                    data=build_zip_bytes(run_dir),
                    file_name=f"{run_id}_switch_failed.zip",
                    mime="application/zip",
                )
                browser.close()
                st.stop()
            elif not current_code_after_switch:
                st.warning("無法從頁面文字確認目前股票代號，仍會繼續爬；若結果不是目標股票，請下載 ZIP 查看 after_stock_screenshot.png。")

            total = len(selected_topics)

            for idx, topic in enumerate(selected_topics, start=1):
                status_box.write(f"處理欄位 {idx}/{total}：{topic}")
                log(f"處理欄位 {idx}/{total}：{topic}")

                actions = click_topic(page, topic)

                try:
                    page.wait_for_load_state("networkidle", timeout=25000)
                except Exception:
                    pass

                page.wait_for_timeout(topic_wait_seconds * 1000)

                topic_text = extract_body_text(page)
                topic_item = {
                    "topic": topic,
                    "actions": actions,
                    "text": topic_text,
                    "url": page.url,
                    "title": page.title(),
                    "captured_at": human_now(),
                }
                topic_results.append(topic_item)

                topic_md = build_topic_markdown(company_label, topic_item)
                (run_dir / f"{safe_name(topic)}.md").write_text(topic_md, encoding="utf-8")

                if save_screenshots:
                    try:
                        (screenshots_dir / f"{safe_name(topic)}.png").write_bytes(page.screenshot(full_page=True))
                    except Exception:
                        pass

                # Save partial all-content after each topic.
                write_run_files(run_dir, company_label, topic_results, page.title(), page.url, debug)

                progress_value = 30 + int(idx / total * 65)
                progress.progress(min(progress_value, 95))
                log(f"完成欄位：{topic}")

            # 第二區塊資料：沿用同一個已登入、已切換股票代號的頁面，不重新登入、不重新輸入股票代號。
            try:
                status_box.write("第二區塊：同一次頁面擷取累計月營收 CSV...")
                log("第二區塊：同一次頁面擷取累計月營收 CSV")
                csv_result = get_revenue_csv_with_scroll(page, REVENUE_CHART_KEYWORD)
                revenue_debug_meta = {k: v for k, v in csv_result.items() if k != "csv"}
                debug["revenue_csv_result_meta"] = revenue_debug_meta

                if csv_result.get("ok") and (csv_result.get("csv") or "").strip():
                    revenue_csv_text = csv_result.get("csv") or ""
                    revenue_markdown_text = build_revenue_csv_markdown(
                        company_label,
                        revenue_csv_text,
                        csv_result.get("chart_title") or REVENUE_CHART_KEYWORD,
                        page.title(),
                        page.url,
                        csv_result.get("method") or "Highcharts CSV",
                    )
                    write_revenue_run_files(run_dir, company_label, revenue_csv_text, revenue_markdown_text, debug)
                    log("第二區塊完成：累計月營收 CSV 已取得")
                else:
                    debug["revenue_csv_failed"] = revenue_debug_meta
                    (run_dir / "revenue_csv_failed.json").write_text(json.dumps(revenue_debug_meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    log("第二區塊未成功取得 CSV：" + str(revenue_debug_meta)[:180])
            except Exception as e:
                debug["revenue_csv_exception"] = str(e)
                try:
                    (run_dir / "revenue_csv_error.txt").write_text(str(e), encoding="utf-8")
                except Exception:
                    pass
                log("第二區塊發生錯誤：" + str(e)[:180])

            final_title = page.title()
            final_url = page.url
            browser.close()

        debug["finished_at"] = human_now()
        result_markdown = write_run_files(run_dir, company_label, topic_results, final_title, final_url, debug)
        if revenue_csv_text.strip():
            write_revenue_run_files(run_dir, company_label, revenue_csv_text, revenue_markdown_text, debug)

        progress.progress(100)
        status_box.write("完成。")
        log("全部完成")

        st.success("爬取完成。")

        after_text_for_hint = (run_dir / "debug_after_stock_text.txt").read_text(encoding="utf-8")
        current_for_hint = detect_current_stock_code(after_text_for_hint)
        if current_for_hint == stock_code:
            st.success(f"已確認切換到股票代號 {stock_code}。")
        else:
            st.warning("不確定是否成功切換股票。請下載 ZIP 查看 after_stock_screenshot.png。")

        st.subheader("全部爬蟲結果")
        copy_button(result_markdown, "一鍵複製全部爬蟲結果")
        st.text_area("全部結果 Markdown", result_markdown, height=560)

        st.download_button(
            label="下載 ZIP",
            data=build_zip_bytes(run_dir),
            file_name=f"{run_id}.zip",
            mime="application/zip",
        )

        st.download_button(
            label="下載 Markdown",
            data=result_markdown.encode("utf-8"),
            file_name=f"{run_id}.md",
            mime="text/markdown",
        )

        st.subheader("第二區塊：累計月營收追蹤 CSV")
        if revenue_csv_text.strip():
            st.success("已使用同一次登入、同一次股票切換的頁面取得累計月營收 CSV。")
            copy_button(revenue_csv_text, "一鍵複製累計月營收 CSV")
            st.text_area("累計月營收 CSV", revenue_csv_text, height=420)
            st.download_button(
                label="下載累計月營收 CSV",
                data=revenue_csv_text.encode("utf-8-sig"),
                file_name=f"{run_id}_revenue_tracking.csv",
                mime="text/csv",
            )
        else:
            st.warning("本次沒有成功取得累計月營收 CSV。請下載 ZIP，裡面會有 revenue_csv_failed.json 或 revenue_csv_error.txt 供診斷。")

    except Exception as e:
        st.error("爬取流程失敗。")
        st.exception(e)
        try:
            (run_dir / "error.txt").write_text(str(e), encoding="utf-8")
        except Exception:
            pass
        if run_dir.exists() and any(run_dir.iterdir()):
            st.download_button(
                label="下載目前暫存 ZIP",
                data=build_zip_bytes(run_dir),
                file_name=f"{run_id}_partial.zip",
                mime="application/zip",
            )

st.divider()
st.header("第二區塊：圖表 CSV 一次下載")
st.caption("可獨立執行：只登入一次、進虎八速覽、輸入一次股票代號，然後依序下載累計月營收、季 EPS、季營收、季毛利率、營收趨勢與利潤率季度、存貨銷售比、合約負債、存貨細項等 CSV；不會跑第一區塊的產業情報欄位。")

with st.expander("本次會下載的 CSV 清單", expanded=True):
    for i, spec in enumerate(SECOND_BLOCK_CHART_SPECS, start=1):
        note = "（會先點季度）" if spec.get("pre_click_text") else ""
        st.write(f"{i}. {spec['label']} {note}")

if st.button("只抓第二區塊：全部圖表 CSV", key="run_second_block_csvs_only"):
    run_second_block_csvs_only(login_url, email, password, stock_code, wait_seconds, show_intermediate_images)

latest_second_block = None
for rd in latest_run_dirs(limit=10):
    combined_path = rd / "_SECOND_BLOCK_ALL_CSV.md"
    if combined_path.exists() and combined_path.read_text(encoding="utf-8").strip():
        latest_second_block = (rd, combined_path.read_text(encoding="utf-8"))
        break

if latest_second_block:
    rd, combined_text = latest_second_block
    st.success(f"已找到最近一次第二區塊 CSV：{rd.name}")
    copy_button(combined_text, "一鍵複製最近一次第二區塊全部 CSV")
    st.text_area("最近一次第二區塊全部 CSV", combined_text, height=420)
    st.download_button(
        label="下載最近一次第二區塊完整 ZIP",
        data=build_zip_bytes(rd),
        file_name=f"{rd.name}.zip",
        mime="application/zip",
        key="download_latest_second_block_zip",
    )
else:
    st.info("目前還沒有第二區塊多圖表 CSV。可直接按上方「只抓第二區塊：全部圖表 CSV」獨立執行。")
