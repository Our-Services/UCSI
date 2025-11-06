import os
import json
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

try:
    from bot import run_bot, load_config  # داخل نفس مجلد src
except Exception:
    # دعم التشغيل حين يكون المسار غير مضاف تلقائيًا
    sys.path.append(str(Path(__file__).resolve().parent))
    from bot import run_bot, load_config


# إعدادات افتراضية يمكن تعديلها لاحقًا (ضع الإحداثيات الدقيقة للمباني هنا إن رغبت)
PRESETS = {
    "building_c": {"latitude": 0.0, "longitude": 0.0, "accuracy": 10},
    "building_g": {"latitude": 0.0, "longitude": 0.0, "accuracy": 10},
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UCSI Attendance Bot")
        self.geometry("800x600")
        self.resizable(True, True)

        # Load current config
        try:
            cfg = load_config("config/config.json")
        except Exception:
            cfg = {}

        # App state variables
        self.status_var = tk.StringVar(value="Ready")
        self.admin_authenticated = False

        # Auto Attendance variables
        self.url_var = tk.StringVar(value=str(cfg.get("url", "")))
        self.loc_mode = tk.StringVar(value="browser")  # building_c, building_g, custom, browser
        self.lat_var = tk.StringVar(value=str(PRESETS["building_c"]["latitude"]))
        self.lon_var = tk.StringVar(value=str(PRESETS["building_c"]["longitude"]))
        self.acc_var = tk.StringVar(value=str(PRESETS["building_c"].get("accuracy", 10)))
        self.headless_var = tk.BooleanVar(value=(os.getenv("HEADLESS", "0") in ("1", "true", "True")))
        # 0 means auto: run in parallel for all users
        self.parallel_var = tk.IntVar(value=int(cfg.get("parallel_browsers", 0) or 0))
        self.cf_mode_var = tk.StringVar(value=str((cfg.get("cloudflare") or {}).get("handle_challenge", "auto")))
        # Screenshots: delay before prepared shot (seconds)
        self.prep_shot_delay_var = tk.IntVar(value=int(((cfg.get("screenshots") or {}).get("delay_ms_before_prepared", 10000)) / 1000))

        # Add User variables
        self.new_username_var = tk.StringVar()
        self.new_phone_var = tk.StringVar()
        self.new_sid_var = tk.StringVar()
        self.new_pwd_var = tk.StringVar()

        # Manage Accounts variables
        self.admin_user_var = tk.StringVar()
        self.admin_pwd_var = tk.StringVar()
        self.m_sid_var = tk.StringVar()
        self.m_pwd_var = tk.StringVar()
        self.m_username_var = tk.StringVar()
        self.m_phone_var = tk.StringVar()

        # Build UI
        self._build_ui()

    def _build_ui(self):
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=tk.BOTH, expand=True)

        auto_tab = ttk.Frame(notebook)
        add_tab = ttk.Frame(notebook)
        manage_tab = ttk.Frame(notebook)

        notebook.add(auto_tab, text="Auto Attendance")
        notebook.add(add_tab, text="Add New User")
        notebook.add(manage_tab, text="Manage Accounts")

        self._build_auto_tab(auto_tab)
        self._build_add_user_tab(add_tab)
        self._build_manage_tab(manage_tab)

        # Status bar
        status_frm = ttk.Frame(outer)
        status_frm.pack(fill=tk.X)
        ttk.Separator(status_frm).pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(status_frm, textvariable=self.status_var).pack(side=tk.LEFT, padx=10, pady=6)
        ttk.Label(status_frm, text="AHMAD2039 - 2025").pack(side=tk.RIGHT, padx=10, pady=6)

    def _build_auto_tab(self, frm):
        pad = {"padx": 10, "pady": 8}

        # URL row
        ttk.Label(frm, text="Attendance URL:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.url_var, width=60).grid(row=0, column=1, columnspan=3, sticky="ew", **pad)
        ttk.Button(frm, text="Paste URL", command=self._paste_url).grid(row=0, column=4, sticky="ew", **pad)

        # Location source
        ttk.Label(frm, text="Location Source:").grid(row=1, column=0, sticky="w", **pad)
        rb_c = ttk.Radiobutton(frm, text="Building C", variable=self.loc_mode, value="building_c", command=self._on_loc_change)
        rb_g = ttk.Radiobutton(frm, text="Building G", variable=self.loc_mode, value="building_g", command=self._on_loc_change)
        rb_custom = ttk.Radiobutton(frm, text="Custom", variable=self.loc_mode, value="custom", command=self._on_loc_change)
        rb_browser = ttk.Radiobutton(frm, text="From Browser (Device)", variable=self.loc_mode, value="browser", command=self._on_loc_change)
        rb_c.grid(row=1, column=1, sticky="w", **pad)
        rb_g.grid(row=1, column=2, sticky="w", **pad)
        rb_custom.grid(row=1, column=3, sticky="w", **pad)
        rb_browser.grid(row=1, column=4, sticky="w", **pad)

        # Coordinates
        ttk.Label(frm, text="Latitude (lat):").grid(row=2, column=0, sticky="w", **pad)
        self.lat_entry = ttk.Entry(frm, textvariable=self.lat_var, width=20)
        self.lat_entry.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Longitude (lon):").grid(row=2, column=2, sticky="w", **pad)
        self.lon_entry = ttk.Entry(frm, textvariable=self.lon_var, width=20)
        self.lon_entry.grid(row=2, column=3, sticky="w", **pad)
        ttk.Label(frm, text="Accuracy (m):").grid(row=2, column=4, sticky="w", **pad)
        self.acc_entry = ttk.Entry(frm, textvariable=self.acc_var, width=8)
        self.acc_entry.grid(row=2, column=5, sticky="w", **pad)

        # Exec options
        ttk.Label(frm, text="Execution Options:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Headless", variable=self.headless_var).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Parallel Browsers (0 = Auto):").grid(row=3, column=2, sticky="e", **pad)
        ttk.Spinbox(frm, from_=0, to=20, textvariable=self.parallel_var, width=6).grid(row=3, column=3, sticky="w", **pad)
        ttk.Label(frm, text="Cloudflare:").grid(row=3, column=4, sticky="e", **pad)
        cf_combo = ttk.Combobox(frm, values=["auto", "manual", "off"], textvariable=self.cf_mode_var, width=8)
        cf_combo.grid(row=3, column=5, sticky="w", **pad)

        # Screenshot options
        ttk.Label(frm, text="Screenshot Delay (sec, after prepared):").grid(row=4, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=0, to=30, textvariable=self.prep_shot_delay_var, width=6).grid(row=4, column=1, sticky="w", **pad)

        # Buttons
        self.run_btn = ttk.Button(frm, text="Run", command=self._on_run)
        self.run_btn.grid(row=5, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Exit", command=self.destroy).grid(row=5, column=2, sticky="ew", **pad)

        # Initialize enable/disable fields
        self._on_loc_change()

    def _build_add_user_tab(self, frm):
        pad = {"padx": 10, "pady": 8}

        # Top: Username and Phone
        ttk.Label(frm, text="Username:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.new_username_var, width=30).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Phone:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.new_phone_var, width=18).grid(row=0, column=3, sticky="w", **pad)

        # Separator between name/phone and studentId/password
        ttk.Separator(frm).grid(row=1, column=0, columnspan=4, sticky="ew", **pad)

        # Student ID and Password
        ttk.Label(frm, text="Student ID:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.new_sid_var, width=30).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Password:").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.new_pwd_var, show="*", width=18).grid(row=2, column=3, sticky="w", **pad)

        # Buttons
        ttk.Button(frm, text="Save", command=self._save_new_user).grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Clear", command=self._clear_new_user).grid(row=3, column=2, sticky="ew", **pad)

    def _build_manage_tab(self, frm):
        pad = {"padx": 10, "pady": 8}

        # Admin login pane
        self.manage_container = ttk.Frame(frm)
        self.manage_container.grid(row=0, column=0, sticky="nsew")
        frm.grid_rowconfigure(0, weight=1)
        frm.grid_columnconfigure(0, weight=1)

        login_frame = ttk.LabelFrame(self.manage_container, text="Admin Login")
        login_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(login_frame, text="Admin Username:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(login_frame, textvariable=self.admin_user_var, width=24).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(login_frame, text="Admin Password:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(login_frame, textvariable=self.admin_pwd_var, show="*", width=24).grid(row=0, column=3, sticky="w", **pad)
        ttk.Button(login_frame, text="Login", command=self._admin_login).grid(row=0, column=4, sticky="ew", **pad)

        # Management pane (hidden until login)
        self.admin_area = ttk.LabelFrame(self.manage_container, text="Manage Student Credentials")
        self.admin_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # List of users
        list_frame = ttk.Frame(self.admin_area)
        list_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(list_frame, text="Students:").grid(row=0, column=0, sticky="w", **pad)
        self.users_listbox = tk.Listbox(list_frame, height=10)
        self.users_listbox.grid(row=1, column=0, columnspan=1, sticky="nsew", **pad)
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # Edit area
        edit_frame = ttk.Frame(self.admin_area)
        edit_frame.pack(fill=tk.X, expand=False)
        ttk.Label(edit_frame, text="Student ID:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(edit_frame, textvariable=self.m_sid_var, width=24).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(edit_frame, text="Password:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(edit_frame, textvariable=self.m_pwd_var, width=24).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(edit_frame, text="Name:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(edit_frame, textvariable=self.m_username_var).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(edit_frame, text="Phone:").grid(row=1, column=2, sticky="w", **pad)
        ttk.Label(edit_frame, textvariable=self.m_phone_var).grid(row=1, column=3, sticky="w", **pad)

        ttk.Button(edit_frame, text="Add", command=self._admin_add).grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(edit_frame, text="Update", command=self._admin_update).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(edit_frame, text="Delete", command=self._admin_delete).grid(row=1, column=2, sticky="ew", **pad)
        ttk.Button(edit_frame, text="Refresh", command=self._admin_refresh).grid(row=1, column=3, sticky="ew", **pad)

        self.users_listbox.bind("<<ListboxSelect>>", self._on_user_select)

        # Initially hide admin area until authenticated
        self._set_admin_area_visible(False)
        self._admin_refresh()

    def _on_loc_change(self):
        mode = self.loc_mode.get()
        # حدّث الحقول وفق الاختيار
        editable = mode in ("building_c", "building_g", "custom")
        state = "normal" if editable else "disabled"
        for entry in (self.lat_entry, self.lon_entry, self.acc_entry):
            entry.configure(state=state)

        if mode == "building_c":
            p = PRESETS["building_c"]
            self.lat_var.set(str(p["latitude"]))
            self.lon_var.set(str(p["longitude"]))
            self.acc_var.set(str(p.get("accuracy", 10)))
        elif mode == "building_g":
            p = PRESETS["building_g"]
            self.lat_var.set(str(p["latitude"]))
            self.lon_var.set(str(p["longitude"]))
            self.acc_var.set(str(p.get("accuracy", 10)))
        elif mode == "custom":
            # اترك القيم كما هي ليدخلها المستخدم
            pass
        elif mode == "browser":
            # في وضع المتصفح، لا حاجة لإحداثيات ثابتة
            self.lat_var.set("")
            self.lon_var.set("")
            self.acc_var.set("")

    def _paste_url(self):
        try:
            value = self.clipboard_get()
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Clipboard empty")
            self.url_var.set(value.strip())
            self.status_var.set("URL pasted from clipboard.")
        except Exception:
            messagebox.showerror("Error", "Clipboard is empty or contains unsupported data.")

    # --- Add User actions ---
    def _save_new_user(self):
        sid = self.new_sid_var.get().strip()
        pwd = self.new_pwd_var.get().strip()
        username = self.new_username_var.get().strip()
        phone = self.new_phone_var.get().strip()
        if not sid or not pwd:
            messagebox.showerror("Error", "Student ID and Password are required.")
            return
        users = self._read_users()
        if any(u.get("studentId") == sid for u in users):
            messagebox.showerror("Error", "Student ID already exists.")
            return
        users.append({"studentId": sid, "password": pwd, "username": username, "phone": phone})
        self._write_users(users)
        messagebox.showinfo("Saved", "New user saved successfully.")
        self._clear_new_user()

    def _clear_new_user(self):
        self.new_username_var.set("")
        self.new_phone_var.set("")
        self.new_sid_var.set("")
        self.new_pwd_var.set("")

    # --- Admin manage actions ---
    def _admin_login(self):
        user = self.admin_user_var.get().strip()
        pwd = self.admin_pwd_var.get().strip()
        if user == "1002476196" and pwd == "Ahmad@2006":
            self.admin_authenticated = True
            self._set_admin_area_visible(True)
            messagebox.showinfo("Authenticated", "Admin access granted.")
        else:
            self.admin_authenticated = False
            self._set_admin_area_visible(False)
            messagebox.showerror("Error", "Invalid admin credentials.")

    def _set_admin_area_visible(self, visible: bool):
        # Enable/disable only widgets that support 'state'
        try:
            self._set_children_state(self.admin_area, enabled=visible)
        except Exception:
            pass
        self.admin_area.configure(text=("Manage Student Credentials" if visible else "Manage Student Credentials (Locked)"))

    def _set_children_state(self, container, enabled: bool):
        for child in container.winfo_children():
            try:
                opts = child.configure()
                if isinstance(opts, dict) and ('state' in opts):
                    child.configure(state=('normal' if enabled else 'disabled'))
                # Recurse into nested containers
                if child.winfo_children():
                    self._set_children_state(child, enabled)
            except Exception:
                # Safely ignore widgets not supporting state
                pass

    def _on_user_select(self, event=None):
        try:
            idxs = self.users_listbox.curselection()
            if not idxs:
                return
            idx = idxs[0]
            users = self._read_users()
            if idx < 0 or idx >= len(users):
                return
            self.m_sid_var.set(users[idx].get("studentId", ""))
            self.m_pwd_var.set(users[idx].get("password", ""))
            self.m_username_var.set(users[idx].get("username", ""))
            self.m_phone_var.set(users[idx].get("phone", ""))
        except Exception:
            pass

    def _admin_refresh(self):
        users = self._read_users()
        self.users_listbox.delete(0, tk.END)
        for u in users:
            sid = u.get("studentId", "")
            name = u.get("username", "")
            phone = u.get("phone", "")
            self.users_listbox.insert(tk.END, f"{sid} | {name} | {phone}")

    def _admin_add(self):
        if not self.admin_authenticated:
            messagebox.showerror("Error", "Admin login required.")
            return
        sid = self.m_sid_var.get().strip()
        pwd = self.m_pwd_var.get().strip()
        if not sid or not pwd:
            messagebox.showerror("Error", "Student ID and Password are required.")
            return
        users = self._read_users()
        if any(u.get("studentId") == sid for u in users):
            messagebox.showerror("Error", "Student ID already exists.")
            return
        users.append({"studentId": sid, "password": pwd})
        self._write_users(users)
        self._admin_refresh()
        messagebox.showinfo("Saved", "User added.")

    def _admin_update(self):
        if not self.admin_authenticated:
            messagebox.showerror("Error", "Admin login required.")
            return
        sid = self.m_sid_var.get().strip()
        pwd = self.m_pwd_var.get().strip()
        if not sid or not pwd:
            messagebox.showerror("Error", "Student ID and Password are required.")
            return
        users = self._read_users()
        updated = False
        for u in users:
            if u.get("studentId") == sid:
                u["password"] = pwd
                updated = True
                break
        if not updated:
            messagebox.showerror("Error", "Student ID not found.")
            return
        self._write_users(users)
        self._admin_refresh()
        messagebox.showinfo("Updated", "Password updated.")

    def _admin_delete(self):
        if not self.admin_authenticated:
            messagebox.showerror("Error", "Admin login required.")
            return
        sid = self.m_sid_var.get().strip()
        if not sid:
            messagebox.showerror("Error", "Student ID is required.")
            return
        users = self._read_users()
        new_users = [u for u in users if u.get("studentId") != sid]
        if len(new_users) == len(users):
            messagebox.showerror("Error", "Student ID not found.")
            return
        self._write_users(new_users)
        self._admin_refresh()
        self.m_sid_var.set("")
        self.m_pwd_var.set("")
        messagebox.showinfo("Deleted", "User deleted.")

    # --- Config helpers ---
    def _read_users(self):
        try:
            cfg = load_config("config/config.json")
        except Exception:
            return []
        return list(cfg.get("users", []) or [])

    def _write_users(self, users):
        cfg_path = Path("config/config.json")
        try:
            with cfg_path.open(encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg["users"] = users
        try:
            with cfg_path.open("w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write config: {e}")

    def _build_config(self):
        # ابدأ من الإعداد الحالي ثم طبّق التغييرات
        try:
            base = load_config("config/config.json")
        except Exception:
            base = {}

        base["url"] = self.url_var.get().strip()
        # 0 => auto parallel equal to number of users
        try:
            base["parallel_browsers"] = int(self.parallel_var.get() or 0)
        except Exception:
            base["parallel_browsers"] = 0
        base["open_output_dir_after_run"] = True

        # Cloudflare
        base["cloudflare"] = {
            "handle_challenge": self.cf_mode_var.get().strip() or "auto",
            "timeout_ms": int((base.get("cloudflare") or {}).get("timeout_ms", 20000)),
            "after_check_delay_ms": int((base.get("cloudflare") or {}).get("after_check_delay_ms", 1500)),
        }

        # Geolocation
        mode = self.loc_mode.get()
        if mode == "browser":
            base["geolocation"] = {
                "source": "browser",
                "require_browser": True,
                "wait_ms": int((base.get("geolocation") or {}).get("wait_ms", 4000)),
            }
        else:
            # قيم lat/lon/acc
            try:
                lat = float(self.lat_var.get())
                lon = float(self.lon_var.get())
            except Exception:
                messagebox.showerror("Error", "Please enter numeric values for latitude/longitude.")
                raise
            try:
                acc = int(float(self.acc_var.get()))
            except Exception:
                acc = 10
            base["geolocation"] = {
                "source": "fixed",
                "latitude": lat,
                "longitude": lon,
                "accuracy": acc,
            }

        # Screenshots config: delay before prepared shot
        shots = (base.get("screenshots") or {})
        try:
            shots["delay_ms_before_prepared"] = int(self.prep_shot_delay_var.get()) * 1000
        except Exception:
            shots["delay_ms_before_prepared"] = int(shots.get("delay_ms_before_prepared", 3000))
        base["screenshots"] = shots

        return base

    def _on_run(self):
        # ضبط HEADLESS
        os.environ["HEADLESS"] = "1" if self.headless_var.get() else "0"

        def worker():
            try:
                cfg = self._build_config()
            except Exception:
                self.status_var.set("Failed to build config.")
                return
            try:
                self.status_var.set("Running...")
                self.run_btn.configure(state="disabled")
                run_bot(cfg)
                self.status_var.set("Run complete.")
            except Exception as e:
                self.status_var.set(f"Error occurred: {e}")
                messagebox.showerror("Error", str(e))
            finally:
                self.run_btn.configure(state="normal")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = App()
    app.mainloop()