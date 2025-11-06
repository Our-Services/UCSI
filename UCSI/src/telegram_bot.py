import os
import logging
import threading
from typing import Any, Dict, List

from pathlib import Path

# Import bot functions
try:
    from bot import run_bot, load_config
except Exception:
    import sys
    from pathlib import Path as P
    sys.path.append(str(P(__file__).resolve().parent))
    from bot import run_bot, load_config

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram._webappinfo import WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


status_lock = threading.Lock()
run_status: Dict[str, Any] = {"state": "idle", "error": None}

def _subjects_library() -> List[str]:
    """Read subjects library from config; seed defaults once if empty."""
    cfg = read_cfg()
    # Normalize subjects: strip whitespace and drop empties
    raw = list((cfg.get("subjects") or []) or [])
    lib = [str(s).strip() for s in raw if str(s).strip()]
    if not lib:
        # Seed initial defaults into the shared library (one-time initialization)
        lib = [
            "Engineering Statics",
            "Mathematical Methods for Engineering II   ",
            "Digital Electronics",
            "Effective Writing",
            "Technical Communication",
        ]
        cfg["subjects"] = lib
        try:
            write_cfg(cfg)
        except Exception:
            pass
    return lib

# إحداثيات تقريبية داخل الحرم؛ يمكن تعديلها لاحقًا
PRESETS = {
    "building_g": {"latitude": 3.0783228, "longitude": 101.7328630, "accuracy": 25},
    "building_c": {"latitude": 3.078617, "longitude": 101.7334, "accuracy": 25},
}


def set_status(state: str, error: str | None = None):
    with status_lock:
        run_status["state"] = state
        run_status["error"] = error


def read_cfg() -> Dict[str, Any]:
    try:
        return load_config("config/config.json")
    except Exception:
        return {}


