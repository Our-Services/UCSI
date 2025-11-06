import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, urlencode
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# -----------------------------------------------
# ملاحظات إعداد سريعة (اقرأني):
#
# 1) أين أضع الرابط؟
#    - في الملف: config/config.json داخل المفتاح "url".
#    - أو يمكنك تمرير الرابط عند التشغيل عبر وسيط: --url
#      مثال: python src/bot.py --url https://example.com...
#
# 2) أين أضع أسماء المستخدمين وكلمات السر؟
#    - في الملف: config/config.json داخل المفتاح "users" كمصفوفة عناصر.
#      كل عنصر يحتوي على: studentId و password
#      مثال:
#        "users": [
#          { "studentId": "2023012345", "password": "pass1" },
#          { "studentId": "2023012346", "password": "pass2" }
#        ]
#
# 3) ماذا لو لم يتعرّف السكربت على الحقول/الأزرار؟
#    - استخدم "login.overrides" في config.json لتعريف محددات CSS مباشرة:
#      - student_id_selector، password_selector، submit_selector
#
# 4) الموقع يطلب تمكين الموقع (GPS):
#    - حدّد إحداثياتك في "geolocation" داخل config.json ليتم منح الإذن تلقائيًا.
# -----------------------------------------------


def load_config(path: str) -> Dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        print(f"[Error] Configuration file not found: {cfg_path}")
        sys.exit(1)
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)


def get_arg(key: str, default: str | None = None) -> str | None:
    for i, a in enumerate(sys.argv):
        if a == key and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(f"{key}="):
            return a.split("=", 1)[1]
    return default


def grant_geo_permissions(context, origin: str, geolocation: Dict[str, Any] | None):
    if geolocation:
        context.set_default_navigation_timeout(30000)
        try:
            context.grant_permissions(["geolocation"], origin=origin)
        except Exception:
            # بعض الإصدارات لا تحتاج origin
            context.grant_permissions(["geolocation"])  # noqa
        # إعداد موقع جغرافي افتراضي عند إنشاء الصفحة
        # ملاحظة: new_context يدعم geolocation مباشرة أيضًا، لكن نستخدم منطقًا موحدًا هنا.


