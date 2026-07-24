"""
buff_engine.py — Zefoy buff core (không tương tác), rút gọn từ buff.py gốc.
Giữ nguyên logic decode/cooldown/submit của tool gốc.
"""
import re, html, json, base64, time, urllib.parse
import requests
from bs4 import BeautifulSoup

BASE = "https://zefoy.com"

def parse_cookie_string(s: str):
    out = {}
    for it in (s or "").split(";"):
        it = it.strip()
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def build_session(cookie_str: str, ua: str) -> requests.Session:
    s = requests.Session()
    s.cookies.update(parse_cookie_string(cookie_str))
    s.headers.update({
        "user-agent": ua or "Mozilla/5.0",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "vi-VN,vi;q=0.9,en;q=0.8",
        "referer": BASE + "/",
    })
    return s

def decode_zefoy_response(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    def try_decode(v):
        try:
            d = base64.b64decode(urllib.parse.unquote(v[::-1])).decode("utf-8")
            if "<" in d or "{" in d:
                return d
        except Exception:
            pass
        try:
            d = base64.b64decode(v).decode("utf-8")
            if "<" in d or "{" in d:
                return d
        except Exception:
            pass
        return v
    dec = try_decode(text)
    if dec != text:
        try:
            data = json.loads(dec)
            if isinstance(data, dict) and "html" in data:
                return try_decode(data["html"])
        except Exception:
            pass
        return dec
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "html" in data:
            return try_decode(data["html"])
    except Exception:
        pass
    return text

def extract_cooldown_seconds(decoded: str):
    soup = BeautifulSoup(decoded, "html.parser")
    tag = soup.find(id="login-countdown") or soup.find(class_=re.compile(r"countdown"))
    txt = (tag.text.strip() if tag else "") or soup.get_text(" ", strip=True)
    m1 = re.search(r"(\d+)\s*minute", txt, re.I)
    m2 = re.search(r"(\d+)\s*second", txt, re.I)
    if m1 or m2:
        total = (int(m1.group(1)) if m1 else 0) * 60 + (int(m2.group(1)) if m2 else 0)
        if total > 0:
            return total
    for pat in [r"var\s+ltm\s*=\s*(\d+)", r"ltimer\s*\(\s*(\d+)", r"timer\s*\(\s*(\d+)",
                r"var\s+k\s*=\s*(\d+)", r"var\s+time\s*=\s*(\d+)", r"var\s+c\s*=\s*(\d+)",
                r"seconds\s*=\s*(\d+)"]:
        m = re.search(pat, decoded, re.I)
        if m:
            v = int(m.group(1))
            if v > 0:
                return v
    if "checking timer" in txt.lower() or "please wait" in txt.lower():
        return 120
    return 0

def get_services(session: requests.Session):
    r = session.get(BASE + "/")
    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.find_all("div", class_="colsmenu")
    services = []
    for c in cards:
        title = c.find("h5", class_="card-title")
        btn = c.find("button")
        if not title or not btn:
            continue
        active = "disabled" not in btn.attrs
        btn_class = ""
        for cls in btn.get("class", []):
            if cls.startswith("t-") and cls.endswith("-button"):
                btn_class = cls
                break
        st = c.find(class_="badge") or c.find("small")
        services.append({
            "name": title.text.strip(),
            "active": active,
            "status": st.text.strip() if st else ("ON" if active else "OFF"),
            "btn_class": btn_class,
            "menu_class": btn_class.replace("-button", "-menu") if btn_class else "",
            "id": btn_class.replace("-button", "").replace("t-", "") if btn_class else "",
        })
    return services, r.text

def get_service_form(home_html: str, menu_class: str):
    soup = BeautifulSoup(home_html, "html.parser")
    div = soup.find("div", class_=menu_class) or soup.find(class_=re.compile(menu_class))
    if not div:
        return None
    form = div.find("form")
    if not form:
        return None
    inp = form.find("input", type="search") or form.find("input", type="text")
    return {"action": form.get("action"), "input_name": inp.get("name") if inp else None}

def run_buff_once(cookie_str: str, ua: str, service_id: str, video_url: str) -> dict:
    """Thực thi 1 lượt buff. Trả dict {ok, message, cooldown}."""
    if not cookie_str:
        return {"ok": False, "message": "Chưa cấu hình cookie trong /admin"}
    s = build_session(cookie_str, ua)
    services, home_html = get_services(s)
    svc = next((x for x in services if x["id"] == service_id or x["name"].lower() == service_id.lower()), None)
    if not svc:
        return {"ok": False, "message": f"Không có dịch vụ '{service_id}'"}
    if not svc["active"]:
        return {"ok": False, "message": f"Dịch vụ '{svc['name']}' đang OFFLINE"}
    form_info = get_service_form(home_html, svc["menu_class"])
    if not form_info or not form_info["action"] or not form_info["input_name"]:
        return {"ok": False, "message": "Không lấy được form của dịch vụ"}

    ajax_headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": BASE, "referer": BASE + "/",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": ua or "Mozilla/5.0",
    }
    action_url = f"{BASE}/{form_info['action']}"
    data = {form_info["input_name"]: video_url}

    decoded = None
    for _ in range(3):
        r = s.post(action_url, headers=ajax_headers, data=data)
        decoded = decode_zefoy_response(r.text)
        cd = extract_cooldown_seconds(decoded)
        soup = BeautifulSoup(decoded, "html.parser")
        form = soup.find("form")
        btn = soup.find("button", class_=re.compile(r"wbutton|btn"))
        if (cd > 0) or form or btn:
            break
        time.sleep(2.5)

    cd = extract_cooldown_seconds(decoded or "")
    if cd > 0:
        return {"ok": False, "message": f"Đang cooldown {cd}s", "cooldown": cd}

    soup = BeautifulSoup(decoded or "", "html.parser")
    form = soup.find("form")
    btn = soup.find("button", class_=re.compile(r"wbutton|btn"))
    if not (form or btn):
        return {"ok": False, "message": "Không tìm được form submit (cookie có thể hết hạn)"}

    target = form if form else btn.find_parent("form")
    submit_action = (target.get("action") if target else None) or form_info["action"]
    if not submit_action or submit_action in ("", "/") or not submit_action.startswith("c2Vu"):
        submit_action = form_info["action"]
    submit_url = f"{BASE}/{submit_action}"

    submit_data = {}
    for inp in (target.find_all("input") if target else []):
        n = inp.get("name")
        if n:
            submit_data[n] = inp.get("value", "")
    for sel in (target.find_all("select") if target else []):
        n = sel.get("name")
        if not n:
            continue
        opts = sel.find_all("option")
        best = None; bestv = -1
        for o in opts:
            try:
                v = int(re.search(r"\d+", o.get("value", "") or o.text).group(0))
                if v > bestv:
                    bestv, best = v, o.get("value", "") or o.text
            except Exception:
                continue
        if best is not None:
            submit_data[n] = best

    r2 = s.post(submit_url, headers=ajax_headers, data=submit_data)
    dec2 = decode_zefoy_response(r2.text)
    txt = BeautifulSoup(dec2, "html.parser").get_text(" ", strip=True).lower()
    if "success" in txt or "sent" in txt or "tăng" in txt or "hoàn" in txt:
        return {"ok": True, "message": "Đã gửi lượt buff thành công"}
    cd2 = extract_cooldown_seconds(dec2)
    if cd2 > 0:
        return {"ok": True, "message": f"Gửi xong, cooldown {cd2}s", "cooldown": cd2}
    return {"ok": True, "message": "Đã gửi (không xác định rõ phản hồi)"}
