"""
Core buff logic — chuyển thể từ buff.py của TIENDEV, không dùng cookie/UA
từ config. Session được khởi tạo tinh gọn, tự lấy captcha + form.

Toàn bộ hàm ở đây đều dùng chung requests.Session, an toàn để bọc FastAPI.
"""
from __future__ import annotations

import base64
import html
import json
import re
import time
import urllib.parse
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE = "https://zefoy.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": DEFAULT_UA,
}

AJAX_HEADERS = {
    "accept": "*/*",
    "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": BASE,
    "referer": BASE + "/",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": DEFAULT_UA,
    "x-requested-with": "XMLHttpRequest",
}


def new_session() -> requests.Session:
    """Tạo session sạch, tự lấy PHPSESSID từ Zefoy — không cần cookie ngoài."""
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    try:
        s.get(BASE + "/", timeout=30)
    except Exception:
        pass
    return s


# ────────── decode / parse helpers (từ buff.py) ──────────
def decode_zefoy_response(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text

    def _try(val: str) -> str:
        try:
            dec = base64.b64decode(urllib.parse.unquote(val[::-1])).decode("utf-8")
            if "<" in dec or "{" in dec or "div" in dec:
                return dec
        except Exception:
            pass
        try:
            dec = base64.b64decode(val).decode("utf-8")
            if "<" in dec or "{" in dec:
                return dec
        except Exception:
            pass
        return val

    decoded = _try(text)
    if decoded != text:
        try:
            data = json.loads(decoded)
            if isinstance(data, dict) and "html" in data:
                return _try(data["html"])
        except Exception:
            pass
        return decoded
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "html" in data:
            return _try(data["html"])
    except Exception:
        pass
    return text


def clean_html_text(html_content: str) -> str:
    return BeautifulSoup(html_content or "", "html.parser").get_text(separator=" ").strip()


def extract_cooldown_seconds(decoded: str) -> tuple[int, str]:
    soup = BeautifulSoup(decoded or "", "html.parser")
    tag = soup.find(id="login-countdown") or soup.find(class_=re.compile(r"countdown"))
    text_clean = clean_html_text(decoded)
    countdown_text = tag.text.strip() if tag else text_clean

    m_min = re.search(r"(\d+)\s*minute", countdown_text, re.I)
    m_sec = re.search(r"(\d+)\s*second", countdown_text, re.I)
    if m_min or m_sec:
        mins = int(m_min.group(1)) if m_min else 0
        secs = int(m_sec.group(1)) if m_sec else 0
        total = mins * 60 + secs
        if total > 0:
            return total, f"Please wait {mins} minute(s) {secs} second(s)"

    for pat in (
        r"var\s+ltm\s*=\s*(\d+)",
        r"ltm\s*=\s*(\d+)",
        r"ltimer\s*\(\s*(\d+)",
        r"timer\s*\(\s*(\d+)",
        r"startTimer\s*\(\s*(\d+)",
        r"var\s+time\s*=\s*(\d+)",
        r"var\s+timeleft\s*=\s*(\d+)",
        r"var\s+c\s*=\s*(\d+)",
        r"var\s+k\s*=\s*(\d+)",
        r"seconds\s*=\s*(\d+)",
    ):
        m = re.search(pat, decoded or "", re.I)
        if m:
            secs = int(m.group(1))
            if secs > 0:
                return secs, f"Please wait {secs // 60} minute(s) {secs % 60} second(s)"

    low = text_clean.lower()
    if "checking timer" in low or "please wait" in low:
        return 120, "Checking Timer... (mặc định 120s)"
    return 0, ""


# ────────── captcha ──────────
def get_captcha(session: requests.Session) -> tuple[str | None, dict, bytes | None]:
    """Trả về (captcha_url, form_data, image_bytes). Nếu đã đăng nhập trả (None, {}, None)."""
    t = str(int(time.time()))
    r = session.get(BASE + "/", params={"getcapthca": t}, timeout=30)
    doc = decode_zefoy_response(r.text)
    soup = BeautifulSoup(doc, "html.parser")

    img = soup.find("img", id="captcha-img") or soup.find("img", src=re.compile(r"_CAPTCHA"))
    src = img.get("src") if img else None
    if not src:
        m = re.search(r'src="([^"]*_CAPTCHA=[^"]*)"', doc)
        if m:
            src = m.group(1)
    if not src:
        # có thể đã đăng nhập
        check = session.get(BASE + "/", timeout=30).text
        if "colsmenu" in check or "t-followers-button" in check or "t-hearts-button" in check:
            return None, {}, None
        return None, {}, None

    src = html.unescape(src)
    if not src.startswith("http"):
        src = BASE + src

    form_data: dict[str, str] = {}
    form = soup.find("form")
    if form:
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

    try:
        img_bytes = session.get(src, timeout=30).content
    except Exception:
        img_bytes = None
    return src, form_data, img_bytes


def submit_captcha(session: requests.Session, answer: str, form_data: dict) -> bool:
    """Gửi mã captcha. True nếu vào được trang chủ có menu."""
    data = dict(form_data or {})
    data["captchalogin"] = (answer or "").strip().lower()
    resp = session.post(BASE + "/", data=data, timeout=30)
    if "Captcha code is incorrect" in resp.text or "zbcd" in resp.text:
        return False
    check = session.get(BASE + "/", timeout=30).text
    return any(k in check for k in ("t-followers-button", "t-hearts-button", "colsmenu"))


# ────────── services ──────────
def get_services(session: requests.Session) -> tuple[list[dict], str]:
    r = session.get(BASE + "/", timeout=30)
    doc = r.text
    soup = BeautifulSoup(doc, "html.parser")
    cards = soup.find_all("div", class_="colsmenu")
    out = []
    for card in cards:
        title_tag = card.find("h5", class_="card-title")
        if not title_tag:
            continue
        btn = card.find("button")
        if not btn:
            continue
        is_active = "disabled" not in btn.attrs
        btn_class = ""
        for cls in btn.get("class", []):
            if cls.startswith("t-") and cls.endswith("-button"):
                btn_class = cls
                break
        status_tag = card.find(class_="badge") or card.find("small")
        status_text = status_tag.text.strip() if status_tag else ("ON" if is_active else "OFF")
        out.append({
            "name": title_tag.text.strip(),
            "active": is_active,
            "status": status_text,
            "btn_class": btn_class,
            "menu_class": btn_class.replace("-button", "-menu") if btn_class else "",
        })
    return out, doc


def get_service_form(home_html: str, menu_class: str) -> dict | None:
    soup = BeautifulSoup(home_html or "", "html.parser")
    menu_div = soup.find("div", class_=menu_class) or soup.find(class_=re.compile(menu_class or ""))
    if not menu_div:
        return None
    form = menu_div.find("form")
    if not form:
        return None
    action = form.get("action")
    inp = form.find("input", type="search") or form.find("input", class_="form-control")
    input_name = inp.get("name") if inp else None
    if not input_name:
        for i in form.find_all("input"):
            if i.get("type", "text").lower() in ("search", "text") and i.get("name"):
                input_name = i.get("name")
                break
    return {"action": action, "input_name": input_name}


# ────────── buff loop step ──────────
def do_buff_once(
    session: requests.Session,
    action_url: str,
    input_name: str,
    video_url: str,
) -> dict[str, Any]:
    """Chạy 1 lượt buff. Trả về dict {status, message, cooldown, amount, kind}."""
    search_data = {input_name: video_url}
    decoded = ""
    total_wait = 0
    countdown_text = ""
    form = None
    submit_btn = None
    for attempt in range(3):
        r = session.post(action_url, headers=AJAX_HEADERS, data=search_data, timeout=45)
        decoded = decode_zefoy_response(r.text)
        soup = BeautifulSoup(decoded, "html.parser")
        total_wait, countdown_text = extract_cooldown_seconds(decoded)
        form = soup.find("form")
        submit_btn = soup.find("button", class_=re.compile(r"wbutton|btn"))
        if (total_wait > 0 and "mặc định" not in countdown_text.lower()) or form or submit_btn:
            break
        time.sleep(2.0)

    if total_wait > 0:
        return {"status": "cooldown", "cooldown": total_wait, "message": countdown_text}

    if not (form or submit_btn):
        return {
            "status": "error",
            "message": clean_html_text(decoded) or "Không tìm thấy form submit",
            "raw": decoded[:800],
        }

    target_form = form if form else submit_btn.find_parent("form")
    submit_action = target_form.get("action") if target_form else None
    if not submit_action or submit_action.strip() in ("", "/"):
        submit_action = action_url
    submit_url = submit_action if submit_action.startswith("http") else f"{BASE}/{submit_action.lstrip('/')}"

    submit_data: dict[str, str] = {}
    inputs = target_form.find_all("input") if target_form else []
    for i in inputs:
        name = i.get("name")
        if name:
            submit_data[name] = i.get("value", "")

    selects = target_form.find_all("select") if target_form else []
    picked_max: str | None = None
    for sel in selects:
        name = sel.get("name")
        if not name:
            continue
        max_val: str | None = None
        max_int = -1
        for opt in sel.find_all("option"):
            val = (opt.get("value") or "").strip()
            if not val:
                continue
            try:
                vi = int(val)
                if vi > max_int:
                    max_int = vi
                    max_val = val
            except ValueError:
                if max_val is None:
                    max_val = val
        if max_val is not None:
            submit_data[name] = max_val
            picked_max = max_val

    btn = target_form.find("button", type="submit") if target_form else submit_btn
    if btn and btn.get("name"):
        submit_data[btn.get("name")] = btn.get("value", "")

    r2 = session.post(submit_url, headers=AJAX_HEADERS, data=submit_data, timeout=45)
    dec2 = decode_zefoy_response(r2.text)
    msg = clean_html_text(dec2) or "Đã gửi (không có phản hồi text)"
    cd2, _ = extract_cooldown_seconds(dec2)

    amount = None
    m = re.search(r"(\d+)", msg)
    if m:
        try:
            amount = int(m.group(1))
        except Exception:
            amount = None

    return {
        "status": "ok",
        "message": msg,
        "cooldown": cd2 or None,
        "amount": amount,
        "picked_max": picked_max,
    }
