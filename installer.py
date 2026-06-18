"""
Comic Viewer GUI Installer
PyInstaller --onefile でビルドして使う。
dist/ComicViewer フォルダを datas としてバンドルし、
sys._MEIPASS/ComicViewer からインストール先にコピーする。
"""
import sys
import os
import shutil
import ctypes
import winreg
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME    = "Comic Viewer"
APP_VERSION = "1.0.0"
APP_EXE     = "ComicViewer.exe"
REG_KEY     = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\ComicViewer"

# ---------------------------------------------------------------------------
# 管理者権限
# ---------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def elevate():
    exe = sys.executable
    args = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    sys.exit(0)

# ---------------------------------------------------------------------------
# パスユーティリティ
# ---------------------------------------------------------------------------

def _csidl(csidl: int) -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf)
    return Path(buf.value)

def get_program_files() -> Path:
    return _csidl(0x0026)   # CSIDL_PROGRAM_FILES

def get_startmenu_programs() -> Path:
    return _csidl(0x0017)   # CSIDL_COMMON_PROGRAMS  (All Users)

def get_common_desktop() -> Path:
    return _csidl(0x0019)   # CSIDL_COMMON_DESKTOPDIRECTORY (All Users)

def source_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ComicViewer"
    return Path(__file__).parent / "dist" / "ComicViewer"

# ---------------------------------------------------------------------------
# ショートカット / レジストリ
# ---------------------------------------------------------------------------

def create_shortcut(lnk: Path, target: str, working_dir: str, icon: str = ""):
    ps = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{lnk}"); '
        f'$s.TargetPath = "{target}"; '
        f'$s.WorkingDirectory = "{working_dir}"; '
    )
    if icon:
        ps += f'$s.IconLocation = "{icon}"; '
    ps += '$s.Save()'
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True
    )

def register_uninstall(install_dir: Path, uninstall_cmd: str):
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0, winreg.KEY_WRITE
    ) as k:
        def sv(name, val, typ=winreg.REG_SZ):
            winreg.SetValueEx(k, name, 0, typ, val)
        sv("DisplayName",     APP_NAME)
        sv("DisplayVersion",  APP_VERSION)
        sv("Publisher",       APP_NAME)
        sv("InstallLocation", str(install_dir))
        sv("UninstallString", uninstall_cmd)
        sv("DisplayIcon",     str(install_dir / APP_EXE) + ",0")
        sv("NoModify",        1, winreg.REG_DWORD)
        sv("NoRepair",        1, winreg.REG_DWORD)
        try:
            kb = sum(
                f.stat().st_size for f in install_dir.rglob("*") if f.is_file()
            ) // 1024
            sv("EstimatedSize", kb, winreg.REG_DWORD)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# GUIインストーラー
# ---------------------------------------------------------------------------

