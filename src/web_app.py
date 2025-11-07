import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, render_template, redirect, url_for, request, flash, session
from urllib.parse import urlencode
from urllib.request import Request, urlopen


app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent / "templates"), static_folder=str(Path(__file__).resolve().parent / "static"))
app.secret_key = os.getenv("FLASK_SECRET_KEY", "ucsi-web-secret")


# -----------------------------
# Output images auto-cleaner
# -----------------------------
def _clean_output_once(max_age_hours: int = 6) -> int:
    """Delete images in ./output older than max_age_hours. Returns count deleted."""
    try:
        import time
        root = Path("output")
        if not root.exists():
            return 0
        cutoff = time.time() - max_age_hours * 3600
        patterns = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif")
        deleted = 0
        for pat in patterns:
            for p in root.glob(pat):
                try:
                    if p.is_file() and p.stat().st_mtime < cutoff:
                        p.unlink(missing_ok=True)
                        deleted += 1
                except Exception:
                    # Ignore files we cannot delete
                    pass
        # Optionally remove empty subdirectories
        for sub in root.glob("*/"):
            try:
                if sub.is_dir() and not any(sub.iterdir()):
                    sub.rmdir()
            except Exception:
                pass
        return deleted
    except Exception:
        return 0


def start_output_cleanup_daemon():
    """Start a background cleaner that runs every N hours.

    Env vars:
    - OUTPUT_MAX_AGE_HOURS (default: 6) — delete files older than this age
    - OUTPUT_CLEAN_INTERVAL_HOURS (default: same as max age) — run frequency
    - OUTPUT_AUTO_CLEAN (default: 1) — set to 0 to disable
    """
    if os.getenv("OUTPUT_AUTO_CLEAN", "1") not in ("1", "true", "True"):
        return
    try:
        max_age = int(os.getenv("OUTPUT_MAX_AGE_HOURS", "6") or 6)
    except Exception:
        max_age = 6
    try:
        interval = int(os.getenv("OUTPUT_CLEAN_INTERVAL_HOURS", str(max_age)) or max_age)
    except Exception:
        interval = max_age

    def _loop():
        import time
        while True:
            try:
                deleted = _clean_output_once(max_age)
                if deleted:
                    print(f"[output-clean] Deleted {deleted} old image(s) from ./output")
            except Exception:
                pass
            time.sleep(max(1, interval) * 3600)

    try:
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
    except Exception:
        pass


# Launch the output cleaner in the background when the web app starts
start_output_cleanup_daemon()


PRESETS = {
    "building_c": {"latitude": 0.0, "longitude": 0.0, "accuracy": 10},
    "building_g": {"latitude": 0.0, "longitude": 0.0, "accuracy": 10},
}

# Initial subjects that will seed the shared library if empty
DEFAULT_SUBJECTS: List[str] = [
    "Engineering Statics",
    "Mathematical Methods for Engineering II",
    "Digital Electronics",
    "Effective Writing",
    "Technical Communication",
]

ADMIN_USER = "1002476196"
ADMIN_PWD = "Ahmad@2006"


status_lock = threading.Lock()
run_status: Dict[str, Any] = {"state": "idle", "error": None}


def set_status(state: str, error: str | None = None):
    with status_lock:
        run_status["state"] = state
        run_status["error"] = error


