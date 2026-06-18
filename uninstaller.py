"""
Comic Viewer Uninstaller
uac_admin=True でビルドするため、起動時に自動でUAC昇格を要求する。
"""
import sys
import os
import shutil
import winreg
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

APP_NAME = "Comic Viewer"
REG_KEY  = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\ComicViewer"


def _csidl(n: int) -> Path:
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(0, n, 0, 0, buf)
    return Path(buf.value)


def get_startmenu_programs() -> Path:
    return _csidl(0x0017)   # CSIDL_COMMON_PROGRAMS


def get_common_desktop() -> Path:
    return _csidl(0x0019)   # CSIDL_COMMON_DESKTOPDIRECTORY


def get_cache_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "comic_viewer" if local else None


def read_registry() -> dict:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY) as k:
            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
            return {"install_dir": Path(loc)}
    except Exception:
        return {}


def remove_shortcuts_and_registry(install_dir: Path):
    sm   = get_startmenu_programs()
    desk = get_common_desktop()

    for lnk in [
        sm   / f"{APP_NAME}.lnk",
        sm   / f"Uninstall {APP_NAME}.lnk",
        desk / f"{APP_NAME}.lnk",
    ]:
        try:
            if lnk.exists():
                lnk.unlink()
        except Exception:
            pass

    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY)
    except Exception:
        subprocess.run(
            ["reg", "delete", f"HKLM\\{REG_KEY}", "/f"],
            capture_output=True
        )


def schedule_folder_deletion(install_dir: Path):
    """
    uninstall.exe 自身が install_dir 内で動いているため、
    Python プロセス終了後に PowerShell で削除する。
    2 秒のディレイで確実にプロセスが終了してから削除。
    """
    cmd = (
        f"Start-Sleep -Seconds 2; "
        f"Remove-Item -LiteralPath '{install_dir}' "
        f"-Recurse -Force -ErrorAction SilentlyContinue"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd]
    )


class UninstallWindow:
    BG     = "#F5F5F5"
    ACCENT = "#C62828"

    def __init__(self, install_dir: Path):
        self.install_dir = install_dir
        self.root = tk.Tk()
        self.root.title(f"Uninstall {APP_NAME}")
        self.root.geometry("440x270")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG)
        self._build_ui()
        self.root.mainloop()

    def _build_ui(self):
        # ヘッダー
        hdr = tk.Frame(self.root, bg=self.ACCENT, height=60)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text=f"  Uninstall {APP_NAME}",
            bg=self.ACCENT, fg="white", font=("Segoe UI", 13, "bold")
        ).pack(side=tk.LEFT, padx=20, pady=12)

        body = tk.Frame(self.root, bg=self.BG, padx=24, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text=f"This will remove {APP_NAME} from:\n{self.install_dir}",
            bg=self.BG, font=("Segoe UI", 9), justify=tk.LEFT
        ).pack(anchor=tk.W)

        tk.Frame(body, bg="#DDDDDD", height=1).pack(fill=tk.X, pady=10)

        # キャッシュ削除オプション
        cache_dir = get_cache_dir()
        self.clear_cache = tk.BooleanVar(value=False)
        cb_text = "Also delete user data (cache, settings, reading progress)"
        if cache_dir:
            cb_text += f"\n  {cache_dir}"
        tk.Checkbutton(
            body, text=cb_text,
            variable=self.clear_cache,
            bg=self.BG, font=("Segoe UI", 9),
            activebackground=self.BG,
            justify=tk.LEFT, wraplength=380
        ).pack(anchor=tk.W)

        # ボタン行
        btn_row = tk.Frame(self.root, bg="#E8E8E8", pady=10)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Button(
            btn_row, text="  Cancel  ",
            command=self.root.destroy,
            relief=tk.FLAT, bg="#E0E0E0", font=("Segoe UI", 9)
        ).pack(side=tk.RIGHT, padx=10)

        tk.Button(
            btn_row, text="  Uninstall  ",
            command=self._run,
            relief=tk.FLAT, bg=self.ACCENT, fg="white",
            font=("Segoe UI", 9, "bold"),
            activebackground="#B71C1C", activeforeground="white"
        ).pack(side=tk.RIGHT, padx=4)

    def _run(self):
        # 1. ショートカット・レジストリ削除（ロックされていないものを先に削除）
        remove_shortcuts_and_registry(self.install_dir)

        # 2. キャッシュ削除（任意）
        if self.clear_cache.get():
            cache_dir = get_cache_dir()
            if cache_dir and cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)

        # 3. インストールフォルダ削除をPowerShellに委譲してプロセス終了
        #    （uninstall.exe 自身が install_dir 内で動いているため直接削除不可）
        schedule_folder_deletion(self.install_dir)

        messagebox.showinfo(
            "Uninstall",
            f"{APP_NAME} has been uninstalled.\n\n"
            "The installation folder will be removed shortly."
        )
        self.root.destroy()


if __name__ == "__main__":
    info = read_registry()
    if not info:
        messagebox.showerror(
            "Error",
            f"{APP_NAME} does not appear to be installed\n"
            "(registry entry not found)."
        )
        sys.exit(1)

    UninstallWindow(info["install_dir"])