def write_cfg(data: Dict[str, Any]) -> None:
    cfg_path = Path("config/config.json")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    with cfg_path.open("w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)


def is_allowed(user_id: int) -> bool:
    raw = os.getenv("TELEGRAM_ALLOWED_IDS", "").strip()
    if not raw:
        return True
    try:
        allowed = {int(x.strip()) for x in raw.split(",") if x.strip()}
    except Exception:
        return False
    return user_id in allowed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    # قائمة رئيسية بدون زر فتح الواجهة
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("New Preparation", callback_data="prep_new")],
        [InlineKeyboardButton("New User", callback_data="user_add")],
        [InlineKeyboardButton("Manage Users", callback_data="user_manage")],
        [InlineKeyboardButton("Show Last 10 Preparations", callback_data="history")],
    ])
    await update.message.reply_text(
        "UCSI Attendance Bot\nChoose an action:", reply_markup=kb
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    state = run_status.get("state")
    err = run_status.get("error")
    if err:
        await update.message.reply_text(f"Status: {state}\nError: {err}")
    else:
        await update.message.reply_text(f"Status: {state}")


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Helper to get IDs for TELEGRAM_ALLOWED_IDS
    uid = update.effective_user.id if update.effective_user else None
    cid = update.effective_chat.id if update.effective_chat else None
    msg = ["Your IDs:"]
    if uid is not None:
        msg.append(f"User ID: {uid}")
    if cid is not None:
        msg.append(f"Chat ID: {cid}")
    await update.message.reply_text("\n".join(msg))


def _run_worker(cfg: Dict[str, Any]):
    try:
        set_status("running")
        run_bot(cfg)
        set_status("done")
    except Exception as e:  # noqa
        set_status("error", str(e))


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    if run_status.get("state") == "running":
        await update.message.reply_text("Already running.")
        return
    cfg = read_cfg()
    # Respect HEADLESS env
    os.environ["HEADLESS"] = os.getenv("HEADLESS", "1")
    t = threading.Thread(target=_run_worker, args=(cfg,), daemon=True)
    t.start()
    await update.message.reply_text("Started. Use /status to check progress.")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    uid = q.from_user.id if q.from_user else None
    if uid is None or not is_allowed(uid):
        await q.answer("Access denied.", show_alert=True)
        return
    data = q.data or ""
    if data == "run":
        if run_status.get("state") == "running":
            await q.answer("Already running.", show_alert=False)
            return
        cfg = read_cfg()
        os.environ["HEADLESS"] = os.getenv("HEADLESS", "1")
        t = threading.Thread(target=_run_worker, args=(cfg,), daemon=True)
        t.start()
        await q.answer("Started.")
        await q.message.reply_text("Started. Use /status to check progress.")
    elif data == "status":
        state = run_status.get("state")
        err = run_status.get("error")
        await q.answer("Done.")
        if err:
            await q.message.reply_text(f"Status: {state}\nError: {err}")
        else:
            await q.message.reply_text(f"Status: {state}")
    elif data == "prep_new":
        # ابدأ معالج التحضير الجديد
        prep = context.user_data.get("prep") or {"url": None, "subject": None, "location": "custom"}
        context.user_data["prep"] = prep
        await _show_prep_menu(q, context)
    elif data == "prep_subject_menu":
        # عرض قائمة المواد في رسالة منفصلة
        await _send_subject_menu(q, context)
    elif data.startswith("prep_subject:"):
        subj = data.split(":", 1)[1]
        context.user_data.setdefault("prep", {})["subject"] = subj
        await _show_prep_menu(q, context)
    elif data == "prep_back":
        # Back to preparation menu
        await _show_prep_menu(q, context)
    elif data.startswith("prep_loc:"):
        loc = data.split(":", 1)[1]
        if loc == "custom":
            context.user_data.setdefault("prep", {})["location"] = "custom"
            context.user_data["awaiting"] = "custom_loc"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="prep_back")]])
            await _replace_message(q, context, "Enter coordinates as: lat, lon, acc\nExample: 3.0796, 101.7332, 25", kb)
        elif loc in ("building_g", "building_c"):
            context.user_data.setdefault("prep", {})["location"] = loc
            await _show_prep_menu(q, context)
        else:
            await _show_prep_menu(q, context)
    elif data == "prep_url":
        context.user_data["awaiting"] = "prep_url"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="prep_back")]])
        await _replace_message(q, context, "Send the new preparation URL now:", kb)
    elif data == "prep_start":
        await _start_preparation(q, context)
    elif data == "prep_cancel":
        # Reset to defaults when cancelling/back from preparation menu
        context.user_data["prep"] = {"url": None, "subject": None, "location": "custom"}
        context.user_data["awaiting"] = None
        await _show_main_menu(q, context)
    elif data == "user_add":
        context.user_data["awaiting"] = "add_user_username"
        # ابدأ تجميع بيانات المستخدم الجديد واحفظ معرف التلغرام الخاص به
        nu = {"telegram_chat_id": int(update.effective_chat.id)}
        context.user_data["new_user"] = nu
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        # أرسل الرسالة التمهيدية التي تحتوي على الحقول المطلوبة ثم ابدأ بجمع البيانات
        await _update_summary_message(update, context)
        m = await q.message.reply_text("Send the username:", reply_markup=kb)
        context.user_data["last_prompt_msg_id"] = m.message_id
    elif data == "user_manage":
        context.user_data["awaiting"] = "admin_user"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        await q.edit_message_text("Send the admin username:", reply_markup=kb)
    elif data == "history":
        await _show_history(q)
    elif data in ("m_add", "m_update", "m_delete", "m_list"):
        await _on_manage_button(update, context, data)
    elif data == "back_main":
        await _show_main_menu(q, context)


async def seturl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /seturl <url>")
        return
    url = args[0]
    cfg = read_cfg()
    cfg["url"] = url
    write_cfg(cfg)
    await update.message.reply_text("URL updated.")


async def setheadless(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    args = context.args
    if not args or args[0] not in ("0", "1"):
        await update.message.reply_text("Usage: /setheadless <0|1>")
        return
    os.environ["HEADLESS"] = args[0]
    await update.message.reply_text(f"HEADLESS set to {args[0]}.")


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN not set in environment.")
    app = Application.builder().token(token).build()
    logging.info("Starting Telegram bot polling...")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("run", run))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("seturl", seturl))
    app.add_handler(CommandHandler("setheadless", setheadless))
    app.add_handler(CommandHandler("whoami", whoami))
    # Handle subject selection callbacks first
    app.add_handler(CallbackQueryHandler(on_subject_toggle, pattern=r"^sub_"))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