def read_cfg() -> Dict[str, Any]:
    try:
        import json
        cfg_path = Path("config/config.json")
        if not cfg_path.exists():
            return {}
        with cfg_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_cfg(data: Dict[str, Any]) -> None:
    cfg_path = Path("config/config.json")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    with cfg_path.open("w", encoding="utf-8") as f:
        import json as _json
        _json.dump(data, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    # Default to the admin manage interface instead of auto attendance
    return redirect(url_for("manage"))


@app.route("/auto", methods=["GET"]) 
def auto():
    cfg = read_cfg()
    # Defaults mirroring desktop GUI
    page_data = {
        "url": str(cfg.get("url", "")),
        "loc_mode": "browser",
        "lat": str(PRESETS["building_c"]["latitude"]),
        "lon": str(PRESETS["building_c"]["longitude"]),
        "acc": str(PRESETS["building_c"].get("accuracy", 10)),
        "headless": (os.getenv("HEADLESS", "0") in ("1", "true", "True")),
        "parallel": int(cfg.get("parallel_browsers", 0) or 0),
        "cf_mode": str((cfg.get("cloudflare") or {}).get("handle_challenge", "auto")),
        "prep_shot_delay": int(((cfg.get("screenshots") or {}).get("delay_ms_before_prepared", 10000)) / 1000),
        "status": run_status,
    }
    return render_template("auto.html", data=page_data)


def build_config_from_form(form) -> Dict[str, Any]:
    base = read_cfg() or {}
    base["url"] = str(form.get("url", "")).strip()
    try:
        base["parallel_browsers"] = int(form.get("parallel", "0") or 0)
    except Exception:
        base["parallel_browsers"] = 0
    base["open_output_dir_after_run"] = True
    # Cloudflare
    base["cloudflare"] = {
        "handle_challenge": str(form.get("cf_mode", "auto")).strip() or "auto",
        "timeout_ms": int((base.get("cloudflare") or {}).get("timeout_ms", 20000)),
        "after_check_delay_ms": int((base.get("cloudflare") or {}).get("after_check_delay_ms", 1500)),
    }
    # Geo
    mode = str(form.get("loc_mode", "browser"))
    if mode == "browser":
        base["geolocation"] = {
            "source": "browser",
            "require_browser": True,
            "wait_ms": int((base.get("geolocation") or {}).get("wait_ms", 4000)),
        }
    else:
        try:
            lat = float(form.get("lat", "0") or 0)
            lon = float(form.get("lon", "0") or 0)
        except Exception:
            raise ValueError("Please enter numeric values for latitude/longitude.")
        try:
            acc = int(float(form.get("acc", "10") or 10))
        except Exception:
            acc = 10
        base["geolocation"] = {
            "source": "fixed",
            "latitude": lat,
            "longitude": lon,
            "accuracy": acc,
        }
    # Screenshots config
    shots = (base.get("screenshots") or {})
    try:
        shots["delay_ms_before_prepared"] = int(form.get("prep_shot_delay", "10") or 10) * 1000
    except Exception:
        shots["delay_ms_before_prepared"] = int(shots.get("delay_ms_before_prepared", 3000))
    base["screenshots"] = shots
    return base


@app.route("/auto/run", methods=["POST"]) 
def auto_run():
    # HEADLESS from checkbox
    os.environ["HEADLESS"] = "1" if request.form.get("headless") == "on" else "0"
    try:
        cfg = build_config_from_form(request.form)
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("auto"))

    # Persist updated config
    try:
        write_cfg(cfg)
    except Exception:
        pass

    def worker():
        try:
            set_status("running")
            # Lazy import bot only when automation is triggered
            try:
                from bot import run_bot as _run_bot
            except Exception:
                import sys
                from pathlib import Path as P
                sys.path.append(str(P(__file__).resolve().parent))
                from bot import run_bot as _run_bot
            _run_bot(cfg)
            set_status("done")
        except Exception as e:  # noqa
            set_status("error", str(e))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    flash("Started automation in background.", "info")
    return redirect(url_for("auto"))


