"""
嘉南藥理大學圖書館座位管理系統 - 自動登入 + 預約研究小間

使用方式：
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. cp env.example.txt .env，並填入你的學號、身分證末四碼、想預約的研究小間房號
    4. 執行 `python3 cnu_carrel_bot.py` 測試是否能成功登入與預約
    5. 確認沒問題後，用 cron 設定每天固定時間自動執行這支程式（見 README）

本程式設計成「執行一次就結束」，定時觸發交給 cron 負責，
這樣電腦不需要一直開著、也不用額外常駐一個 Python 程式在背景。

【重要】以下標記 TODO 的地方，是我還看不到網站實際渲染後 HTML 的部分，
需要你用瀏覽器開發者工具（F12 -> Elements）幫忙確認正確的選擇器，
確認方式我寫在每個 TODO 旁邊的說明裡。
"""

import os
import sys
import time
import logging
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv()

LOGIN_URL = "https://carrel.cnu.edu.tw/"
STUDENT_ID = os.getenv("CNU_STUDENT_ID")
ID_LAST4 = os.getenv("CNU_ID_LAST4")
ROOM_NUMBER = os.getenv("CNU_ROOM_NUMBER", "401")
DEBUG = os.getenv("CNU_DEBUG", "0") == "1"

MAX_CAPTCHA_RETRY = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("cnu_carrel_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def wait_until(condition_fn, timeout_ms=8000, interval_ms=200):
    """
    重複執行 condition_fn()，只要它回傳真值就馬上結束（不用傻等固定秒數）；
    如果一直不成立，最多等到 timeout_ms 為止。
    比起寫死 wait_for_timeout(1500)，這樣網路快的時候可以省下大半時間。
    """
    elapsed = 0
    while elapsed < timeout_ms:
        result = condition_fn()
        if result:
            return result
        time.sleep(interval_ms / 1000)
        elapsed += interval_ms
    return condition_fn()


def find_in_frames(page, build_locator):
    """
    這個網站可能用 iframe 把「側邊選單」跟「內容區」分開放，
    Playwright 預設只在最外層頁面找元素，抓不到 iframe 裡面的東西。
    這個函式會掃過主頁面 + 所有 iframe，回傳第一個「真的找得到」的 Locator。
    build_locator 是一個函式，輸入一個 frame，回傳這個 frame 上的 Locator。
    """
    for frame in page.frames:
        try:
            loc = build_locator(frame)
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


def login(page) -> bool:
    """登入系統，回傳是否成功"""
    # domcontentloaded 比 networkidle 快很多：只要 DOM 結構好了就繼續，
    # 不用等所有背景網路請求（例如廣告、分析、心跳）都安靜下來
    page.goto(LOGIN_URL, wait_until="domcontentloaded")

    for attempt in range(1, MAX_CAPTCHA_RETRY + 1):
        log.info(f"嘗試登入 第 {attempt} 次")

        page.fill("#tbUserID", STUDENT_ID)
        page.fill("#tbPassword", ID_LAST4)

        if DEBUG:
            actual_userid_len = len(page.locator("#tbUserID").input_value())
            actual_pwd_len = len(page.locator("#tbPassword").input_value())
            log.info(
                f"[除錯] 學號欄位目前長度={actual_userid_len}（應為 {len(STUDENT_ID or '')}）、"
                f"密碼欄位目前長度={actual_pwd_len}（應為 {len(ID_LAST4 or '')}）"
            )

        # 驗證碼不是圖片，是直接寫在 HTML 裡的文字節點，直接讀取即可，不需要 OCR
        captcha_text = page.locator("#captchaText").inner_text().strip()
        log.info(f"讀到的驗證碼: {captcha_text}")

        page.fill("#tbCaptcha", captcha_text)

        if DEBUG:
            shot_path = f"debug_before_submit_attempt{attempt}.png"
            page.screenshot(path=shot_path)
            log.info(f"[除錯] 已截圖存到 {shot_path}，送出登入前的畫面")

        page.click("#pbLogin")

        # 不用傻等固定秒數：改成每 150ms 檢查一次「登入後才會出現的功能選單」
        # 或「錯誤訊息」，哪個先出現就馬上處理，最多等 6 秒
        success_marker = page.locator("text=功能選單")
        error_marker = page.locator("#LabelStatus")

        def check():
            if success_marker.count() > 0:
                return "success"
            if error_marker.count() > 0:
                text = error_marker.inner_text().strip()
                if text:
                    return text
            return None

        result = wait_until(check, timeout_ms=6000, interval_ms=150)

        if result == "success":
            log.info("登入成功")
            return True

        error_text = result or "（未知錯誤，可能是頁面回應較慢）"
        log.warning(f"登入失敗：{error_text}，重新整理驗證碼後重試")

        refresh_btn = page.locator("i.captcha-refresh")
        if refresh_btn.count() > 0:
            refresh_btn.click()
            page.wait_for_timeout(400)

    log.error(f"連續 {MAX_CAPTCHA_RETRY} 次登入失敗，放棄")
    return False


def book_room(page) -> bool:
    """登入成功後，導覽到「按日借用研究小間」頁面，查詢當天空間並預約指定房間"""

    # 有些網站點擊「預約」後會跳出瀏覽器原生的確認視窗（confirm 對話框），
    # 這裡預先註冊，一律自動按下「確定」，避免程式卡住等不到人工點擊
    page.on("dialog", lambda dialog: dialog.accept())

    # 點擊左側選單「按日借用研究小間」（側邊選單目前確定是在主頁面上，不是 iframe）
    page.click("text=按日借用研究小間")

    def build_book_btn(frame):
        row = frame.locator("tr", has_text=ROOM_NUMBER)
        return row.locator(
            "input[value='預約'], button:has-text('預約'), a:has-text('預約')"
        ).first

    query_locator_fn = lambda f: f.locator("#btnSubmit")  # noqa: E731

    # 不用傻等固定秒數：輪詢直到「預約按鈕」或「查詢按鈕」其中一個出現
    book_btn_holder = {}
    query_btn_holder = {}

    def check_page_ready():
        bb = find_in_frames(page, build_book_btn)
        if bb is not None:
            book_btn_holder["btn"] = bb
            return True
        qb = find_in_frames(page, query_locator_fn)
        if qb is not None:
            query_btn_holder["btn"] = qb
            return True
        return False

    wait_until(check_page_ready, timeout_ms=6000, interval_ms=150)

    if DEBUG:
        log.info(f"[除錯] 點擊「按日借用研究小間」後，目前網址：{page.url}")
        log.info(f"[除錯] 目前頁面上共有 {len(page.frames)} 個 frame（含主頁面）")
        page.screenshot(path="debug_after_click_menu.png")
        log.info("[除錯] 已截圖存到 debug_after_click_menu.png")

    book_btn = book_btn_holder.get("btn")

    if book_btn is not None:
        log.info("房間列表已經在頁面上，跳過查詢步驟")
    else:
        log.info("頁面上還沒有房間列表，點擊「查詢可預約空間」")
        query_btn = query_btn_holder.get("btn") or find_in_frames(page, query_locator_fn)

        if query_btn is None:
            if DEBUG:
                page.screenshot(path="debug_query_button_click_failed.png")
                log.info("[除錯] 找不到查詢按鈕，已截圖存到 debug_query_button_click_failed.png")
            log.error("在主頁面及所有 iframe 裡都找不到查詢按鈕（#btnSubmit）")
            return False

        try:
            query_btn.click(timeout=8000)
        except PWTimeout:
            log.warning("一般點擊逾時，改用強制點擊（force click）再試一次")
            query_btn.click(timeout=6000, force=True)

        if DEBUG:
            page.screenshot(path="debug_after_query.png")
            log.info("[除錯] 已截圖存到 debug_after_query.png")

        log.info(f"尋找研究小間 {ROOM_NUMBER} 的預約按鈕")
        book_btn = wait_until(
            lambda: find_in_frames(page, build_book_btn), timeout_ms=6000, interval_ms=150
        )

    if book_btn is None:
        log.warning(f"查無房號 {ROOM_NUMBER} 的預約按鈕，可能該房間今天未開放或已被預約完")
        return False

    book_btn.click()

    # 這裡不能省：要確保「預約」這個網路請求真的送到伺服器、伺服器也回應了，
    # 才能關閉瀏覽器，不然可能請求還在半路上就被切斷，導致其實沒訂到房間
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PWTimeout:
        pass

    log.info(f"已送出房號 {ROOM_NUMBER} 的預約，請自行至系統確認結果")
    return True


def run_once():
    if not STUDENT_ID or not ID_LAST4:
        log.error("尚未在 .env 內設定 CNU_STUDENT_ID / CNU_ID_LAST4")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not DEBUG, slow_mo=300 if DEBUG else 0)
        context = browser.new_context()
        page = context.new_page()

        try:
            if login(page):
                book_room(page)
            else:
                log.error("因登入失敗，本次預約流程中止")
        except PWTimeout:
            log.exception("等待網頁元素逾時，可能是選擇器不正確，或網站改版")
        finally:
            browser.close()


if __name__ == "__main__":
    run_once()
