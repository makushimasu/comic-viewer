# appdir.py — アプリデータディレクトリの共通定義
import os
import sys
from pathlib import Path


def _resolve_app_dir() -> Path:
    if sys.platform == "win32":
        # %LOCALAPPDATA%\comic_viewer  (AppData\Local — 非表示フォルダ)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "comic_viewer"
    # Linux / macOS: 既存ユーザーとの互換性のため ~/comic_viewer を維持
    return Path.home() / "comic_viewer"


APP_DIR: Path = _resolve_app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)