@app.route("/add", methods=["GET", "POST"]) 
def add_user():
    if request.method == "GET":
        return render_template("add.html")
    # POST
    username = (request.form.get("username") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    sid = (request.form.get("studentId") or "").strip()
    pwd = (request.form.get("password") or "").strip()
    if not sid or not pwd:
        flash("Student ID and Password are required.", "error")
        return redirect(url_for("add_user"))
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    pendings: List[Dict[str, Any]] = list(cfg.get("pending_users", []) or [])
    # Prevent duplicates across both lists
    if any(u.get("studentId") == sid for u in users) or any(p.get("studentId") == sid for p in pendings):
        flash("Student ID already exists (in users or pending).", "error")
        return redirect(url_for("add_user"))
    pendings.append({"studentId": sid, "password": pwd, "username": username, "phone": phone, "subjects": []})
    cfg["pending_users"] = pendings
    write_cfg(cfg)
    flash("Request submitted. Awaiting admin approval.", "success")
    return redirect(url_for("add_user"))


@app.route("/manage", methods=["GET"]) 
def manage():
    authed = bool(session.get("admin", False))
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    pendings: List[Dict[str, Any]] = list(cfg.get("pending_users", []) or [])
    subjects_library: List[str] = list(cfg.get("subjects", []) or [])
    # Seed default subjects into the library once if empty
    if not subjects_library:
        subjects_library = list(DEFAULT_SUBJECTS)
        cfg["subjects"] = subjects_library
        try:
            write_cfg(cfg)
        except Exception:
            pass
    view = (request.args.get("view") or "req").strip()
    if view not in ("req", "users"):
        view = "req"
    return render_template("manage.html", authed=authed, users=users, pendings=pendings, subjects_library=subjects_library, view=view)


@app.route("/manage/login", methods=["POST"]) 
def manage_login():
    user = (request.form.get("admin_user") or "").strip()
    pwd = (request.form.get("admin_pwd") or "").strip()
    if user == ADMIN_USER and pwd == ADMIN_PWD:
        session["admin"] = True
        flash("Admin access granted.", "success")
    else:
        session["admin"] = False
        flash("Invalid admin credentials.", "error")
    return redirect(url_for("manage"))


def require_admin() -> bool:
    return bool(session.get("admin", False))


@app.route("/manage/add", methods=["POST"]) 
def manage_add():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    pwd = (request.form.get("password") or "").strip()
    if not sid or not pwd:
        flash("Student ID and Password are required.", "error")
        return redirect(url_for("manage"))
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    if any(u.get("studentId") == sid for u in users):
        flash("Student ID already exists.", "error")
        return redirect(url_for("manage"))
    users.append({"studentId": sid, "password": pwd})
    cfg["users"] = users
    write_cfg(cfg)
    flash("User added.", "success")
    return redirect(url_for("manage"))


@app.route("/manage/update", methods=["POST"]) 
def manage_update():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    pwd = (request.form.get("password") or "").strip()
    username = (request.form.get("username") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    if not sid:
        flash("Student ID is required.", "error")
        return redirect(url_for("manage", view="users"))
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    updated = False
    for u in users:
        if u.get("studentId") == sid:
            if pwd:
                u["password"] = pwd
            if username:
                u["username"] = username
            if phone:
                u["phone"] = phone
            updated = True
            break
    if not updated:
        flash("Student ID not found.", "error")
        return redirect(url_for("manage", view="users"))
    cfg["users"] = users
    write_cfg(cfg)
    flash("Password updated.", "success")
    return redirect(url_for("manage", view="users"))


@app.route("/manage/delete", methods=["POST"]) 
def manage_delete():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    users = [u for u in users if u.get("studentId") != sid]
    cfg["users"] = users
    write_cfg(cfg)
    flash("User deleted.", "success")
    return redirect(url_for("manage", view="users"))

# --- Pending approvals ---
@app.route("/manage/approve", methods=["POST"]) 
def manage_approve():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    pendings: List[Dict[str, Any]] = list(cfg.get("pending_users", []) or [])
    # Find pending
    idx = None
    for i, p in enumerate(pendings):
        if p.get("studentId") == sid:
            idx = i
            break
    if idx is None:
        flash("Pending request not found.", "error")
        return redirect(url_for("manage"))
    # Move to users if not duplicate
    if any(u.get("studentId") == sid for u in users):
        flash("Student already exists.", "error")
        return redirect(url_for("manage"))
    user = pendings.pop(idx)
    users.append({
        "studentId": user.get("studentId"),
        "password": user.get("password"),
        "username": user.get("username"),
        "phone": user.get("phone"),
        # احفظ معرف التلغرام إن توفر ليُستخدم في إرسال صورة التوثيق لاحقًا
        "telegram_chat_id": user.get("telegram_chat_id"),
        "subjects": list(user.get("subjects", []) or []),
    })
    cfg["users"] = users
    cfg["pending_users"] = pendings
    write_cfg(cfg)
    # Notify the user via Telegram if chat id is known
    try:
        chat_id = user.get("telegram_chat_id")
        token = os.getenv("TELEGRAM_TOKEN")
        if chat_id and token:
            text = (
                f"Your account request has been approved.\n"
                f"Student ID: {user.get('studentId','')}\n"
                f"You can now create or receive preparations."
            )
            api_url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urlencode({"chat_id": int(chat_id), "text": text}).encode("utf-8")
            req = Request(api_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                urlopen(req, timeout=5).read()
            except Exception:
                pass
    except Exception:
        pass
    flash("User approved.", "success")
    return redirect(url_for("manage"))


@app.route("/manage/reject", methods=["POST"]) 
def manage_reject():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    cfg = read_cfg()
    pendings: List[Dict[str, Any]] = list(cfg.get("pending_users", []) or [])
    new_p = [p for p in pendings if p.get("studentId") != sid]
    cfg["pending_users"] = new_p
    write_cfg(cfg)
    flash("User rejected.", "success")
    return redirect(url_for("manage"))

# --- Subject management ---
@app.route("/manage/subject/add", methods=["POST"]) 
def manage_subject_add():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    subject = (request.form.get("subject") or "").strip()
    if not subject:
        flash("Subject is required.", "error")
        return redirect(url_for("manage"))
    # Ensure subject exists in global library
    cfg = read_cfg()
    lib: List[str] = list(cfg.get("subjects", []) or [])
    if subject not in lib:
        lib.append(subject)
        cfg["subjects"] = lib
        write_cfg(cfg)
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    found = False
    for u in users:
        if u.get("studentId") == sid:
            subs = list(u.get("subjects", []) or [])
            if subject not in subs:
                subs.append(subject)
            u["subjects"] = subs
            found = True
            break
    if not found:
        flash("Student ID not found.", "error")
        return redirect(url_for("manage"))
    cfg["users"] = users
    write_cfg(cfg)
    flash("Subject added.", "success")
    return redirect(url_for("manage"))


@app.route("/manage/subject/remove", methods=["POST"]) 
def manage_subject_remove():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage"))
    sid = (request.form.get("studentId") or "").strip()
    subject = (request.form.get("subject") or "").strip()
    cfg = read_cfg()
    users: List[Dict[str, Any]] = list(cfg.get("users", []) or [])
    found = False
    for u in users:
        if u.get("studentId") == sid:
            subs = [s for s in list(u.get("subjects", []) or []) if s != subject]
            u["subjects"] = subs
            found = True
            break
    if not found:
        flash("Student ID not found.", "error")
        return redirect(url_for("manage"))
    cfg["users"] = users
    write_cfg(cfg)
    flash("Subject removed.", "success")
    return redirect(url_for("manage"))

# --- Global subjects library management ---
@app.route("/manage/subjects/add", methods=["POST"]) 
def manage_subjects_add_global():
    if not require_admin():
        flash("Admin login required.", "error")
        return redirect(url_for("manage", view="users"))
    subject = (request.form.get("subject") or "").strip()
    if not subject:
        flash("Subject name is required.", "error")
        return redirect(url_for("manage", view="users"))
    cfg = read_cfg()
    lib: List[str] = list(cfg.get("subjects", []) or [])
    if subject not in lib:
        lib.append(subject)
        cfg["subjects"] = lib
        write_cfg(cfg)
        flash("Subject added to library.", "success")
    else:
        flash("Subject already exists in library.", "info")
    return redirect(url_for("manage", view="users"))


@app.route("/status")
def status():
    return {"state": run_status.get("state"), "error": run_status.get("error")}


def _host():
    # Bind to all interfaces by default so devices on LAN or tunnels can reach it
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    return host, port


if __name__ == "__main__":
    h, p = _host()
    dbg = (os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True"))
    app.run(host=h, port=p, debug=dbg, use_reloader=False)