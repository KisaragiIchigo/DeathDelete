import os
import sys
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTextEdit, QProgressBar, QMessageBox, QStyle,
    QInputDialog, QLineEdit
)

import hashlib
import ctypes
from ctypes import wintypes 

# ===== UI 定数 =====
APP_TITLE: str = "DeathDelete セットアップ ©️2025 KisaragiIchigo"
UI_FONT_FAMILY: str = "メイリオ"
RESIZE_MARGIN: int = 8

# ===== 実行ファイル名 / 対象名（同一フォルダに配置想定） =====
EXE_KEY_CL  = "encryption_key.exe"  # Step2: secret.key を生成
EXE_DELSET  = "delset.exe"          # Step3: 設定GUI（移動しない）

SRC_MAIN    = "MainApp.exe"
SRC_DELETE  = "DeleteApp.exe"
SRC_KEY     = "secret.key"

# 暗号化ターゲットパスのファイル名（出力先= delset.exe と同一フォルダ）
TARGET_PATH_ENC = "yummy_target.enc"

BATCH_NAME  = "このパッチを管理者権限で実行してください.bat"

# ===== QSS（簡素） =====
QSS = """
QWidget { background: #111827; color: #e5e7eb; font-size: 12px; }
QPushButton {
  background: #4169e1; color: white; border: none; padding: 8px 12px; border-radius: 10px;
}
QPushButton:hover { background: #7000e0; }
QPushButton:disabled { background: #4b5563; color: #9ca3af; }
QLabel#title { font-size: 14px; font-weight: bold; color: #ffffff; }
QTextEdit { background: #0b1220; border: 1px solid #374151; border-radius: 8px; }
QProgressBar { border:1px solid #374151; border-radius:6px; text-align:center; background:#0b1220; color:#e5e7eb; }
QProgressBar::chunk { background:#4169e1; border-radius:6px; }
"""

# ===== パスユーティリティ =====
def app_dir() -> Path:
    # setup.exe / setup.pyw のいる場所（＝delset.exe と同じフォルダ想定）
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def here(*names: str) -> Path:
    return app_dir().joinpath(*names)

def exists_here(name: str) -> bool:
    return here(name).exists()

def run_and_wait(path: Path) -> int:
    if not path.exists():
        return 127
    if path.suffix.lower() == ".bat":
        proc = subprocess.Popen(["cmd", "/c", str(path)], cwd=str(path.parent))
    else:
        proc = subprocess.Popen([str(path)], cwd=str(path.parent))
    proc.wait()
    return int(proc.returncode)

# ===== ハッシュ＆環境変数 =====
def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _set_user_env_var(name: str, value: str) -> int:
    try:
        completed = subprocess.run(["setx", name, value], check=False,
                                   capture_output=True, text=True)
        return completed.returncode
    except Exception:
        return 1

# ===== Windows DPAPI（ユーザースコープ）で文字列を暗号化 =====
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]

CRYPTPROTECT_UI_FORBIDDEN = 0x01

def _to_blob(b: bytes) -> DATA_BLOB:
    blob = DATA_BLOB()
    blob.cbData = len(b)
    blob.pbData = ctypes.cast(ctypes.create_string_buffer(b), ctypes.POINTER(ctypes.c_char))
    return blob

def dpapi_protect_text(s: str) -> bytes:
    CryptProtectData = ctypes.windll.crypt32.CryptProtectData
    CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)
    ]
    CryptProtectData.restype = wintypes.BOOL
    in_blob = _to_blob(s.encode("utf-8"))
    out_blob = DATA_BLOB()
    if not CryptProtectData(ctypes.byref(in_blob), None, None, None, None,
                            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)

def generate_batch_content(dest_dir: Path) -> str:
    app_path = dest_dir / "MainApp.exe"
    tr_quoted = f"\\\"{app_path}\\\""
    return f"""@echo off

:: ■ 1. MainApp.exeを一度だけ即時実行
echo "MainApp.exe" を起動します...
start "" "{app_path}"

:: 少し待機
timeout /t 3 > nul

:: ■ 2.3日(72時間)ごとに実行するタスクを登録
schtasks /Create /TN "MainApp_Recurring_Task" /TR "{tr_quoted}" /SC DAILY /MO 3 /F

echo.
echo 全ての処理が完了しました。
pause
"""