# -------------------------
# -------------------------
# Submenu helpers
# -------------------------

def _checkmark(selected: bool, label: str) -> str:
    return ("✅ " + label) if selected else ("☑️ " + label)


async def _show_main_menu(q, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("New Preparation", callback_data="prep_new")],
        [InlineKeyboardButton("New User", callback_data="user_add")],
        [InlineKeyboardButton("Manage Users", callback_data="user_manage")],
        [InlineKeyboardButton("Show Last 10 Preparations", callback_data="history")],
    ])
    await _replace_message(q, context, "UCSI Attendance Bot\nChoose an action:", kb)


async def _send_main_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("New Preparation", callback_data="prep_new")],
        [InlineKeyboardButton("New User", callback_data="user_add")],
        [InlineKeyboardButton("Manage Users", callback_data="user_manage")],
        [InlineKeyboardButton("Show Last 10 Preparations", callback_data="history")],
    ])
    await _send_new_menu_after_text(update, context, "UCSI Attendance Bot\nChoose an action:", kb)


async def _show_prep_menu(q, context):
    prep = context.user_data.get("prep") or {}
    url = prep.get("url")
    subject = prep.get("subject")
    loc = prep.get("location", "custom")

    url_label = (url or "— Not set —")
    subj_label = (subject or "— Not selected —")

    rows = [
        [InlineKeyboardButton(f"Add Preparation URL\n{url_label}", callback_data="prep_url")],
        [InlineKeyboardButton(f"Choose Subject\n{subj_label}", callback_data="prep_subject_menu")],
        [
            InlineKeyboardButton(_checkmark(loc == "custom", "Custom Location"), callback_data="prep_loc:custom"),
            InlineKeyboardButton(_checkmark(loc == "building_g", "Block G"), callback_data="prep_loc:building_g"),
            InlineKeyboardButton(_checkmark(loc == "building_c", "Block C"), callback_data="prep_loc:building_c"),
        ],
        [InlineKeyboardButton("Start Preparation / Run All", callback_data="prep_start")],
        [InlineKeyboardButton("Cancel / Back", callback_data="prep_cancel")],
    ]
    kb = InlineKeyboardMarkup(rows)
    await _replace_message(q, context, "New Preparation Setup:", kb)


async def _send_prep_menu_message(update: Update, context):
    # نسخة لإرسال قائمة جديدة بدل تحرير السابقة
    prep = context.user_data.get("prep") or {}
    url = prep.get("url")
    subject = prep.get("subject")
    loc = prep.get("location", "custom")
    url_label = (url or "— Not set —")
    subj_label = (subject or "— Not selected —")
    rows = [
        [InlineKeyboardButton(f"Add Preparation URL\n{url_label}", callback_data="prep_url")],
        [InlineKeyboardButton(f"Choose Subject\n{subj_label}", callback_data="prep_subject_menu")],
        [
            InlineKeyboardButton(_checkmark(loc == "custom", "Custom Location"), callback_data="prep_loc:custom"),
            InlineKeyboardButton(_checkmark(loc == "building_g", "Block G"), callback_data="prep_loc:building_g"),
            InlineKeyboardButton(_checkmark(loc == "building_c", "Block C"), callback_data="prep_loc:building_c"),
        ],
        [InlineKeyboardButton("Start Preparation / Run All", callback_data="prep_start")],
        [InlineKeyboardButton("Cancel / Back", callback_data="prep_cancel")],
    ]
    kb = InlineKeyboardMarkup(rows)
    await _send_new_menu_after_text(update, context, "New Preparation Setup:", kb)


async def _send_subject_menu(q, context):
    # قائمة لاختيار المادة من مكتبة مشتركة
    subs = _subjects_library()
    rows = [[InlineKeyboardButton("📘 " + s, callback_data=f"prep_subject:{s}")] for s in subs]
    rows.append([InlineKeyboardButton("Back", callback_data="prep_back")])
    kb = InlineKeyboardMarkup(rows)
    await _replace_message(q, context, "Select Subject:", kb)

