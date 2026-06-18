# page_cache.py
import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional

from appdir import APP_DIR

PAGE_CACHE_ROOT = APP_DIR / "page_cache"
PAGE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_MB = 500


def _cache_dir(file_path: Path) -> Path:
    key = hashlib.md5(str(file_path).encode()).hexdigest()
    return PAGE_CACHE_ROOT / key


def _meta_path(cache_dir: Path) -> Path:
    return cache_dir / "meta.json"


def get_cached_names(file_path: Path) -> Optional[list[str]]:
    d = _cache_dir(file_path)
    meta_file = _meta_path(d)
    if not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        if meta.get("mtime") != file_path.stat().st_mtime:
            return None
        return meta.get("original_names") or meta.get("pages", [])
    except Exception:
        return None


def has_cached_pages(file_path: Path) -> bool:
    """キャッシュの存在確認のみ。bytesを読み込まないので高速・低メモリ。"""
    d = _cache_dir(file_path)
    meta_file = _meta_path(d)
    if not meta_file.exists():
        return False
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        if meta.get("mtime") != file_path.stat().st_mtime:
            return False
        return bool(meta.get("pages"))
    except Exception:
        return False


def get_cached_paths(file_path: Path) -> Optional[list[Path]]:
    """キャッシュ済みページをPathリストで返す。bytesを読まないのでメモリ節約。"""
    d = _cache_dir(file_path)
    meta_file = _meta_path(d)
    if not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        if meta.get("mtime") != file_path.stat().st_mtime:
            return None
        pages_names = meta.get("pages", [])
        if not pages_names:
            return None
        paths = []
        for name in pages_names:
            p = d / name
            if not p.exists():
                return None
            paths.append(p)
        return paths
    except Exception:
        return None


def get_cached_pages(file_path: Path) -> Optional[list[bytes]]:
    d = _cache_dir(file_path)
    meta_file = _meta_path(d)
    if not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        if meta.get("mtime") != file_path.stat().st_mtime:
            return None
        pages_names = meta.get("pages", [])
        if not pages_names:
            return None
        result = []
        for name in pages_names:
            p = d / name
            if not p.exists():
                return None
            result.append(p.read_bytes())
        return result
    except Exception:
        return None


def save_cached_pages(file_path: Path, pages: list[bytes],
                      max_mb: int = DEFAULT_MAX_MB,
                      original_names: list[str] | None = None,
                      on_done=None):
    """
    全ページをキャッシュに保存する。
    元がJPEGならそのまま保存、それ以外はJPEG変換して保存。
    on_done: 保存完了時に呼ばれるコールバック（引数なし）
    """
    if not pages:
        return
    d = _cache_dir(file_path)
    try:
        from PIL import Image
        import io as _io
        d.mkdir(parents=True, exist_ok=True)
        page_names = []
        for i, data in enumerate(pages):
            if data[:2] == b'\xff\xd8':
                name = f"{i:04d}.jpg"
                (d / name).write_bytes(data)
            else:
                name = f"{i:04d}.jpg"
                try:
                    img = Image.open(_io.BytesIO(data))
                    img.load()
                    if img.mode in ('RGBA', 'P'):
                        bg = Image.new('RGB', img.size, (255, 255, 255))
                        bg.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                        img = bg
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    buf = _io.BytesIO()
                    img.save(buf, 'JPEG', quality=92, optimize=True)
                    (d / name).write_bytes(buf.getvalue())
                except Exception:
                    name = f"{i:04d}.bin"
                    (d / name).write_bytes(data)
            page_names.append(name)
        meta = {
            "mtime": file_path.stat().st_mtime,
            "source": str(file_path),
            "pages": page_names,
            "original_names": original_names or page_names,
        }
        _meta_path(d).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        _evict_old_caches(max_mb)
        if on_done:
            on_done()
    except Exception as e:
        print(f"[page_cache] 保存エラー: {e}")
        shutil.rmtree(d, ignore_errors=True)


def invalidate_cache(file_path: Path):
    d = _cache_dir(file_path)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def get_cache_size_mb() -> float:
    total = sum(
        f.stat().st_size
        for f in PAGE_CACHE_ROOT.rglob("*")
        if f.is_file()
    )
    return total / (1024 * 1024)


def _evict_old_caches(max_mb: int):
    if get_cache_size_mb() <= max_mb:
        return
    dirs = [d for d in PAGE_CACHE_ROOT.iterdir() if d.is_dir()]
    dirs.sort(key=lambda d: d.stat().st_atime)
    for d in dirs:
        if get_cache_size_mb() <= max_mb * 0.9:
            break
        shutil.rmtree(d, ignore_errors=True)
