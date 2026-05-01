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
    last = {"ok": False, "error": "not started"}
    try:
        page.wait_for_timeout(2500)
    except Exception:
        pass
    for y in [0, 450, 900, 1350, 1800, 2300, 2800, 3400, 4000, 4700, 5400, 6200, 7000]:
        try:
            page.evaluate("(y) => window.scrollTo(0, y)", y)
            page.wait_for_timeout(1800)
        except Exception:
            pass
        last = find_revenue_highcharts_csv(page, keyword)
        if last.get("ok") and (last.get("csv") or "").strip():
            last["scroll_y"] = y
            return last
    return last


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
# Page UI
# -----------------------------

st.title("UAnalyze 產業情報小助理：v2 測試版")
st.caption("第一區塊維持原本穩定爬蟲；第二區塊可獨立抓累計月營收追蹤 CSV。兩個區塊共用同一組 Email、密碼、股票代號。")

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


# -----------------------------
# 第二區塊：多圖表 CSV 下載 helpers
# -----------------------------

CSV_TARGETS = [
    {
        "no": 1,
        "label": "累計月營收追蹤(實際營收vs法人vs我的預估)-新版",
        "keyword": "累計月營收追蹤",
        "file": "01_累計月營收追蹤.csv",
        "need_quarter": False,
    },
    {
        "no": 2,
        "label": "季EPS表現追蹤(實際VS法人共識)",
        "keyword": "季EPS表現追蹤",
        "file": "02_季EPS表現追蹤.csv",
        "need_quarter": False,
    },
    {
        "no": 3,
        "label": "季營收表現追蹤(實際VS法人共識)",
        "keyword": "季營收表現追蹤",
        "file": "03_季營收表現追蹤.csv",
        "need_quarter": False,
    },
    {
        "no": 4,
        "label": "季毛利率表現追蹤(實際VS法人共識)",
        "keyword": "季毛利率表現追蹤",
        "file": "04_季毛利率表現追蹤.csv",
        "need_quarter": False,
    },
    {
        "no": 5,
        "label": "營收趨勢與利潤率比較圖（季度）",
        "keyword": "營收趨勢與利潤率比較圖",
        "file": "05_營收趨勢與利潤率比較圖_季度.csv",
        "need_quarter": True,
    },
    {
        "no": 6,
        "label": "存貨銷售比(月)(每季更新一次)",
        "keyword": "存貨銷售比",
        "file": "06_存貨銷售比.csv",
        "need_quarter": False,
    },
    {
        "no": 7,
        "label": "合約負債VS佔營收比重VS季營收",
        "keyword": "合約負債",
        "file": "07_合約負債VS佔營收比重VS季營收.csv",
        "need_quarter": False,
    },
    {
        "no": 8,
        "label": "存貨細項(原始科目)",
        "keyword": "存貨細項",
        "file": "08_存貨細項_原始科目.csv",
        "need_quarter": False,
    },
]


def build_multi_csv_markdown(company_label: str, results: list, page_title: str, page_url: str) -> str:
    parts = [
        "# UAnalyze 第二區塊全部 CSV 擷取結果",
        "",
        f"- 公司：{company_label}",
        f"- 擷取時間：{human_now()}",
        f"- 頁面標題：{page_title}",
        f"- 頁面網址：{page_url}",
        "",
        "---",
        "",
    ]
    for r in results:
        parts.append(f"## {r.get('no')}. {r.get('label')}")
        parts.append("")
        parts.append(f"- 狀態：{'成功' if r.get('ok') else '失敗'}")
        if r.get("method"):
            parts.append(f"- 擷取方式：{r.get('method')}")
        if r.get("error"):
            parts.append(f"- 原因：{r.get('error')}")
        parts.append("")
        if r.get("csv"):
            parts.append(r.get("csv") or "")
            parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def dismiss_floating_ui(page):
    """把股票搜尋下拉、cookie 等會擋畫面的浮層關掉。"""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass
    try:
        if page.get_by_text("我知道了", exact=True).count() > 0:
            page.get_by_text("我知道了", exact=True).first.click(timeout=1500)
            page.wait_for_timeout(500)
    except Exception:
        pass