async def _replace_message(q, context, text: str, reply_markup=None):
    try:
        await context.bot.delete_message(chat_id=q.message.chat_id, message_id=q.message.message_id)
    except Exception:
        pass
    new_msg = await context.bot.send_message(chat_id=q.message.chat_id, text=text, reply_markup=reply_markup)
    context.user_data["last_bot_msg_id"] = new_msg.message_id

async def _send_new_menu_after_text(update: Update, context, text: str, reply_markup=None):
    chat_id = update.effective_chat.id
    last_id = context.user_data.get("last_bot_msg_id")
    if last_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=last_id)
        except Exception:
            pass
    new_msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    context.user_data["last_bot_msg_id"] = new_msg.message_id

async def _update_summary_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create or update a registration summary message with entered fields."""
    nu = context.user_data.get("new_user", {})
    subs = list(context.user_data.get("new_user_subjects", set()))
    lines = [
        "Please provide the following fields (all in English):",
        "1) Username",
        "2) Phone",
        "3) Student ID",
        "4) Password",
        "5) Courses",
        "",
        "Registration Info:",
        f"- Username: {nu.get('username','—')}",
        f"- Phone: {nu.get('phone','—')}",
        f"- Student ID: {nu.get('studentId','—')}",
        f"- Password: {nu.get('password','—')}",
        f"- Courses: {(', '.join(subs) if subs else '—')}",
    ]
    msg_id = context.user_data.get("summary_msg_id")
    chat_id = update.effective_chat.id
    text = "\n".join(lines)
    try:
        if msg_id:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        else:
            m = await context.bot.send_message(chat_id=chat_id, text=text)
            context.user_data["summary_msg_id"] = m.message_id
    except Exception:
        m = await context.bot.send_message(chat_id=chat_id, text=text)
        context.user_data["summary_msg_id"] = m.message_id

async def _send_subjects_multiselect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = _subjects_library()
    selected = set(context.user_data.get("new_user_subjects", set()))
    rows: List[List[InlineKeyboardButton]] = []
    for s in subs:
        label = ("✅ " + s) if s in selected else ("☑️ " + s)
        rows.append([InlineKeyboardButton(label, callback_data=f"sub_toggle:{s}")])
    rows.append([InlineKeyboardButton("Confirm ✅📚", callback_data="sub_confirm")])
    await update.message.reply_text("Select courses (toggle) then confirm:", reply_markup=InlineKeyboardMarkup(rows))


async def on_subject_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    uid = q.from_user.id if q.from_user else None
    if uid is None or not is_allowed(uid):
        await q.answer("Access denied.", show_alert=True)
        return
    data = q.data or ""
    if data.startswith("sub_toggle:"):
        s = data.split(":", 1)[1]
        cur = set(context.user_data.get("new_user_subjects", set()))
        if s in cur:
            cur.remove(s)
        else:
            cur.add(s)
        context.user_data["new_user_subjects"] = cur
        await _update_summary_message(update, context)
        # redraw keyboard
        subs = _subjects_library()
        rows: List[List[InlineKeyboardButton]] = []
        for ss in subs:
            label = ("✅ " + ss) if ss in cur else ("☑️ " + ss)
            rows.append([InlineKeyboardButton(label, callback_data=f"sub_toggle:{ss}")])
        rows.append([InlineKeyboardButton("Confirm ✅📚", callback_data="sub_confirm")])
        try:
            await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
        except Exception:
            await q.message.reply_text("Updated selection.", reply_markup=InlineKeyboardMarkup(rows))
        await q.answer()
    elif data == "sub_confirm":
        nu = dict(context.user_data.get("new_user", {}))
        subjects = list(context.user_data.get("new_user_subjects", set()))
        cfg = read_cfg()
        users: List[Dict[str, Any]] = list((cfg.get("users", []) or []))
        pendings: List[Dict[str, Any]] = list((cfg.get("pending_users", []) or []))
        sid_val = nu.get("studentId")
        if any(u.get("studentId") == sid_val for u in users) or any(p.get("studentId") == sid_val for p in pendings):
            await _replace_message(q, context, "Student ID already exists (in users or pending).", None)
        else:
            nu.setdefault("subjects", subjects)
            pendings.append(nu)
            cfg["pending_users"] = pendings
            write_cfg(cfg)
            await _replace_message(q, context, "User request submitted. Awaiting admin approval.", None)
        context.user_data["awaiting"] = None
        await _show_main_menu(q, context)
        await q.answer()


async def _start_preparation(q, context):
    prep = context.user_data.get("prep") or {}
    url = (prep.get("url") or "").strip()
    subject = (prep.get("subject") or "").strip()
    location = prep.get("location", "custom")
    if not url or not subject:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="prep_back")]])
        await _replace_message(q, context, "Please set URL and subject first.", kb)
        return
    cfg = read_cfg()
    # Save initiator chat id to send progress updates only to the creator
    try:
        chat_id = int(q.message.chat.id)
    except Exception:
        chat_id = None
    notify_cfg = dict((cfg.get("notify") or {}))
    if chat_id:
        notify_cfg["initiator_chat_id"] = chat_id
    # Remove milestones: only final completion notification is used
    notify_cfg["milestones"] = []
    cfg["notify"] = notify_cfg
    # حدّث الرابط والموقع
    cfg["url"] = url
    # خزّن المادة المحددة ليتم تصفية المستخدمين بناءً عليها أثناء التحضير
    cfg["selected_subject"] = subject
    if location == "custom":
        custom_geo = (prep.get("custom_geo") or {})
        try:
            lat = float(custom_geo.get("latitude"))
            lon = float(custom_geo.get("longitude"))
            acc = int(float(custom_geo.get("accuracy", 25)))
        except Exception:
            lat = PRESETS.get("building_g", {}).get("latitude")
            lon = PRESETS.get("building_g", {}).get("longitude")
            acc = int(PRESETS.get("building_g", {}).get("accuracy", 25))
        cfg["geolocation"] = {
            "source": "fixed",
            "latitude": lat,
            "longitude": lon,
            "accuracy": acc,
        }
    elif location in ("building_g", "building_c"):
        preset = PRESETS.get(location) or {"latitude": 3.079548, "longitude": 101.733216, "accuracy": 50}
        cfg["geolocation"] = {
            "source": "fixed",
            "latitude": preset.get("latitude"),
            "longitude": preset.get("longitude"),
            "accuracy": int(preset.get("accuracy", 50)),
        }
    elif location == "ip":
        cfg["geolocation"] = {"source": "ip", "accuracy": 50}
    write_cfg(cfg)
    # Run in background thread same as /run
    if run_status.get("state") == "running":
        await _replace_message(q, context, "Already running.", None)
        return
    os.environ["HEADLESS"] = os.getenv("HEADLESS", "1")
    t = threading.Thread(target=_run_worker, args=(cfg,), daemon=True)
    t.start()
    # سجّل في التاريخ
    try:
        from datetime import datetime
        cfg2 = read_cfg()
        hist = list(cfg2.get("history", []) or [])
        hist.append({"subject": subject, "timestamp": datetime.now().isoformat(timespec="seconds"), "url": url})
        cfg2["history"] = hist[-50:]
        write_cfg(cfg2)
    except Exception:
        pass
    await _replace_message(q, context, "Started. Just wait a few seconds..", None)
    # Store the started message id and chat id so the runner can delete it on completion
    try:
        started_id = context.user_data.get("last_bot_msg_id")
        started_chat = q.message.chat.id
        if started_id:
            cfg3 = read_cfg()
            notify3 = dict((cfg3.get("notify") or {}))
            notify3["started_message_id"] = int(started_id)
            notify3["started_message_chat_id"] = int(started_chat)
            cfg3["notify"] = notify3
            write_cfg(cfg3)
    except Exception:
        pass


async def _show_history(q):
    cfg = read_cfg()
    hist = list(cfg.get("history", []) or [])
    last10 = hist[-10:]
    if not last10:
        await q.edit_message_text("No attendance records yet.")
        return
    lines = [f"- {h.get('subject','?')} — {h.get('timestamp','?')}" for h in last10]
    await q.edit_message_text("Last 10 attendances:\n" + "\n".join(lines))


async def _on_manage_button(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    # يفعّل حقول الإدخال المطلوبة لكل عملية
    if code == "m_add":
        context.user_data["awaiting"] = "m_add_sid"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        await update.effective_message.reply_text("[Add] Send Student ID:", reply_markup=kb)
    elif code == "m_update":
        context.user_data["awaiting"] = "m_update_sid"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        await update.effective_message.reply_text("[Update] Send Student ID:", reply_markup=kb)
    elif code == "m_delete":
        context.user_data["awaiting"] = "m_delete_sid"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        await update.effective_message.reply_text("[Delete] Send Student ID:", reply_markup=kb)
    elif code == "m_list":
        users = list((read_cfg().get("users", []) or []))
        if not users:
            await update.effective_message.reply_text("No users found.")
        else:
            msg = "Users list:\n" + "\n".join([f"{u.get('studentId','')} | {u.get('password','')} | {u.get('username','')} | {u.get('phone','')}" for u in users])
            await update.effective_message.reply_text(msg)
        await _send_main_menu_message(update, context)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # يُستخدم لالتقاط المدخلات النصية أثناء التدفق
    if not is_allowed(update.effective_user.id):
        return
    txt = (update.message.text or "").strip()
    awaiting = context.user_data.get("awaiting")
    if awaiting == "prep_url":
        context.user_data.setdefault("prep", {})["url"] = txt
        context.user_data["awaiting"] = None
        await update.message.reply_text("URL saved.")
        await _send_prep_menu_message(update, context)
        return
    if awaiting == "custom_loc":
        # توقع إدخالًا بصيغة: lat, lon, acc أو lat lon acc
        parts = [p.strip() for p in txt.replace(",", " ").split() if p.strip()]
        if len(parts) < 2:
            await update.message.reply_text("Invalid format. Send in the format: lat, lon, acc")
            return
        try:
            lat = float(parts[0])
            lon = float(parts[1])
            acc = int(float(parts[2])) if len(parts) >= 3 else 25
        except Exception:
            await update.message.reply_text("Invalid format. Send in the format: lat, lon, acc")
            return
        prep = context.user_data.setdefault("prep", {})
        prep["custom_geo"] = {"latitude": lat, "longitude": lon, "accuracy": acc}
        prep["location"] = "custom"
        context.user_data["awaiting"] = None
        await update.message.reply_text("Coordinates saved.")
        await _send_prep_menu_message(update, context)
        return
    # إضافة مستخدم جديد
    if awaiting == "add_user_username":
        nu = context.user_data.get("new_user", {})
        nu["username"] = txt
        context.user_data["new_user"] = nu
        # احذف رسالة المطالبة السابقة
        try:
            msg_id = context.user_data.get("last_prompt_msg_id")
            if msg_id:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception:
            pass
        await _update_summary_message(update, context)
        context.user_data["awaiting"] = "add_user_phone"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        m = await update.message.reply_text("Send the phone number:", reply_markup=kb)
        context.user_data["last_prompt_msg_id"] = m.message_id
        return
    if awaiting == "add_user_phone":
        nu = context.user_data.get("new_user", {})
        nu["phone"] = txt
        context.user_data["new_user"] = nu
        # احذف رسالة المطالبة السابقة
        try:
            msg_id = context.user_data.get("last_prompt_msg_id")
            if msg_id:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception:
            pass
        await _update_summary_message(update, context)
        context.user_data["awaiting"] = "add_user_sid"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        m = await update.message.reply_text("Send the student ID:", reply_markup=kb)
        context.user_data["last_prompt_msg_id"] = m.message_id
        return
    if awaiting == "add_user_sid":
        nu = context.user_data.get("new_user", {})
        nu["studentId"] = txt
        context.user_data["new_user"] = nu
        # احذف رسالة المطالبة السابقة
        try:
            msg_id = context.user_data.get("last_prompt_msg_id")
            if msg_id:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception:
            pass
        await _update_summary_message(update, context)
        context.user_data["awaiting"] = "add_user_pwd"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        m = await update.message.reply_text("Send the password:", reply_markup=kb)
        context.user_data["last_prompt_msg_id"] = m.message_id
        return
    if awaiting == "add_user_pwd":
        nu = context.user_data.get("new_user", {})
        nu["password"] = txt
        context.user_data["new_user"] = nu
        # Show subjects multi-select instead of immediate submit
        context.user_data["awaiting"] = "add_user_subjects"
        context.user_data["new_user_subjects"] = set()
        # احذف رسالة المطالبة السابقة
        try:
            msg_id = context.user_data.get("last_prompt_msg_id")
            if msg_id:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception:
            pass
        await _update_summary_message(update, context)
        await _send_subjects_multiselect(update, context)
        return
    # إدارة المستخدمين
    if awaiting == "admin_user":
        context.user_data["_admin_user"] = txt
        context.user_data["awaiting"] = "admin_pwd"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
        await update.message.reply_text("Send the admin password:", reply_markup=kb)
        return
    if awaiting == "admin_pwd":
        admin_user = str(context.user_data.get("_admin_user", ""))
        admin_pwd = txt
        if admin_user == "1002476196" and admin_pwd == "Ahmad@2006":
            context.user_data["awaiting"] = None
            import os as _os
            web_url = _os.getenv("WEB_APP_URL", "http://127.0.0.1:5000/manage")
            await update.message.reply_text("Admin privileges granted. Choose an action:")
            # Telegram requires HTTPS for WebApp. Fallback to opening external link when not HTTPS.
            if str(web_url).lower().startswith("https://"):
                btn = InlineKeyboardButton("Open Admin Panel", web_app=WebAppInfo(web_url))
            else:
                btn = InlineKeyboardButton("Open Admin Panel (opens browser)", url=web_url)
            kb = InlineKeyboardMarkup([
                [btn],
                [InlineKeyboardButton("Back", callback_data="back_main")],
            ])
            await update.message.reply_text("Admin Panel:", reply_markup=kb)
        else:
            context.user_data["awaiting"] = None
            await update.message.reply_text("Invalid admin credentials.")
            await _send_main_menu_message(update, context)
        return
    if awaiting == "m_add_sid":
        context.user_data["m_sid"] = txt
        context.user_data["awaiting"] = "m_add_pwd"
        await update.message.reply_text("Send the password:")
        return
    if awaiting == "m_add_pwd":
        sid = str(context.user_data.get("m_sid", ""))
        pwd = txt
        cfg = read_cfg()
        users = list(cfg.get("users", []) or [])
        if any(u.get("studentId") == sid for u in users):
            await update.message.reply_text("Student ID already exists.")
        else:
            users.append({"studentId": sid, "password": pwd})
            cfg["users"] = users
            write_cfg(cfg)
            await update.message.reply_text("Added.")
        context.user_data["awaiting"] = None
        await _send_main_menu_message(update, context)
        return
    if awaiting == "m_update_sid":
        context.user_data["m_sid"] = txt
        context.user_data["awaiting"] = "m_update_pwd"
        await update.message.reply_text("Send the new password:")
        return
    if awaiting == "m_update_pwd":
        sid = str(context.user_data.get("m_sid", ""))
        pwd = txt
        cfg = read_cfg()
        users = list(cfg.get("users", []) or [])
        updated = False
        for u in users:
            if u.get("studentId") == sid:
                u["password"] = pwd
                updated = True
                break
        if updated:
            cfg["users"] = users
            write_cfg(cfg)
            await update.message.reply_text("Updated.")
        else:
            await update.message.reply_text("Student ID not found.")
        context.user_data["awaiting"] = None
        await _send_main_menu_message(update, context)
        return
    if awaiting == "m_delete_sid":
        sid = txt
        cfg = read_cfg()
        users = [u for u in (cfg.get("users", []) or []) if u.get("studentId") != sid]
        cfg["users"] = users
        write_cfg(cfg)
        await update.message.reply_text("Deleted.")
        context.user_data["awaiting"] = None
        await _send_main_menu_message(update, context)
        return

if __name__ == "__main__":
    main()