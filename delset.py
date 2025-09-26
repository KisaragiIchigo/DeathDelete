import sys
import os
import io
import ctypes
from ctypes import wintypes  # 重要
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
from cryptography.fernet import Fernet
import configparser
from pathlib import Path

# ==== 暗号化ターゲットパス ====
TARGET_PATH_ENC = "yummy_target.enc"

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]

CRYPTPROTECT_UI_FORBIDDEN = 0x01

def _from_bytes_to_blob(b: bytes) -> DATA_BLOB:
    blob = DATA_BLOB()
    blob.cbData = len(b)
    blob.pbData = ctypes.cast(ctypes.create_string_buffer(b), ctypes.POINTER(ctypes.c_char))
    return blob

def dpapi_unprotect_to_text(b: bytes) -> str:
    CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
    CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(DATA_BLOB)
    ]
    CryptUnprotectData.restype = wintypes.BOOL
    in_blob = _from_bytes_to_blob(b)
    out_blob = DATA_BLOB()
    ppszDesc = ctypes.c_wchar_p()
    if not CryptUnprotectData(ctypes.byref(in_blob), ctypes.byref(ppszDesc),
                              None, None, None, CRYPTPROTECT_UI_FORBIDDEN,
                              ctypes.byref(out_blob)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)

# ==== 実行基準ディレクトリ（PyInstaller --onefile 対応） ====
def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

# ==== DPAPI で暗号化されたターゲットパスを読む ====
def read_target_dir() -> Path | None:
    p = app_dir() / TARGET_PATH_ENC
    try:
        if p.exists():
            enc = p.read_bytes()
            s = dpapi_unprotect_to_text(enc)
            t = Path(s)
            if t.exists() and t.is_dir():
                return t
    except Exception:
        pass
    return None

# ==== 既定パス（target_dir 優先） ====
_target_dir = read_target_dir()
DEFAULT_CONFIG_PATH = (_target_dir / "yummy.ini") if _target_dir else (app_dir() / "yummy.ini")
DEFAULT_KEY_PATH    = (_target_dir / "secret.key") if _target_dir else (app_dir() / "secret.key")

# グローバル状態
path_list = []
delete_script_path_var = None
app = None
path_type_var = None

def _key_path_candidates():
    """
    secret.key の探索優先順
    1) target_dir/secret.key（最優先）
    2) 実行ディレクトリ（app_dir）/secret.key（フォールバック）
    3) PyInstaller の _MEIPASS（バンドル内）※基本使わないが保険
    """
    cand = [DEFAULT_KEY_PATH, app_dir() / "secret.key"]
    if getattr(sys, "_MEIPASS", None):
        cand.append(Path(sys._MEIPASS) / "secret.key")
    # 重複排除
    uniq = []
    for c in cand:
        if c not in uniq:
            uniq.append(c)
    return uniq

def load_key():
    for kp in _key_path_candidates():
        if kp.exists():
            try:
                with open(kp, "rb") as key_file:
                    return key_file.read()
            except Exception:
                continue
    messagebox.showerror(
        "エラー",
        "暗号化キーファイル 'secret.key' が見つかりません。\n"
        f"検索場所:\n- {DEFAULT_KEY_PATH}\n- {app_dir()/'secret.key'}\n"
        f"{'(バンドル内も確認)' if getattr(sys, '_MEIPASS', None) else ''}\n\n"
        "setup で ②→移動 を実行したか確認してください。"
    )
    return None

def encrypt_data(data, key):
    if not key or not data:
        return None
    return Fernet(key).encrypt(data.encode('utf-8'))

def decrypt_data(encrypted_data, key):
    if not key or not encrypted_data:
        return None
    try:
        return Fernet(key).decrypt(encrypted_data).decode('utf-8')
    except Exception as e:
        print(f"復号に失敗しました: {e}")
        return None

def _config_file_path() -> Path:
    """ yummy.ini の実体パス（target_dir 優先） """
    return DEFAULT_CONFIG_PATH

def load_config():
    key = load_key()
    cfg_path = _config_file_path()
    if not key or not cfg_path.exists():
        return [], ""
    config = configparser.ConfigParser()
    local_path_list = []
    try:
        with open(cfg_path, 'rb') as f:
            encrypted_data = f.read()
        decrypted_string = decrypt_data(encrypted_data, key)
        if not decrypted_string:
            raise ValueError("復号失敗")
        config.read_string(decrypted_string)
        if 'Paths' in config and 'list' in config['Paths']:
            local_path_list = [p for p in config['Paths']['list'].splitlines() if p]
        delete_script_path = config.get('Settings', 'delete_script_path', fallback="")
        return local_path_list, delete_script_path
    except Exception as e:
        print(f"設定の読み込みに失敗: {e}")
        try:
            if cfg_path.exists():
                cfg_path.rename(cfg_path.with_suffix(cfg_path.suffix + ".bak"))
        except Exception:
            pass
        messagebox.showwarning("設定読込失敗", f"{cfg_path.name} の読込に失敗しました。\nバックアップを作成し、新しい設定ファイルを作成します。")
        return [], ""