def fetch_ip_geolocation() -> Dict[str, Any] | None:
    """Attempts to fetch the geolocation based on the public IP address of the device."""
    # First attempt: ipapi.co
    try:
        with urllib.request.urlopen("https://ipapi.co/json", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            lat = data.get("latitude") or data.get("lat")
            lon = data.get("longitude") or data.get("lon")
            if lat is not None and lon is not None:
                return {"latitude": float(lat), "longitude": float(lon), "accuracy": 1000}
    except Exception:
        pass
    # المحاولة الثانية: ip-api.com
    try:
        with urllib.request.urlopen("http://ip-api.com/json", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                lat = data.get("lat")
                lon = data.get("lon")
                if lat is not None and lon is not None:
                    return {"latitude": float(lat), "longitude": float(lon), "accuracy": 2000}
    except Exception:
        pass
    return None


def resolve_geolocation(config: Dict[str, Any]) -> Dict[str, Any] | None:
    """Resolves the geolocation based on the configuration: either fixed or via IP."""
    geo_cfg = config.get("geolocation") or {}
    source = str(geo_cfg.get("source", "fixed")).lower()
    if source == "browser":
        # اترك المتصفح يحدّد الموقع بنفسه. سنمنح الإذن فقط دون تمرير إحداثيات.
        return None
    if source == "ip":
        ip_geo = fetch_ip_geolocation()
        if ip_geo:
            # استخدم دقة من الإعداد إن وُجدت
            acc = geo_cfg.get("accuracy")
            if acc is not None:
                ip_geo["accuracy"] = acc
            return ip_geo
        # إن فشل الجلب عبر IP، أعد محاولة باستخدام القيم الثابتة إن وُجدت
    # مصدر ثابت: استخدم القيم كما هي إن وُجدت
    lat = geo_cfg.get("latitude")
    lon = geo_cfg.get("longitude")
    acc = geo_cfg.get("accuracy", 1000)
    if lat is not None and lon is not None:
        return {"latitude": float(lat), "longitude": float(lon), "accuracy": int(acc)}
    return None

def probe_browser_geolocation(page, config: Dict[str, Any]) -> None:
    """Attempts to learn the browser's geolocation if the source is 'browser'."""
    geo_cfg = config.get("geolocation") or {}
    if str(geo_cfg.get("source", "fixed")).lower() != "browser":
        return
    wait_ms = int(geo_cfg.get("wait_ms", 4000))
    require = bool(geo_cfg.get("require_browser", True))
    try:
        page.wait_for_timeout(500)  # فسحة قصيرة قبل الطلب
    except Exception:
        pass
    try:
        result = page.evaluate(
            """
            () => new Promise((resolve) => {
              try {
                navigator.geolocation.getCurrentPosition(
                  (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy }),
                  (err) => resolve({ error: String(err && err.message || 'geolocation-error') })
                );
              } catch (e) {
                resolve({ error: String(e && e.message || 'geolocation-exception') });
              }
            })
            """
        )
        if isinstance(result, dict) and not result.get("error"):
            print(f"[Info] Browser geolocation: lat={result['lat']}, lon={result['lon']}, acc≈{int(result['acc'])}m")
            return
        else:
            if require:
                print(f"[Warning] Failed to get browser geolocation: {result.get('error')}")
            return
    except Exception as e:
        if require:
            print(f"[Error] Exception while querying browser geolocation: {e}")
    # انتظار إضافي اختياري حين يتطلب الموقع طلبًا لاحقًا
    if wait_ms > 0:
        try:
            page.wait_for_timeout(wait_ms)
        except Exception:
            pass


def click_first_matching_button(page, names: List[str]) -> bool:
    for name in names:
        try:
            page.get_by_role("button", name=re.compile(name, re.I)).click()
            return True
        except Exception:
            # جرّب مطابقة نص مباشرة
            try:
                page.locator(f"text={name}").first.click()
                return True
            except Exception:
                # محاولات إضافية وفق البنية الظاهرة (زر بداخله span.t-Button-label)
                try:
                    page.locator("button").filter(has_text=re.compile(name, re.I)).first.click()
                    return True
                except Exception:
                    try:
                        page.locator("button:has(span.t-Button-label)").filter(has_text=re.compile(name, re.I)).first.click()
                        return True
                    except Exception:
                        try:
                            page.locator("span.t-Button-label").filter(has_text=re.compile(name, re.I)).first.click()
                            return True
                        except Exception:
                            continue
    return False

def wait_and_click_first_matching(page, names: List[str], timeout_ms: int) -> bool:
    """Waits until any of the buttons with the specified names appears, then clicks it."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if click_first_matching_button(page, names):
            return True
        try:
            page.wait_for_timeout(400)
        except Exception:
            pass
    return False


def _spinner_selectors(shots_cfg: Dict[str, Any]) -> List[str]:
    prepared_wait_selector_cfg = shots_cfg.get("prepared_wait_selector")
    if isinstance(prepared_wait_selector_cfg, list):
        selectors = [str(s).strip() for s in prepared_wait_selector_cfg if str(s).strip()]
    elif isinstance(prepared_wait_selector_cfg, str) and prepared_wait_selector_cfg.strip():
        selectors = [prepared_wait_selector_cfg.strip()]
    else:
        selectors = [
            ".fa-spinner",
            ".t-Icon--spinner",
            ".u-Processing",
            ".apex_wait_mask",
            "div.u-Processing-spinner",
            ".spinner",
            ".spinner-border",
            ".loading-spinner",
            ".lds-spinner",
            ".MuiCircularProgress-root",
        ]
    return selectors


def _wait_idle_and_hide_spinners(page, shots_cfg: Dict[str, Any], timeout_ms: int) -> None:
    # أولاً: انتظر حالة تحميل الصفحة
    try:
        page.wait_for_load_state("networkidle")
    except Exception:
        try:
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
    # ثانيًا: حاول إخفاء مؤشرات التحميل الشائعة
    selectors = _spinner_selectors(shots_cfg)
    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state="hidden", timeout=timeout_ms)
            break
        except Exception:
            continue


def _send_telegram_message(chat_id: int | str, text: str) -> None:
    """Send a simple text message via Telegram Bot API.
    Requires TELEGRAM_TOKEN in environment. Swallows all errors."""
    try:
        token = os.getenv("TELEGRAM_TOKEN")
        if not token:
            return
        api = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urlencode({"chat_id": int(chat_id), "text": text})
        req = urllib.request.Request(api, data=payload.encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def _notify_initiator(config: Dict[str, Any], text: str) -> None:
    notify = (config.get("notify") or {})
    chat_id = notify.get("initiator_chat_id") or notify.get("chat_id")
    if chat_id:
        _send_telegram_message(chat_id, text)

def _delete_started_message_if_any(config: Dict[str, Any]) -> None:
    try:
        notify = (config.get("notify") or {})
        chat_id = notify.get("started_message_chat_id")
        msg_id = notify.get("started_message_id")
        token = os.getenv("TELEGRAM_TOKEN")
        if token and chat_id and msg_id:
            import requests as _requests
            api_url = f"https://api.telegram.org/bot{token}/deleteMessage"
            payload = {"chat_id": chat_id, "message_id": msg_id}
            try:
                _requests.post(api_url, json=payload, timeout=10)
            except Exception:
                pass
    except Exception:
        pass


def screenshot_for(page, sid: str, config: Dict[str, Any], suffix: str | None = None) -> str | None:
    """Captures a screenshot and appends an optional suffix to the filename to indicate the state.
    Returns the file path on success, or None on failure."""
    tmpl = config.get("screenshot_template", "output/{studentId}.png")
    shots_cfg = config.get("screenshots", {})
    full_page = bool(shots_cfg.get("full_page", False))
    scroll_top_before = bool(shots_cfg.get("scroll_top_before", True))
    # مهلة قبل لقطة الشاشة بعد التحضير (قابلة للضبط)
    delay_ms_prepared = int(shots_cfg.get("delay_ms_before_prepared", 3000))
    # اختياري: انتظر زوال مؤشرات التحميل قبل لقطة "prepared"
    prepared_wait_timeout = int(shots_cfg.get("prepared_wait_timeout_ms", 15000))
    path_str = tmpl.format(studentId=sid)
    # Append optional suffix and a timestamp YYYYMMDD-HHMMSS to filename
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    p = Path(path_str)
    new_stem = p.stem
    if suffix:
        new_stem = f"{new_stem}-{suffix}"
    new_stem = f"{new_stem}-{timestamp}"
    path_str = str(p.with_name(new_stem + p.suffix))
    out_path = Path(path_str)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # انتظر قبل الالتقاط إذا كانت اللقطة "prepared" لتجنب مشاكل العرض
        if suffix == "prepared":
            try:
                _wait_idle_and_hide_spinners(page, shots_cfg, prepared_wait_timeout)
            except Exception:
                pass
            if delay_ms_prepared > 0:
                try:
                    page.wait_for_timeout(delay_ms_prepared)
                except Exception:
                    pass
        if scroll_top_before:
            try:
                page.evaluate("window.scrollTo(0,0)")
            except Exception:
                pass
        page.screenshot(path=str(out_path), full_page=full_page)
        print(f"[Info] Saved screenshot: {out_path}")
        return str(out_path)
    except Exception:
        print("[Error] Failed to save screenshot.")
        return None


def scroll_back_to_top(page, delay_ms: int = 200):
    """Scrolls the page back to the top to reduce visible motion after clicks."""
    try:
        if delay_ms > 0:
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass
    try:
        page.evaluate("window.scrollTo(0,0)")
    except Exception:
        pass

def handle_cloudflare_challenge(page, config: Dict[str, Any]) -> bool:
    """Tries to handle the Cloudflare challenge page if it is present.
    Returns True if no challenge is present or if it is successfully bypassed,
    and False if the challenge prevents proceeding.
    """
    cf_cfg = (config.get("cloudflare") or {})
    mode = str(cf_cfg.get("handle_challenge", "auto")).lower()
    timeout_ms = int(cf_cfg.get("timeout_ms", 20000))
    after_delay_ms = int(cf_cfg.get("after_check_delay_ms", 1500))

    if mode == "off":
        return True

    def is_challenge_present() -> bool:
        try:
            if page.locator("text=Verify you are human").first.is_visible():
                return True
        except Exception:
            pass
        try:
            if page.locator("text=Performance & security by Cloudflare").first.is_visible():
                return True
        except Exception:
            pass
        try:
            if page.locator("iframe[title*='security challenge']").count() > 0:
                return True
        except Exception:
            pass
        return False

    # إن لم يوجد تحدي فلا حاجة لشيء
    if not is_challenge_present():
        return True

    # محاولة تلقائية للنقر على مربع التحقق
    if mode in ("auto", "automatic"):
        try:
            page.get_by_label(re.compile("Verify you are human", re.I)).check()
            try:
                page.wait_for_load_state("networkidle")
            except Exception:
                page.wait_for_load_state("domcontentloaded")
            if after_delay_ms > 0:
                try:
                    page.wait_for_timeout(after_delay_ms)
                except Exception:
                    pass
        except Exception:
            # جرّب عبر الإطار مباشرة إن وُجد
            try:
                frame = page.frame_locator("iframe[title*='security challenge']").first
                frame.locator("input[type='checkbox']").click()
                if after_delay_ms > 0:
                    try:
                        page.wait_for_timeout(after_delay_ms)
                    except Exception:
                        pass
            except Exception:
                pass

    # في الوضع اليدوي، امنح بعض الوقت ليحل المستخدم التحدي
    if mode == "manual":
        print("[Warning] Cloudflare challenge detected. Please resolve it manually if required.")
        try:
            page.wait_for_timeout(timeout_ms)
        except Exception:
            pass

    return not is_challenge_present()

def run_for_user(p, browser, headless: bool, url: str, origin: str, user: Dict[str, str], config: Dict[str, Any]) -> bool:
    geolocation = resolve_geolocation(config)
    browser_cfg = (config.get("browser") or {})
    user_agent = browser_cfg.get("user_agent") or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    )
    context = browser.new_context(geolocation=geolocation or None, user_agent=user_agent, locale="en-US")
    # Stealth: reduce automation fingerprints, especially in headless
    try:
        context.add_init_script(
            """
            // Hide webdriver flag
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            // Fake chrome object
            window.chrome = { runtime: {} };
            // Language and vendor
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            // Patch permissions.query to avoid noisy results
            const originalQuery = (navigator.permissions && navigator.permissions.query) ? navigator.permissions.query.bind(navigator.permissions) : null;
            if (originalQuery) {
              navigator.permissions.query = (parameters) => {
                if (parameters && parameters.name === 'notifications') {
                  return Promise.resolve({ state: Notification.permission });
                }
                return originalQuery(parameters);
              };
            }
            // WebGL fingerprint softening
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
              if (parameter === 37445) return 'Intel(R) UHD Graphics 620';
              if (parameter === 37446) return 'Google Inc. (Intel)';
              return getParameter.call(this, parameter);
            };
            """
        )
    except Exception:
        pass
    # يحدّد الموقع الجغرافي تلقائيًا حسب المصدر (IP أو ثابت) من config/config.json
    grant_geo_permissions(context, origin, geolocation)
    page = context.new_page()

    print(f"[Info] Navigating to: {url}")
    page.goto(url, wait_until="domcontentloaded")

    # تحقّق من تحدي Cloudflare إن وُجد وحاول تجاوزه
    if not handle_cloudflare_challenge(page, config):
        sid = user.get("studentId", "")
        print("[Warning] Cloudflare challenge prevents proceeding for this user.")
        screenshot_for(page, sid, config, suffix="cloudflare-challenge")
        context.close()
        return False

    # في وضع المتصفح: اطلب إحداثيات الجهاز الحالي ثم تابع
    probe_browser_geolocation(page, config)

    ui_cfg = config.get("ui", {})
    scroll_back_after_click = bool(ui_cfg.get("scroll_back_after_click", True))
    scroll_back_delay_ms = int(ui_cfg.get("scroll_back_delay_ms", 200))

    login_cfg = config.get("login", {})
    student_label = login_cfg.get("student_id_label", "Student ID")
    password_label = login_cfg.get("password_label", "Password")
    submit_names = login_cfg.get("submit_button_names", ["Sign In", "Login"])
    overrides = login_cfg.get("overrides", {})

    sid = user.get("studentId", "")
    pwd = user.get("password", "")
    shots_cfg = config.get("screenshots", {})

    try:
        if overrides.get("student_id_selector"):
            page.fill(overrides["student_id_selector"], sid)
            # إذا حددت student_id_selector داخل login.overrides في config.json سيتم استخدامه مباشرة
        else:
            page.get_by_label(student_label).fill(sid)
            # إذا لم تحدد محددًا، سيبحث عن الحقل بواسطة نص الملصق "Student ID"
        if overrides.get("password_selector"):
            page.fill(overrides["password_selector"], pwd)
            # إذا حددت password_selector داخل login.overrides سيتم استخدامه مباشرة
        else:
            page.get_by_label(password_label).fill(pwd)
            # إذا لم تحدد محددًا، سيبحث عن الحقل بواسطة نص الملصق "Password"
    except Exception as e:
        print(f"[Error] Failed to fill login fields: {e}")
        # التقط لقطة شاشة لحالة الخطأ
        screenshot_for(page, sid, config, suffix="login-error")
        context.close()
        return False

    # لقطة شاشة بعد تحضير المُعرّف (تعبئة الحقول) قبل محاولة الدخول (قابلة للتعطيل)
    if bool(shots_cfg.get("capture_prepared", False)):
        screenshot_for(page, sid, config, suffix="prepared")

    # انقر زر الدخول
    clicked = False
    if overrides.get("submit_selector"):
        try:
            page.click(overrides["submit_selector"]) 
            clicked = True
            # زر الإرسال محدد مباشرة عبر submit_selector داخل login.overrides
        except Exception:
            # لقطة شاشة عند فشل النقر على زر الإرسال المحدد
            screenshot_for(page, sid, config, suffix="submit-click-error")
            clicked = False
    if not clicked:
        clicked = click_first_matching_button(page, submit_names)
        # إن لم تُحدِّد submit_selector، سيُجرّب أسماء الأزرار في القائمة مثل "Sign In" أو "Login"
    if not clicked:
        print("[Error] Failed to find the login button.")
        # لقطة شاشة عند عدم العثور على زر الدخول
        screenshot_for(page, sid, config, suffix="submit-not-found")
        context.close()
        return False
    # بعد النقر على زر الدخول، أعد التمرير للأعلى لتقليل الحركة المرئية
    if scroll_back_after_click:
        scroll_back_to_top(page, scroll_back_delay_ms)

    # انتظر تواجد واجهة الحضور أو زر الحضور
    check_cfg = config.get("checkin", {})
    check_names = check_cfg.get("button_names", ["Check-In"])  # أزرار محتملة
    timeout_ms = int(check_cfg.get("timeout_ms", 15000))
    success_selector = check_cfg.get("success_selector")
    # success_selector: عنصر يظهر بعد نجاح الحضور (مثل .alert-success) إن رغبت بالتحقق منه

    # بعد الدخول، انتظر استقرار الصفحة ثم حاول الضغط على زر الحضور
    try:
        page.wait_for_load_state("networkidle")
    except Exception:
        page.wait_for_load_state("domcontentloaded")

    # إن توفر محدد مباشر لزر الحضور استخدمه أولاً
    check_selector = check_cfg.get("selector")
    pressed = False
    did_capture_after_checkin = False
    if check_selector:
        try:
            page.click(check_selector)
            pressed = True
        except Exception:
            pressed = False
    if not pressed:
        # حاول الضغط على زر الحضور بانتظار ظهوره
        pressed = wait_and_click_first_matching(page, check_names, timeout_ms)
    if not pressed:
        # أحيانًا يكون زر الحضور باسم "Sign In" داخل صفحة الحضور نفسها
        pressed = wait_and_click_first_matching(page, ["Sign In"], timeout_ms) or pressed
    if not pressed:
        print("[Error] Failed to click the Check-In button.")
        screenshot_for(page, sid, config, suffix="checkin-not-found")
        context.close()
        return False
    # بعد النقر على زر الحضور، أعد التمرير للأعلى أيضًا
    if scroll_back_after_click:
        scroll_back_to_top(page, scroll_back_delay_ms)

    # التقط صورة بعد CHECK-IN فقط إن كان الخيار مفعّلًا
    if bool(shots_cfg.get("capture_after_checkin", True)):
        suffix = str(shots_cfg.get("suffix_after_checkin", "checked-in"))
        # انتظر الاستقرار أو تحقق النجاح قبل الالتقاط بعد النقر
        try:
            # إن توفر success_selector، انتظر ظهوره أولًا
            if success_selector:
                selectors: List[str] = []
                if isinstance(success_selector, list):
                    selectors = [str(s).strip() for s in success_selector if str(s).strip()]
                else:
                    selectors = [s.strip() for s in str(success_selector).split(",") if s.strip()]
                seen = False
                for sel in selectors:
                    try:
                        page.locator(sel).first.wait_for(timeout=timeout_ms, state="visible")
                        seen = True
                        break
                    except Exception:
                        continue
            # على أي حال، أخفِ مؤشرات التحميل وانتظر السكون
            _wait_idle_and_hide_spinners(page, shots_cfg, int(shots_cfg.get("prepared_wait_timeout_ms", 15000)))
        except Exception:
            pass
        shot_path = screenshot_for(page, sid, config, suffix=suffix)
        # بعد الالتقاط، إن كان لدى المستخدم معرف تلغرام، أرسل صورة التوثيق له
        try:
            if shot_path:
                _notify_user_with_photo(user, config, shot_path)
        except Exception:
            pass
        did_capture_after_checkin = True

    # انتظر نجاح إن توفر محدد
    if success_selector:
        # يدعم قائمة محددات أو سلسلة مفصولة بفواصل
        selectors: List[str] = []
        if isinstance(success_selector, list):
            selectors = [str(s).strip() for s in success_selector if str(s).strip()]
        else:
            selectors = [s.strip() for s in str(success_selector).split(",") if s.strip()]

        seen = False
        for sel in selectors:
            try:
                # استخدم Locator الذي يدعم أنماط Playwright مثل text=...
                page.locator(sel).first.wait_for(timeout=timeout_ms, state="visible")
                seen = True
                break
            except PlaywrightTimeout:
                continue
            except Exception:
                # تجاهل أخطاء التحليل لمحددات غير متوافقة وجرب الذي يليه
                continue
        if not seen:
            print("[Warning] Failed to verify success within timeout or invalid selectors.")

    # لقطة شاشة نهائية باسم المستخدم إذا لم نلتقط بعد CHECK-IN
    if not did_capture_after_checkin:
        screenshot_for(page, sid, config, suffix=None)

    context.close()
    return True


def _notify_user_with_photo(user: Dict[str, Any], config: Dict[str, Any], photo_path: str) -> None:
    """Sends a verification photo to the user via Telegram using the Bot API.
    Depends on the presence of the environment variable TELEGRAM_TOKEN and the user's chat ID.
    """
    try:
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = user.get("telegram_chat_id")
        if not token or not chat_id:
            return
        # تحضير عنوان وتسمية
        sid = user.get("studentId", "")
        subject = str(config.get("selected_subject", "")).strip()
        caption = (f"Your attendance has been documented" + (f" For subject: {subject}" if subject else "") + f"\nStudent ID: {sid}")

        # إرسال عبر HTTP متعدد الأجزاء
        import urllib.request
        import urllib.parse
        import mimetypes
        import uuid

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        parts: list[bytes] = []

        def add_field(name: str, value: str):
            parts.append(
                (f"--{boundary}\r\n"
                 f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode("utf-8")
            )

        def add_file(name: str, filename: str, content: bytes, content_type: str):
            header = (f"--{boundary}\r\n"
                      f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                      f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
            parts.append(header)
            parts.append(content)
            parts.append(b"\r\n")

        add_field("chat_id", str(int(chat_id)))
        add_field("caption", caption)
        # حمّل الملف
        try:
            with open(photo_path, "rb") as f:
                data = f.read()
        except Exception:
            return
        ctype = mimetypes.guess_type(photo_path)[0] or "image/png"
        add_file("photo", os.path.basename(photo_path), data, ctype)
        parts.append((f"--{boundary}--\r\n").encode("utf-8"))
        body = b"".join(parts)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Content-Length", str(len(body)))
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                _ = resp.read()
        except Exception:
            # تجاهل أي أخطاء في الإرسال حتى لا تعطل التدفق الرئيسي
            pass
    except Exception:
        # تجنّب إسقاط التنفيذ بسبب أي خطأ غير متوقع هنا
        pass


def run_bot(config: Dict[str, Any]) -> None:
    # الرابط يؤخذ أولًا من وسيط التشغيل --url إن توفر، وإلا من config.json
    url = get_arg("--url", config.get("url"))
    if not url:
        print("[Error] URL not specified. Pass --url or specify it in config.json")
        sys.exit(1)

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # المستخدمون يُقرأون من config.json ضمن المفتاح "users"
    # مثال عنصر: { "studentId": "2023xxxxx", "password": "secret" }
    users: List[Dict[str, str]] = config.get("users", [])
    # إن كانت هناك مادة محددة (من واجهة التحضير)، صفِّ المستخدمين لتلك المادة فقط
    subject_filter = str(config.get("selected_subject", "")).strip()
    if subject_filter:
        try:
            users = [u for u in users if subject_filter in (u.get("subjects", []) or [])]
        except Exception:
            pass
    if not users:
        print("[Warning] No user list found in config. Trying once without credentials.")
        users = [{"studentId": "", "password": ""}]

    headless_env = os.getenv("HEADLESS", "0").strip()
    headless = headless_env in ("1", "true", "True")

    # عدد الجلسات المتوازية
    parallel = int(config.get("parallel_browsers", 0) or 0)
    if parallel <= 0:
        parallel = len(users)
    print(f"[Info] Launching browsers in parallel: {parallel}, Headless: {headless}")

    # Progress notification: percentages removed; only final message will be sent

    def worker(u: Dict[str, str]):
        # كل عامل يُنشئ Playwright ومتصفحًا خاصين به لعدم مشاركة الحالة بين الجلسات
        with sync_playwright() as p:
            browser_cfg = (config.get("browser") or {})
            launch_args = list(browser_cfg.get("launch_args", [])) or [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            browser = p.chromium.launch(headless=headless, args=launch_args)
            try:
                ok = run_for_user(p, browser, headless, url, origin, u, config)
                return (u.get("studentId"), ok)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    results: List[tuple[str | None, bool]] = []
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        future_map = {ex.submit(worker, u): u for u in users}
        for fut in as_completed(future_map):
            sid, ok = fut.result()
            results.append((sid, ok))

    # ملخص
    print("\n[Summary]")
    for sid, ok in results:
        print(f"- {sid}: {'Success' if ok else 'Failure'}")
    print("[Info] Automation process completed.")
    # Delete the started message (if stored), then send final completion message with checkmark
    try:
        _delete_started_message_if_any(config)
        subj = str(config.get("selected_subject", "")).strip() or "All"
        _notify_initiator(config, f"Preparation finished for '{subj}' ✅")
    except Exception:
        pass

    # فتح مجلد الصور بعد الانتهاء إذا كان الخيار مفعّلًا
    try:
        if bool(config.get("open_output_dir_after_run", False)):
            tmpl = config.get("screenshot_template", "output/{studentId}.png")
            try:
                sample = Path(tmpl.format(studentId="example"))
            except Exception:
                sample = Path("output/example.png")
            out_dir = sample.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"[Info] Opening output directory: {out_dir}")
            if sys.platform.startswith("win"):
                os.startfile(str(out_dir))  # نوعية ويندوز
            elif sys.platform == "darwin":
                os.system(f"open \"{out_dir}\"")
            else:
                os.system(f"xdg-open \"{out_dir}\"")
    except Exception:
        pass


if __name__ == "__main__":
    load_dotenv()
    cfg_path = get_arg("--config", "config/config.json")
    config = load_config(cfg_path)
    run_bot(config)