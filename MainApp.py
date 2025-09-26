import os
import subprocess
import time
import threading
import customtkinter as ctk
import sys
from win32com.client import Dispatch
import configparser
from cryptography.fernet import Fernet
from tkinter import messagebox
import ctypes
import hashlib  

# ====== ハッシュ関数 ======
def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# ====== パスワードチェック ======
# - ユーザー環境変数 PASSWORD_HASH に設定されたハッシュと照合する
def check_password(user_input: str) -> bool:
    env_pw_hash = os.getenv("PASSWORD_HASH", "").strip()
    if not env_pw_hash:
        # ハッシュ未設定は“設定ミス”として扱う（メッセージ表示は起動側で実施）
        return False
    return _sha256_hex(user_input) == env_pw_hash


class CustomPasswordDialog(ctk.CTkToplevel):
    def __init__(self, delete_callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("パスワード入力")
        self.lift(); self.focus_force(); self.grab_set()
        self.geometry("400x240"); self.resizable(False, False)

        self._close_attempts = 0
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self._delete_callback = delete_callback
        self._attempts = 0; self._max_attempts = 3
        self._auth_success = False
        self.grid_columnconfigure(0, weight=1)

        self._label = ctk.CTkLabel(self, text="パスワードを入力してください:", font=("メイリオ", 14))
        self._label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        entry_frame = ctk.CTkFrame(self, fg_color="transparent"); entry_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        entry_frame.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(entry_frame, show="*", font=("メイリオ", 12))
        self._entry.grid(row=0, column=0, sticky="ew")
        self._entry.bind("<Return>", self._ok_event); self._entry.focus()

        self._password_visible_var = ctk.IntVar(value=0)
        self._view_checkbox = ctk.CTkCheckBox(entry_frame, text="表示", font=("メイリオ", 12),
                                              variable=self._password_visible_var, command=self._toggle_password_visibility)
        self._view_checkbox.grid(row=0, column=1, padx=(10, 0))

        self._status_label = ctk.CTkLabel(self, text="", font=("メイリオ", 12), text_color="yellow", wraplength=360)
        self._status_label.grid(row=2, column=0, padx=20, pady=5, sticky="w")

        button_frame = ctk.CTkFrame(self, fg_color="transparent"); button_frame.grid(row=3, column=0, padx=20, pady=(10, 20), sticky="e")
        self._ok_button = ctk.CTkButton(button_frame, text="OK", command=self._ok_event, font=("メイリオ", 12))
        self._ok_button.pack(side="right")

    def _toggle_password_visibility(self):
        self._entry.configure(show="" if self._password_visible_var.get() == 1 else "*")

    def _on_closing(self):
        self._close_attempts += 1
        if self._close_attempts >= 3:
            self._delete_callback()
            self.destroy()

    def _ok_event(self, event=None):
        user_input = self._entry.get()
        if check_password(user_input):
            self._status_label.configure(text="認証に成功しました。", text_color="lightgreen")
            self._auth_success = True
            self._ok_button.configure(state="disabled"); self._entry.configure(state="disabled")
            self.after(600, self.destroy)
        else:
            self._attempts += 1
            remaining = self._max_attempts - self._attempts
            self._entry.delete(0, "end")
            if remaining > 0:
                self._status_label.configure(text=f"パスワードが違います。残り試行回数: {remaining}回", text_color="orange")
            else:
                self._status_label.configure(text="セキュリティ解除を実行します。", text_color="lightgreen")
                self._ok_button.configure(state="disabled")
                self.after(400, self._delete_callback)
                self.after(2000, self.destroy)

    def get_result(self):
        self.master.wait_window(self)
        return self._auth_success


# --- ここから下は元ロジック（パスワードの扱いのみ変更） ---
if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
    self_path = os.path.basename(sys.executable).lower().endswith('.exe') and sys.executable or os.path.join(script_dir, "main_script.pyw")
    if not isinstance(self_path, str):  # 保険
        self_path = sys.executable
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    self_path = os.path.abspath(__file__)

CONFIG_FILE = os.path.join(script_dir, "yummy.ini")
KEY_FILE = os.path.join(script_dir, "secret.key")

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

def load_key():
    if not os.path.exists(KEY_FILE): return None
    try:
        with open(KEY_FILE, "rb") as key_file: return key_file.read()
    except: return None

def decrypt_data(encrypted_data, key):
    if not key or not encrypted_data: return None
    try:
        f = Fernet(key); return f.decrypt(encrypted_data).decode('utf-8')
    except: return None

def get_delete_script_path():
    key = load_key()
    if not key or not os.path.exists(CONFIG_FILE): return None
    config = configparser.ConfigParser()
    try:
        with open(CONFIG_FILE, 'rb') as f: encrypted_data = f.read()
        decrypted_string = decrypt_data(encrypted_data, key)
        if not decrypted_string: return None
        config.read_string(decrypted_string); return config.get('Settings', 'delete_script_path', fallback=None)
    except Exception: return None

delete_script_path = get_delete_script_path()
timeout_occurred = False

try:
    shell = Dispatch('WScript.Shell')
    startup_folder = shell.SpecialFolders('Startup')
    main_script_shortcut = os.path.join(startup_folder, "MainAppAuth.lnk")
    delete_script_shortcut = os.path.join(startup_folder, "DeleteApp.lnk")
except Exception:
    startup_folder = None; main_script_shortcut = None; delete_script_shortcut = None

def create_shortcut(target, shortcut_path):
    if not shortcut_path: return
    target = os.path.normpath(target)
    target_dir = os.path.dirname(target)
    if not os.path.exists(target_dir): os.makedirs(target_dir, exist_ok=True)
    try:
        shell = Dispatch('WScript.Shell'); shortcut = shell.CreateShortCut(shortcut_path)
        ext = os.path.splitext(target)[1].lower()
        if ext == '.exe': shortcut.TargetPath = target; shortcut.Arguments = ""; shortcut.IconLocation = target
        elif ext == '.pyw': shortcut.TargetPath = sys.executable.replace("python.exe", "pythonw.exe"); shortcut.Arguments = f'"{target}"'; shortcut.IconLocation = shortcut.TargetPath
        else: shortcut.TargetPath = sys.executable; shortcut.Arguments = f'"{target}"'; shortcut.IconLocation = sys.executable
        shortcut.WorkingDirectory = target_dir; shortcut.save()
    except Exception as e:
        messagebox.showerror("ショートカット作成エラー", f"ショートカットの作成に失敗しました:\n\n{e}")

def get_task_run_command(script_path):
    script_path = os.path.normpath(script_path)
    ext = os.path.splitext(script_path)[1].lower()
    if ext == '.exe': return f'"{script_path}"'
    elif ext == '.pyw': return f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{script_path}"'
    else: return f'"{sys.executable}" "{script_path}"'

def register_task(task_name, script_to_run):
    command = get_task_run_command(script_to_run)
    schtasks_command = ['schtasks', '/Create', '/TN', task_name, '/TR', command, '/SC', 'ONLOGON', '/F', '/RL', 'HIGHEST']
    try:
        subprocess.run(schtasks_command, check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except subprocess.CalledProcessError as e:
        messagebox.showwarning("タスク登録失敗", f"タスク '{task_name}' の登録に失敗しました。代替手段を試みます。\n\n{e.stderr}")
        return False

def delete_task(task_name):
    schtasks_command = ['schtasks', '/Delete', '/TN', task_name, '/F']
    try:
        subprocess.run(schtasks_command, check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except subprocess.CalledProcessError: return False

def delete_script_execution():
    if not delete_task("MainAppAuthTask"):
        if main_script_shortcut and os.path.exists(main_script_shortcut):
            try: os.remove(main_script_shortcut)
            except: pass
    if delete_script_path and os.path.exists(delete_script_path):
        if not register_task("DeleteAppTask", delete_script_path):
            create_shortcut(delete_script_path, delete_script_shortcut)
        delete_task("MainApp_OnLogon_Task")
        delete_task("MainApp_Recurring_Task") 
    ext = os.path.splitext(delete_script_path)[1].lower()
    command = []
    if ext == '.exe': command = [delete_script_path]
    elif ext == '.pyw': command = [sys.executable.replace("python.exe", "pythonw.exe"), delete_script_path]
    else: command = [sys.executable, delete_script_path]
    flags = subprocess.CREATE_NO_WINDOW if ext == '.py' else 0
    subprocess.Popen(command, creationflags=flags)
    time.sleep(5)

def timeout_function():
    # 259200秒 = 72時間
    global timeout_occurred
    time.sleep(259200)
    if not timeout_occurred:
        timeout_occurred = True; delete_script_execution(); app.quit()

if __name__ == "__main__":
    # 先に PASSWORD_HASH の存在チェック（未設定なら明確に案内）
    if not os.getenv("PASSWORD_HASH"):
        root = ctk.CTk(); root.withdraw()
        messagebox.showerror(
            "設定エラー",
            "PASSWORD_HASH が環境変数に設定されていません。\n"
            "Setup の ①『パス→ハッシュ→環境変数』を実行し、\n"
            "新しいPowerShell/コマンドプロンプトで再実行してください。"
        )
        sys.exit(2)

    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

    if not delete_script_path:
        root = ctk.CTk(); root.withdraw()
        messagebox.showerror("致命的なエラー", f"削除用スクリプトのパスが設定されていません。\n'{CONFIG_FILE}'を確認してください。")
        sys.exit()

    app = ctk.CTk(); app.withdraw()
    ctk.set_appearance_mode("dark"); ctk.set_default_color_theme("blue")

    timeout_thread = threading.Thread(target=timeout_function, daemon=True); timeout_thread.start()

    # ダイアログに「delete_script_execution」を渡す（×3回等で実行）
    dialog = CustomPasswordDialog(delete_script_execution)
    auth_successful = dialog.get_result()

    if auth_successful:
        timeout_occurred = True
        if not register_task("MainAppAuthTask", self_path):
            create_shortcut(self_path, main_script_shortcut)
            if delete_script_shortcut and os.path.exists(delete_script_shortcut):
                try: os.remove(delete_script_shortcut)
                except: pass
            delete_task("DeleteAppTask")
    else:
        sys.exit()

    app.mainloop()
