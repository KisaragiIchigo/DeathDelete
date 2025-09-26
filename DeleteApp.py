import os
import shutil
import stat
import ctypes
from cryptography.fernet import Fernet
import configparser
import sys

# --- スクリプト自身の場所を基準にパスを定義 ---
if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(script_dir, "yummy.ini")
KEY_FILE = os.path.join(script_dir, "secret.key")

# --- 設定読み込み・復号 ---
def load_key():
    if not os.path.exists(KEY_FILE):
        return None
    try:
        with open(KEY_FILE, "rb") as key_file:
            return key_file.read()
    except:
        return None

def decrypt_data(encrypted_data, key):
    if not key or not encrypted_data:
        return None
    try:
        f = Fernet(key)
        return f.decrypt(encrypted_data).decode("utf-8")
    except:
        return None

def get_deletion_list():
    key = load_key()
    if not key or not os.path.exists(CONFIG_FILE):
        return []
    try:
        with open(CONFIG_FILE, "rb") as f:
            encrypted_data = f.read()
        decrypted_string = decrypt_data(encrypted_data, key)
        if not decrypted_string:
            return []
        config = configparser.ConfigParser()
        config.read_string(decrypted_string)
        if config.has_section("Paths") and config.has_option("Paths", "list"):
            path_list_str = config.get("Paths", "list")
            return [p for p in path_list_str.splitlines() if p.strip()]
    except:
        return []
    return []

# --- 削除関連 ---
def remove_readonly_win_api(path):
    try:
        FILE_ATTRIBUTE_NORMAL = 0x80
        ctypes.windll.kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL)
    except:
        pass

def onerror(func, path, exc_info):
    try:
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWUSR)
            remove_readonly_win_api(path)
            func(path)
    except:
        pass

def delete_item(path):
    try:
        normalized = os.path.normpath(path)
        if not os.path.exists(normalized):
            return
        if os.path.isfile(normalized) or os.path.islink(normalized):
            os.remove(normalized)
        elif os.path.isdir(normalized):
            shutil.rmtree(normalized, onerror=onerror)
    except:
        pass

# --- メイン処理 ---
if __name__ == "__main__":
    for item in get_deletion_list():
        delete_item(item)