# ===== メインウィンドウ =====
class SetupWindow(QWidget):
    """
    一括実行: ①→②→【移動】→③→⑤
    ① パス→ハッシュ→環境変数
    ② encryption_key.exe（secret.key 生成）
    【移動】 MainApp/DeleteApp/secret.key を移動 ＋（★）yummy_target.enc を “delset.exe と同じフォルダ” に出力
    ③ delset.exe（移動先で yummy.ini を生成/更新）
    ⑤ バッチ生成
    """
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(700, 460)

        # タイトル行
        title_row = QHBoxLayout()
        title_lbl = QLabel(APP_TITLE); title_lbl.setObjectName("title")
        btn_min = QPushButton("🗕"); btn_min.setFixedSize(28, 28); btn_min.clicked.connect(self.showMinimized)
        btn_cls = QPushButton("ｘ"); btn_cls.setFixedSize(28, 28); btn_cls.clicked.connect(self.close)
        title_row.addWidget(title_lbl); title_row.addStretch(); title_row.addWidget(btn_min); title_row.addWidget(btn_cls)

        # 上段
        top_row = QHBoxLayout()
        self.btn_choose = QPushButton("移動先フォルダを選択")
        self.btn_run    = QPushButton("一括実行（1→2→移動→3→バッチ）"); self.btn_run.setEnabled(False)
        self.lbl_dest   = QLabel("未選択"); self.lbl_dest.setStyleSheet("color:#93c5fd;")
        top_row.addWidget(self.btn_choose); top_row.addWidget(self.btn_run)

        # 進捗・ログ
        self.prog = QProgressBar(); self.prog.setRange(0, 100); self.prog.setValue(0)
        self.log  = QTextEdit(); self.log.setReadOnly(True); self.log.setMinimumHeight(220)

        # 個別実行ボタン
        ops_row = QHBoxLayout()
        self.btn_step1 = QPushButton("① パス→ハッシュ→環境変数")
        self.btn_step2 = QPushButton("② encryption_key 実行")
        self.btn_move  = QPushButton("②.5 移動（Main/Delete/secret.key）")  # ②と③の間
        self.btn_step3 = QPushButton("③ delset 実行")
        self.btn_make  = QPushButton("⑤ バッチ生成")
        for b in (self.btn_step1, self.btn_step2, self.btn_move, self.btn_step3, self.btn_make):
            ops_row.addWidget(b)

        # レイアウト
        root = QVBoxLayout(self); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(10)
        root.addLayout(title_row); root.addLayout(top_row)
        root.addWidget(self.lbl_dest); root.addWidget(self.prog)
        root.addWidget(self.log, 1);  root.addLayout(ops_row)

        # シグナル
        self.btn_choose.clicked.connect(self._choose_dest)
        self.btn_run.clicked.connect(self._run_all)
        self.btn_step1.clicked.connect(self._run_step1)
        self.btn_step2.clicked.connect(self._run_step2)
        self.btn_move.clicked.connect(self._move_files)
        self.btn_step3.clicked.connect(self._run_step3)
        self.btn_make.clicked.connect(self._make_batch)

        # 初期チェック
        missing = [n for n in (EXE_KEY_CL, EXE_DELSET, SRC_MAIN, SRC_DELETE) if not exists_here(n)]
        if missing:
            self._err(f"同じフォルダに必要ファイルが見つかりません: {', '.join(missing)}")
        else:
            self._ok("準備完了。移動先フォルダを選択してください。")

        # スタイル
        self.setStyleSheet(QSS)
        if here("setup.ico").exists():
            self.setWindowIcon(QIcon(str(here("setup.ico"))))
        else:
            self.setWindowIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        # フレームレス
        self._moving = False; self._resizing = False
        self._drag_offset = QPoint(); self.installEventFilter(self)

    # ===== ログ =====
    def _log(self, s: str) -> None:  self.log.append(s)
    def _ok(self, s: str) -> None:   self.log.append("✅ " + s)
    def _warn(self, s: str) -> None: self.log.append("⚠️ " + s)
    def _err(self, s: str) -> None:  self.log.append("❌ " + s)

    # ===== 選択 =====
    def _choose_dest(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "移動先フォルダを選択")
        if d:
            self.dest = Path(d)
            self.lbl_dest.setText(str(self.dest)); self.btn_run.setEnabled(True)
            self._ok(f"移動先: {self.dest}")

    # ===== Step1: パス→ハッシュ→環境変数 =====
    def _run_step1(self) -> int:
        self._step(5)
        self._log(">> Step1: パス入力 → SHA-256 生成 → PASSWORD_HASH をユーザー環境変数に登録")
        pw1, ok1 = QInputDialog.getText(self, "パスワード入力", "パスワード:", QLineEdit.Password)
        if not ok1: self._warn("キャンセルされました。"); return 1
        pw2, ok2 = QInputDialog.getText(self, "パスワード再入力", "パスワード（再）:", QLineEdit.Password)
        if not ok2: self._warn("キャンセルされました。"); return 1
        if pw1 != pw2 or pw1 == "": self._err("未入力または一致しません。"); return 2
        h = _sha256_hex(pw1); QApplication.clipboard().setText(h)
        rc = _set_user_env_var("PASSWORD_HASH", h)
        if rc == 0: self._ok("PASSWORD_HASH をユーザー環境変数に登録しました。（新しいプロセスで有効）"); self._log(f"<< ハッシュ: {h}")
        else: self._err("環境変数の登録に失敗しました。権限/ポリシーをご確認ください。")
        return rc

    # ===== Step2: encryption_key.exe =====
    def _run_step2(self) -> int:
        self._step(15)
        self._log(">> Step2: encryption_key.exe（通常は secret.key を生成）")
        rc = run_and_wait(here(EXE_KEY_CL))
        if not exists_here(SRC_KEY):
            self._warn("secret.key が見つかりません。出力場所をご確認ください。")
        self._log(f"<< 終了: {EXE_KEY_CL} (ExitCode={rc})")
        return rc

    # ===== ②.5: 移動 ＋ yummy_target.enc を “自フォルダ” に作成 =====
    def _move_files(self) -> None:
        self._step(40)
        if not hasattr(self, "dest"):
            QMessageBox.warning(self, "未選択", "移動先フォルダを選択してください。"); return
        need = [SRC_MAIN, SRC_DELETE, SRC_KEY]
        miss = [n for n in need if not exists_here(n)]
        if miss:
            self._err("移動元が不足しています: " + ", ".join(miss))
            QMessageBox.warning(self, "不足", "必要ファイルが不足しています。"); return

        self.dest.mkdir(parents=True, exist_ok=True)

        # 上書き前掃除（移動先）
        for n in need:
            dst = self.dest / n
            if dst.exists():
                try: dst.unlink()
                except Exception as e: self._warn(f"上書きのため既存を削除できませんでした: {dst} ({e})")

        # 移動
        for n in need:
            src = here(n); dst = self.dest / n
            shutil.move(str(src), str(dst))
            self._ok(f"移動完了: {n} -> {dst}")

        # ★ DPAPI で“移動先パス”を暗号化 → 【delset.exe と同じフォルダ】に yummy_target.enc を出力
        try:
            enc = dpapi_protect_text(str(self.dest))
            (app_dir() / TARGET_PATH_ENC).write_bytes(enc)
            self._ok(f"{TARGET_PATH_ENC} を {app_dir()} に作成（暗号化済）")
        except Exception as e:
            self._err(f"{TARGET_PATH_ENC} の作成に失敗しました: {e}")

        self._step(55)

    # ===== Step3: delset.exe =====
    def _run_step3(self) -> int:
        self._step(60)
        self._log(">> Step3: delset.exe（設定を保存して閉じてください）")
        rc = run_and_wait(here(EXE_DELSET))
        self._log(f"<< 終了: {EXE_DELSET} (ExitCode={rc})")
        return rc

    # ===== ⑤ バッチ生成 =====
    def _make_batch(self) -> None:
        self._step(90)
        if not hasattr(self, "dest"):
            QMessageBox.warning(self, "未選択", "移動先フォルダを選択してください。"); return
        bat_text = generate_batch_content(self.dest)
        bat_path = app_dir() / BATCH_NAME
        bat_path.write_text(bat_text, encoding="cp932", errors="ignore")
        self._ok(f"生成: {bat_path}")
        self._step(100)
        QMessageBox.information(self, "完了", f"生成しました:\n{bat_path}\n\n右クリック→管理者として実行 してください。")

    # ===== 一括実行（①→②→【移動】→③→⑤） =====
    def _run_all(self) -> None:
        try:
            self.btn_run.setEnabled(False)
            self._step(0)
            self._run_step1(); self._step(20)
            self._run_step2(); self._step(35)
            self._move_files(); self._step(55)   # ← ここで enc を自フォルダへ出力
            self._run_step3(); self._step(85)
            self._make_batch(); self._step(100)
        except PermissionError:
            self._err("権限が不足しています。管理者として実行するか、移動先を変更してください。")
        except Exception as e:
            self._err(f"想定外エラー: {e}")
            QMessageBox.critical(self, "エラー", str(e))
        finally:
            self.btn_run.setEnabled(True)

    def _step(self, v: int) -> None:
        self.prog.setValue(v); QApplication.processEvents()

    # ===== フレームレス移動/リサイズ =====
    def eventFilter(self, obj, e) -> bool:
        if obj is self:
            if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                pos = e.position().toPoint()
                if self._edge_at(pos):
                    self._resizing = True
                    self._resize_edges = self._edge_at(pos)
                    self._start_geo = self.geometry()
                    self._start_mouse = e.globalPosition().toPoint()
                else:
                    self._moving = True
                    self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            elif e.type() == QEvent.MouseMove:
                if self._resizing:
                    self._resize_to(e.globalPosition().toPoint()); return True
                if self._moving and (e.buttons() & Qt.LeftButton):
                    self.move(e.globalPosition().toPoint() - self._drag_offset); return True
                self._update_cursor(self._edge_at(e.position().toPoint())); return False
            elif e.type() == QEvent.MouseButtonRelease:
                self._moving = False; self._resizing = False; self.unsetCursor(); return True
        return super().eventFilter(obj, e)

    def _edge_at(self, pos) -> str:
        m = RESIZE_MARGIN; r = self.rect(); edges = ""
        if pos.y() <= m: edges += "T"
        if pos.y() >= r.height() - m: edges += "B"
        if pos.x() <= m: edges += "L"
        if pos.x() >= r.width() - m: edges += "R"
        return edges

    def _update_cursor(self, edges: str) -> None:
        if edges in ("TL", "BR"): self.setCursor(Qt.SizeFDiagCursor)
        elif edges in ("TR", "BL"): self.setCursor(Qt.SizeBDiagCursor)
        elif edges in ("L", "R"): self.setCursor(Qt.SizeHorCursor)
        elif edges in ("T", "B"): self.setCursor(Qt.SizeVerCursor)
        else: self.unsetCursor()

    def _resize_to(self, gpos) -> None:
        dx = gpos.x() - self._start_mouse.x()
        dy = gpos.y() - self._start_mouse.y()
        geo = self._start_geo
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        if "L" in self._resize_edges:
            new_w = max(self.minimumWidth(), w - dx); x += (w - new_w); w = new_w
        if "R" in self._resize_edges: w = max(self.minimumWidth(), w + dx)
        if "T" in self._resize_edges:
            new_h = max(self.minimumHeight(), h - dy); y += (h - new_h); h = new_h
        if "B" in self._resize_edges: h = max(self.minimumHeight(), h + dy)
        self.setGeometry(x, y, w, h)

# ===== エントリーポイント =====
def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont(UI_FONT_FAMILY, 10))
    w = SetupWindow()
    if here("setup.ico").exists():
        w.setWindowIcon(QIcon(str(here("setup.ico"))))
    else:
        w.setWindowIcon(w.style().standardIcon(QStyle.SP_ComputerIcon))
    w.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