class SetupWindow:
    ACCENT = "#1565C0"
    BG     = "#F5F5F5"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {APP_VERSION} Setup")
        self.root.geometry("540x430")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG)
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        pf = get_program_files()
        self.install_dir    = tk.StringVar(value=str(pf / APP_NAME))
        self.want_startmenu = tk.BooleanVar(value=True)
        self.want_desktop   = tk.BooleanVar(value=False)
        self._installing    = False

        self._build_ui()
        self.root.mainloop()

    # ---- UI構築 ----

    def _build_ui(self):
        # ヘッダー
        hdr = tk.Frame(self.root, bg=self.ACCENT, height=72)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text=f"  {APP_NAME}  Setup",
            bg=self.ACCENT, fg="white", font=("Segoe UI", 15, "bold")
        ).pack(side=tk.LEFT, padx=20, pady=15)
        tk.Label(
            hdr, text=f"v{APP_VERSION}",
            bg=self.ACCENT, fg="#90CAF9", font=("Segoe UI", 10)
        ).pack(side=tk.RIGHT, padx=20)

        body = tk.Frame(self.root, bg=self.BG, padx=28, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        # インストール先
        tk.Label(
            body, text="Installation Folder:",
            bg=self.BG, font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W)
        row = tk.Frame(body, bg=self.BG)
        row.pack(fill=tk.X, pady=(3, 14))
        self._entry = tk.Entry(
            row, textvariable=self.install_dir,
            font=("Segoe UI", 9), relief=tk.SOLID, bd=1
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            row, text=" Browse... ", command=self._browse,
            relief=tk.FLAT, bg="#E0E0E0", font=("Segoe UI", 9)
        ).pack(side=tk.LEFT, padx=(6, 0))

        self._divider(body)

        # オプション
        tk.Label(
            body, text="Options:",
            bg=self.BG, font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(8, 3))
        tk.Checkbutton(
            body, text="Create Start Menu shortcuts",
            variable=self.want_startmenu,
            bg=self.BG, font=("Segoe UI", 9), activebackground=self.BG
        ).pack(anchor=tk.W)
        tk.Checkbutton(
            body, text="Create Desktop shortcut",
            variable=self.want_desktop,
            bg=self.BG, font=("Segoe UI", 9), activebackground=self.BG
        ).pack(anchor=tk.W)

        self._divider(body)

        # 進捗
        self.status_var = tk.StringVar(value="Ready to install.")
        tk.Label(
            body, textvariable=self.status_var,
            bg=self.BG, font=("Segoe UI", 9), fg="#555"
        ).pack(anchor=tk.W, pady=(10, 2))
        self.pb = ttk.Progressbar(body, length=480, mode="determinate")
        self.pb.pack(fill=tk.X)

        # ボタン行
        btn_row = tk.Frame(self.root, bg="#E8E8E8", pady=10)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)
        self.btn_cancel = tk.Button(
            btn_row, text="  Cancel  ", command=self.root.destroy,
            relief=tk.FLAT, bg="#E0E0E0", font=("Segoe UI", 9)
        )
        self.btn_cancel.pack(side=tk.RIGHT, padx=10)
        self.btn_install = tk.Button(
            btn_row, text="  Install  ", command=self._install,
            relief=tk.FLAT, bg=self.ACCENT, fg="white",
            font=("Segoe UI", 9, "bold"), activebackground="#0D47A1",
            activeforeground="white"
        )
        self.btn_install.pack(side=tk.RIGHT, padx=4)

    def _divider(self, parent):
        tk.Frame(parent, bg="#DDDDDD", height=1).pack(fill=tk.X, pady=4)

    # ---- 操作 ----

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.install_dir.get())
        if d:
            self.install_dir.set(os.path.normpath(d))

    def _step(self, msg: str, pct: int):
        self.status_var.set(msg)
        self.pb["value"] = pct
        self.root.update()

    def _install(self):
        if self._installing:
            return
        self._installing = True
        self.btn_install.config(state=tk.DISABLED)
        self.btn_cancel.config(state=tk.DISABLED)
        self._entry.config(state=tk.DISABLED)

        install_dir = Path(self.install_dir.get())
        src = source_dir()

        if not src.exists():
            messagebox.showerror("Error", f"Source not found:\n{src}")
            self._fail()
            return

        try:
            # ファイルコピー
            self._step("Removing previous installation...", 5)
            if install_dir.exists():
                shutil.rmtree(install_dir)

            self._step("Copying files  (this may take a moment)...", 10)
            shutil.copytree(src, install_dir)

            # アンインストーラー (exe) をコピー
            self._step("Installing uninstaller...", 65)
            sm    = get_startmenu_programs()
            desk  = get_common_desktop()

            # uninstall.exe は installer の隣 (frozen) か dist/ 以下 (開発時)
            if getattr(sys, "frozen", False):
                u_src = Path(sys._MEIPASS) / "uninstall.exe"
            else:
                u_src = Path(__file__).parent / "dist" / "uninstall.exe"

            u_exe = install_dir / "uninstall.exe"
            if u_src.exists():
                shutil.copy2(u_src, u_exe)
            else:
                u_exe = None   # uninstall.exe がなければスキップ

            # レジストリ登録 (コントロールパネル)
            self._step("Registering in Programs and Features...", 72)
            uninstall_cmd = f'"{u_exe}"' if u_exe else ""
            register_uninstall(install_dir, uninstall_cmd)

            target  = str(install_dir / APP_EXE)
            workdir = str(install_dir)
            icon    = target + ",0"

            # スタートメニュー
            if self.want_startmenu.get():
                self._step("Creating Start Menu shortcuts...", 82)
                sm.mkdir(parents=True, exist_ok=True)
                create_shortcut(sm / f"{APP_NAME}.lnk", target, workdir, icon)
                if u_exe:
                    create_shortcut(
                        sm / f"Uninstall {APP_NAME}.lnk",
                        str(u_exe), workdir
                    )

            # デスクトップ
            if self.want_desktop.get():
                self._step("Creating Desktop shortcut...", 92)
                create_shortcut(desk / f"{APP_NAME}.lnk", target, workdir, icon)

            self._step("Installation complete!", 100)

            if messagebox.askyesno(
                "Setup Complete",
                f"{APP_NAME} v{APP_VERSION} was installed successfully.\n\nLaunch now?"
            ):
                subprocess.Popen([target])
            self.root.destroy()

        except PermissionError:
            messagebox.showerror(
                "Permission Denied",
                f"Cannot write to:\n  {install_dir}\n\n"
                "Run Setup as Administrator, or choose a different folder."
            )
            self._fail()
        except Exception as e:
            messagebox.showerror("Installation Error", str(e))
            self._fail()

    def _fail(self):
        self._step("Installation failed.", 0)
        self._installing = False
        self.btn_install.config(state=tk.NORMAL)
        self.btn_cancel.config(state=tk.NORMAL)
        self._entry.config(state=tk.NORMAL)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if sys.platform != "win32":
        print("Windows only.")
        sys.exit(1)
    if not is_admin():
        elevate()
    SetupWindow()
