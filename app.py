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
# Page UI
# -----------------------------

st.title("UAnalyze 產業情報小助理：長時間爬蟲版（股票代號 Enter 修正版）")
st.caption("適合一次爬多個欄位。股票欄位只填數字；切換股票時會輸入代號後直接按 Enter，並檢查是否仍停在台泥。")

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

            final_title = page.title()
            final_url = page.url
            browser.close()

        debug["finished_at"] = human_now()
        result_markdown = write_run_files(run_dir, company_label, topic_results, final_title, final_url, debug)

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