def scroll_to_chart_keyword(page, keyword: str) -> dict:
    try:
        return page.evaluate(
            r"""
            (keyword) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('body *'))
                    .filter(el => isVisible(el))
                    .map(el => ({el, text: norm(el.innerText || el.textContent || '')}))
                    .filter(x => x.text.includes(keyword));
                if (!nodes.length) return {ok:false, error:'keyword not found in page text'};
                nodes.sort((a,b) => a.text.length - b.text.length);
                const target = nodes[0].el;
                target.scrollIntoView({block:'center', inline:'nearest'});
                const r = target.getBoundingClientRect();
                return {ok:true, text:nodes[0].text.slice(0,180), x:r.left + r.width/2, y:r.top + r.height/2};
            }
            """,
            keyword,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}


def click_quarter_near_chart(page, keyword: str) -> dict:
    """營收趨勢與利潤率比較圖要先切『季度』。"""
    try:
        scroll_to_chart_keyword(page, keyword)
        page.wait_for_timeout(800)
        box = page.evaluate(
            r"""
            (keyword) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
                const titleEls = Array.from(document.querySelectorAll('body *'))
                    .filter(el => isVisible(el) && norm(el.innerText || el.textContent || '').includes(keyword));
                if (!titleEls.length) return null;
                titleEls.sort((a,b) => norm(a.innerText || a.textContent || '').length - norm(b.innerText || b.textContent || '').length);
                const tr = titleEls[0].getBoundingClientRect();
                const titleY = tr.top + tr.height/2;
                const buttons = Array.from(document.querySelectorAll('button, div, span, a'))
                    .filter(el => isVisible(el) && norm(el.innerText || el.textContent || '') === '季度')
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        return {x:r.left+r.width/2, y:r.top+r.height/2, dy:Math.abs((r.top+r.height/2)-titleY), text:norm(el.innerText || el.textContent || '')};
                    })
                    .filter(b => b.y > 0 && b.y < window.innerHeight);
                if (!buttons.length) return null;
                buttons.sort((a,b) => a.dy - b.dy);
                return buttons[0];
            }
            """,
            keyword,
        )
        if box:
            page.mouse.click(float(box["x"]), float(box["y"]))
            page.wait_for_timeout(2500)
            return {"ok": True, "clicked": box}
        return {"ok": False, "error": "quarter button not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def extract_csv_from_highcharts_global(page, keyword: str) -> dict:
    """先試 JS 直接取 Highcharts。若網站沒有掛 window.Highcharts，就會回 Highcharts not found。"""
    try:
        result = page.evaluate(
            r"""
            (keyword) => {
                const highchartsList = [];
                const pushHC = (v, name) => {
                    if (v && Array.isArray(v.charts) && v.charts.length) highchartsList.push({hc:v, name});
                };
                try { pushHC(window.Highcharts, 'window.Highcharts'); } catch(e) {}
                try {
                    for (const k of Object.keys(window)) {
                        try { pushHC(window[k], 'window.' + k); } catch(e) {}
                    }
                } catch(e) {}
                if (!highchartsList.length) return {ok:false, error:'Highcharts not found'};

                const escapeCell = (value) => {
                    if (value === null || value === undefined) return '';
                    const s = String(value);
                    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
                    return s;
                };

                for (const bundle of highchartsList) {
                    const hc = bundle.hc;
                    const charts = hc.charts.map((chart, index) => ({chart, index})).filter(x => x.chart);
                    const candidates = charts.map(x => {
                        const c = x.chart;
                        const title = (c.title && (c.title.textStr || c.title.element?.textContent)) || '';
                        const subtitle = (c.subtitle && (c.subtitle.textStr || c.subtitle.element?.textContent)) || '';
                        const renderText = (c.renderTo && (c.renderTo.innerText || c.renderTo.textContent)) || '';
                        return {index:x.index, title, subtitle, renderText, haystack:[title, subtitle, renderText].join('\n')};
                    });
                    const target = candidates.find(x => x.haystack.includes(keyword));
                    if (!target) continue;
                    const chart = hc.charts[target.index];
                    if (typeof chart.getCSV === 'function') {
                        const csv = chart.getCSV();
                        if (csv && csv.trim()) return {ok:true, csv, chart_title: target.title || target.subtitle || keyword, chart_index: target.index, method:bundle.name + '.getCSV'};
                    }
                    if (typeof chart.getDataRows === 'function') {
                        const rows = chart.getDataRows();
                        const csv = rows.map(row => row.map(escapeCell).join(',')).join('\n');
                        if (csv && csv.trim()) return {ok:true, csv, chart_title: target.title || target.subtitle || keyword, chart_index: target.index, method:bundle.name + '.getDataRows'};
                    }
                    return {ok:false, error:'target chart found but CSV API unavailable', chart_index: target.index, chart_title: target.title || keyword};
                }
                return {ok:false, error:'target chart not found in Highcharts', highcharts_count: highchartsList.length};
            }
            """,
            keyword,
        )
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "unexpected JS result"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def click_highcharts_csv_download(page, keyword: str, run_dir: Path, file_stem: str) -> dict:
    """用使用者手動會做的流程：找到圖表 → 點右側三條線 → 點 CSV。"""
    try:
        dismiss_floating_ui(page)
        scroll_info = scroll_to_chart_keyword(page, keyword)
        page.wait_for_timeout(1500)

        button_box = page.evaluate(
            r"""
            (keyword) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
                const containers = Array.from(document.querySelectorAll('.highcharts-container'))
                    .filter(el => isVisible(el))
                    .map((el, i) => {
                        const r = el.getBoundingClientRect();
                        return {el, i, text:norm(el.innerText || el.textContent || ''), x:r.left, y:r.top, w:r.width, h:r.height};
                    })
                    .filter(c => c.y < window.innerHeight && (c.y + c.h) > 0);

                let target = containers.find(c => c.text.includes(keyword));
                if (!target) {
                    const titleEls = Array.from(document.querySelectorAll('body *'))
                        .filter(el => isVisible(el) && norm(el.innerText || el.textContent || '').includes(keyword));
                    if (titleEls.length) {
                        titleEls.sort((a,b) => norm(a.innerText || a.textContent || '').length - norm(b.innerText || b.textContent || '').length);
                        const tr = titleEls[0].getBoundingClientRect();
                        const titleY = tr.top + tr.height / 2;
                        const below = containers.filter(c => c.y > titleY - 20);
                        if (below.length) {
                            below.sort((a,b) => a.y - b.y);
                            target = below[0];
                        }
                    }
                }
                if (!target) return {ok:false, error:'visible highcharts container not found'};

                const container = target.el;
                let btn = container.querySelector('.highcharts-contextbutton');
                if (!btn) btn = container.querySelector('g.highcharts-exporting-group .highcharts-button');
                if (!btn) btn = container.querySelector('.highcharts-button-symbol')?.closest('g');
                if (!btn) {
                    const svg = container.querySelector('svg');
                    if (svg) {
                        const cr = container.getBoundingClientRect();
                        // fallback：Highcharts 匯出按鈕通常在圖表右上方
                        return {ok:true, x:cr.right - 26, y:cr.top + 28, fallback:true, target_text:target.text.slice(0,120)};
                    }
                    return {ok:false, error:'export button not found', target_text:target.text.slice(0,120)};
                }
                const br = btn.getBoundingClientRect();
                return {ok:true, x:br.left + br.width/2, y:br.top + br.height/2, target_text:target.text.slice(0,120)};
            }
            """,
            keyword,
        )
        if not button_box or not button_box.get("ok"):
            return {"ok": False, "error": "export button not found", "scroll": scroll_info, "detail": button_box}

        page.mouse.click(float(button_box["x"]), float(button_box["y"]))
        page.wait_for_timeout(900)

        item_box = page.evaluate(
            r"""
            () => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
                const items = Array.from(document.querySelectorAll('.highcharts-menu-item, li, div, span'))
                    .filter(el => isVisible(el))
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        return {el, text:norm(el.innerText || el.textContent || ''), x:r.left+r.width/2, y:r.top+r.height/2, w:r.width, h:r.height};
                    })
                    .filter(x => x.text && x.text.length < 80 && /CSV/i.test(x.text));
                if (!items.length) return null;
                items.sort((a,b) => a.text.length - b.text.length);
                const it = items[0];
                return {x:it.x, y:it.y, text:it.text};
            }
            """
        )
        if not item_box:
            return {"ok": False, "error": "CSV menu item not found", "button": button_box}

        try:
            with page.expect_download(timeout=20000) as download_info:
                page.mouse.click(float(item_box["x"]), float(item_box["y"]))
            download = download_info.value
            out_path = run_dir / f"{safe_name(file_stem)}_downloaded.csv"
            download.save_as(str(out_path))
            csv_text = out_path.read_text(encoding="utf-8-sig", errors="ignore")
            if not csv_text.strip():
                csv_text = out_path.read_text(encoding="utf-8", errors="ignore")
            if csv_text.strip():
                return {"ok": True, "csv": csv_text, "method": "Highcharts export menu download CSV", "menu_item": item_box, "button": button_box}
            return {"ok": False, "error": "downloaded CSV empty", "menu_item": item_box, "path": str(out_path)}
        except Exception as e:
            return {"ok": False, "error": "download event failed: " + str(e), "menu_item": item_box, "button": button_box}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_chart_csv_best_effort(page, spec: dict, run_dir: Path) -> dict:
    keyword = spec.get("keyword") or spec.get("label")
    dismiss_floating_ui(page)
    if spec.get("need_quarter"):
        q = click_quarter_near_chart(page, keyword)
    else:
        q = None

    # 先用最乾淨的 JS 取值；失敗再走真的下載 CSV 菜單。
    for y in [0, 550, 1100, 1650, 2200, 2800, 3400, 4200, 5000, 5900, 6800, 7800, 9000, 10300, 11800]:
        try:
            page.evaluate("(y) => window.scrollTo(0, y)", y)
            page.wait_for_timeout(900)
        except Exception:
            pass
        js_result = extract_csv_from_highcharts_global(page, keyword)
        if js_result.get("ok") and (js_result.get("csv") or "").strip():
            js_result.update({"scroll_y": y, "quarter_click": q})
            return js_result

    menu_result = click_highcharts_csv_download(page, keyword, run_dir, f"{spec.get('no')}_{spec.get('keyword')}")
    menu_result["quarter_click"] = q
    return menu_result


def write_multi_csv_files(run_dir: Path, company_label: str, results: list, markdown_text: str, debug: dict):
    csv_dir = run_dir / "second_block_csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        meta = {k: v for k, v in r.items() if k != "csv"}
        (run_dir / f"{int(r.get('no', 0)):02d}_{safe_name(r.get('label'))}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if r.get("ok") and (r.get("csv") or "").strip():
            (csv_dir / r.get("file", f"{r.get('no')}.csv")).write_text(r.get("csv") or "", encoding="utf-8-sig")
    (run_dir / "second_block_all.md").write_text(markdown_text or "", encoding="utf-8")
    (run_dir / "debug_info.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")


def run_second_block_all_csv(login_url: str, email: str, password: str, stock_code: str, wait_seconds: int, show_intermediate_images: bool):
    """第二區塊獨立流程：登入一次、切換一次股票，連續抓 8 個 CSV。"""
    company_label = normalize_stock_code(stock_code)
    run_id = f"{now_stamp()}_{safe_name(company_label)}_second_block_csv"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    progress = st.progress(0)
    status_box = st.empty()
    log_box = st.empty()
    logs = []

    def log(msg: str):
        line = f"[{human_now()}] {msg}"
        logs.append(line)
        log_box.text("\n".join(logs[-16:]))
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

        st.info("第二區塊獨立執行：登入一次、切換一次股票，接著依序下載 8 個指定 CSV。")
        install = ensure_playwright_chromium()
        if install["returncode"] != 0:
            st.error("Playwright Chromium 安裝 / 檢查失敗。")
            st.code(install["stdout"] + "\n" + install["stderr"])
            st.stop()

        from playwright.sync_api import sync_playwright

        debug = {
            "run_id": run_id,
            "company_label": company_label,
            "mode": "second_block_all_csv_export_menu",
            "targets": CSV_TARGETS,
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
            progress.progress(15)
            debug.update({
                "blocker_actions": blocker_actions,
                "fill_result": fill_result,
                "login_methods": login_methods,
                "login_title": page.title(),
                "login_url_after": page.url,
            })
            (run_dir / "debug_login_text.txt").write_text(extract_body_text(page), encoding="utf-8")
            log(f"登入後：{page.title()} / {page.url}")

            status_box.write("開啟虎八速覽中...")
            log("開啟虎八速覽")
            huba_actions = click_huba_quick_view(page)
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(7000)
            progress.progress(28)
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
            dismiss_floating_ui(page)
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
            progress.progress(38)
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

            results = []
            total = len(CSV_TARGETS)
            for idx, spec in enumerate(CSV_TARGETS, start=1):
                status_box.write(f"第二區塊 {idx}/{total}：{spec['label']}")
                log(f"第二區塊 {idx}/{total}：{spec['label']}")
                result = get_chart_csv_best_effort(page, spec, run_dir)
                result.update({
                    "no": spec["no"],
                    "label": spec["label"],
                    "keyword": spec["keyword"],
                    "file": spec["file"],
                })
                results.append(result)
                if result.get("ok"):
                    log(f"成功：{spec['label']} / {result.get('method')}")
                else:
                    log(f"失敗：{spec['label']} / {result.get('error')}")
                    try:
                        (run_dir / f"{spec['no']:02d}_{safe_name(spec['label'])}_failed.png").write_bytes(page.screenshot(full_page=True))
                    except Exception:
                        pass
                progress.progress(38 + int(58 * idx / total))
                page.wait_for_timeout(1000)

            md_text = build_multi_csv_markdown(company_label, results, page.title(), page.url)
            debug["results_meta"] = [{k: v for k, v in r.items() if k != "csv"} for r in results]
            write_multi_csv_files(run_dir, company_label, results, md_text, debug)
            try:
                (run_dir / "final_screenshot.png").write_bytes(page.screenshot(full_page=True))
            except Exception:
                pass
            browser.close()

            success_count = sum(1 for r in results if r.get("ok") and (r.get("csv") or "").strip())
            progress.progress(100)
            status_box.write(f"第二區塊完成：成功 {success_count}/{total}。")
            if success_count == total:
                st.success(f"第二區塊完成：8 個 CSV 全部成功。")
            elif success_count > 0:
                st.warning(f"第二區塊完成：成功 {success_count}/{total}，其餘請看下方失敗原因。")
            else:
                st.error("第二區塊完成：8 個 CSV 都沒有成功下載。")

            copy_button(md_text, "一鍵複製第二區塊全部 CSV 結果")
            st.text_area("第二區塊全部 CSV 結果", md_text, height=520)

            for r in results:
                icon = "✅" if r.get("ok") else "❌"
                with st.expander(f"{icon} {r.get('no')}. {r.get('label')}", expanded=not r.get("ok")):
                    st.write(f"狀態：{'成功' if r.get('ok') else '失敗'}")
                    if r.get("method"):
                        st.write(f"擷取方式：{r.get('method')}")
                    if r.get("error"):
                        st.write(f"原因：{r.get('error')}")
                    if r.get("csv"):
                        copy_button(r.get("csv"), f"一鍵複製：{r.get('label')}")
                        st.text_area(f"CSV：{r.get('label')}", r.get("csv"), height=260, key=f"csv_area_{run_id}_{r.get('no')}")
                        st.download_button(
                            label=f"下載 CSV：{r.get('label')}",
                            data=(r.get("csv") or "").encode("utf-8-sig"),
                            file_name=r.get("file") or f"{r.get('no')}.csv",
                            mime="text/csv",
                            key=f"csv_dl_{run_id}_{r.get('no')}",
                        )

            st.download_button(
                label="下載第二區塊完整 ZIP",
                data=build_zip_bytes(run_dir),
                file_name=f"{run_id}.zip",
                mime="application/zip",
            )

    except Exception as e:
        st.error("第二區塊全部 CSV 流程失敗。")
        st.exception(e)
        try:
            (run_dir / "run_error.txt").write_text(str(e), encoding="utf-8")
            st.download_button(
                label="下載第二區塊暫存 ZIP",
                data=build_zip_bytes(run_dir),
                file_name=f"{run_id}_partial.zip",
                mime="application/zip",
            )
        except Exception:
            pass


st.divider()
st.header("第二區塊：一次下載全部指定 CSV")
st.caption("不動第一區塊。這裡會獨立登入一次、切換一次股票，然後依序抓你指定的 8 個圖表 CSV；其中『營收趨勢與利潤率比較圖』會先切到季度。")

if st.button("第二區塊：一次抓 8 個 CSV", key="run_second_block_all_csv"):
    run_second_block_all_csv(login_url, email, password, stock_code, wait_seconds, show_intermediate_images)

latest_second_block = None
for rd in latest_run_dirs(limit=10):
    md_path = rd / "second_block_all.md"
    if md_path.exists() and md_path.read_text(encoding="utf-8").strip():
        latest_second_block = (rd, md_path.read_text(encoding="utf-8"))
        break

if latest_second_block:
    rd, md_text = latest_second_block
    st.success(f"已找到最近一次第二區塊結果：{rd.name}")
    copy_button(md_text, "一鍵複製最近一次第二區塊全部 CSV 結果")
    st.text_area("最近一次第二區塊全部 CSV", md_text, height=520)
    st.download_button(
        label="下載最近一次第二區塊完整 ZIP",
        data=build_zip_bytes(rd),
        file_name=f"{rd.name}.zip",
        mime="application/zip",
        key="download_latest_second_block_zip",
    )
else:
    st.info("目前還沒有第二區塊全部 CSV 結果。可直接按上方按鈕執行。")