def save_config():
    key = load_key()
    if not key:
        return
    config = configparser.ConfigParser()
    config['Paths'] = {'list': "\n".join(path_list)}
    config['Settings'] = {'delete_script_path': delete_script_path_var.get()}
    string_io = io.StringIO(); config.write(string_io)
    config_string = string_io.getvalue()

    encrypted_data = encrypt_data(config_string, key)
    if encrypted_data:
        cfg_path = _config_file_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, "wb") as f:
            f.write(encrypted_data)
        print(f"設定を保存しました: {cfg_path}")

def set_delete_script_path():
    path = filedialog.askopenfilename(
        title="削除用スクリプトを選択",
        filetypes=[("実行可能ファイル", "*.pyw *.py *.exe"), ("すべてのファイル", "*.*")]
    )
    if path:
        delete_script_path_var.set(path)

# ===== DnD GUI =====
class CTkinterDnD(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

def add_path_dialog(listbox_widget):
    path = filedialog.askopenfilename(title="追加するファイルを選択") if path_type_var.get() == "file" else filedialog.askdirectory(title="追加するフォルダを選択")
    if path and path not in path_list:
        path_list.append(path); update_listbox(listbox_widget)

def drop(event, listbox_widget):
    dropped_paths = app.tk.splitlist(event.data)
    for path in dropped_paths:
        if os.path.exists(path) and path not in path_list:
            path_list.append(path)
    update_listbox(listbox_widget)

def remove_selected(listbox_widget):
    for i in sorted(listbox_widget.curselection(), reverse=True):
        path_list.pop(i)
    update_listbox(listbox_widget)

def on_closing():
    if messagebox.askokcancel("終了の確認", "設定を保存して終了しますか？"):
        save_config(); app.destroy()

def finish_and_close():
    try:
        save_config()
        messagebox.showinfo("設定完了", "設定を保存して終了します。")
    except Exception as e:
        messagebox.showerror("保存エラー", f"設定の保存に失敗しました:\n{e}")
        return
    app.destroy()

def update_listbox(listbox_widget):
    listbox_widget.delete(0, tk.END)
    for path in sorted(path_list):
        listbox_widget.insert(tk.END, path)

def main():
    global path_type_var, app, delete_script_path_var, _target_dir
    app = CTkinterDnD()
    app.title("削除リスト設定ツール ©️2025 KisaragiIchigo")
    app.geometry("800x620")
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    # 初期ロード
    path_list.clear()
    loaded_paths, loaded_script_path = load_config()
    path_list.extend(loaded_paths)

    # 上部: 出力先インジケータ
    top_info = ctk.CTkFrame(app); top_info.pack(pady=(8, 0), padx=10, fill="x")
    ctk.CTkLabel(
        top_info,
        text=f"現在の設定ファイル出力先: {str(DEFAULT_CONFIG_PATH.parent)}",
        font=("メイリオ", 12)
    ).pack(side="left", padx=6, pady=6)

    # DeleteApp.exe の位置設定
    path_setting_frame = ctk.CTkFrame(app); path_setting_frame.pack(pady=10, padx=10, fill="x")
    ctk.CTkLabel(path_setting_frame, text="DeleteApp.exe のパス(別のところに隠すこと推奨):", font=("メイリオ", 12)).pack(side="left", padx=(5, 0))
    delete_script_path_var = tk.StringVar(value=loaded_script_path)
    path_label = ctk.CTkLabel(path_setting_frame, textvariable=delete_script_path_var, font=("メイリオ", 11), anchor="w", fg_color="#333", corner_radius=5)
    path_label.pack(side="left", padx=5, fill="x", expand=True)
    ctk.CTkButton(path_setting_frame, text="設定", command=set_delete_script_path, font=("メイリオ", 12), width=60).pack(side="right", padx=5)

    # D&D リスト
    list_frame = ctk.CTkFrame(app); list_frame.pack(pady=10, padx=10, fill="both", expand=True)
    ctk.CTkLabel(list_frame, text="ここにファイルやフォルダをドラッグ＆ドロップ", font=("メイリオ", 14), text_color="gray").place(relx=0.5, rely=0.5, anchor="center")
    listbox = tk.Listbox(list_frame, font=("メイリオ", 11), bg="#2B2B2B", fg="white", selectbackground="#1F6AA5", highlightthickness=0, borderwidth=0, selectmode="extended")
    listbox.pack(fill="both", expand=True, padx=1, pady=1); update_listbox(listbox)
    listbox.drop_target_register(DND_FILES); listbox.dnd_bind('<<Drop>>', lambda e: drop(e, listbox))

    # 下段ボタン（終了→保存 の順に右寄せ）
    bottom_frame = ctk.CTkFrame(app); bottom_frame.pack(pady=10, padx=10, fill="x")
    path_type_var = tk.StringVar(value="folder")
    ctk.CTkButton(bottom_frame, text="ファイル/フォルダを追加", command=lambda: add_path_dialog(listbox), font=("メイリオ", 12)).pack(side="left", padx=10)
    ctk.CTkButton(bottom_frame, text="選択項目を削除", command=lambda: remove_selected(listbox), font=("メイリオ", 12)).pack(side="left", padx=10)
    ctk.CTkButton(bottom_frame, text="設定を保存", command=save_config, font=("メイリオ", 12)).pack(side="right", padx=10)
    ctk.CTkButton(bottom_frame, text="設定終了", command=finish_and_close, font=("メイリオ", 12)).pack(side="right", padx=10)
    app.protocol("WM_DELETE_WINDOW", on_closing)
    
    app.mainloop()

if __name__ == "__main__":
    main()
