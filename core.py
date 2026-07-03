# core.py
import io
from pathlib import Path
from PIL import Image
import hashlib

from archive import read_cover, ArchiveError
from appdir import APP_DIR

CACHE_ROOT = APP_DIR / "thumb_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def safe_open_image(data: bytes) -> Image.Image | None:
    """バイト列から安全にPIL Imageを開く"""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        mode = img.mode
        if mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        elif mode == "P":
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        elif mode in ("CMYK", "L"):
            return img.convert("RGB")
        elif mode == "RGB":
            return img
        else:
            return img.convert("RGB")
    except Exception as e:
        print(f"画像オープンエラー: {e}")
        return None


def safe_open_image_from_path(file_path: Path) -> Image.Image | None:
    """ファイルパスから安全にPIL Imageを開く"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        return safe_open_image(data)
    except Exception as e:
        print(f"ファイル読み込みエラー {file_path}: {e}")
        return None


def get_cover_from_archive(file_path: Path) -> Image.Image | None:
    """アーカイブから先頭の画像をメモリ上で抽出"""
    try:
        data = read_cover(file_path)
        if data:
            return safe_open_image(data)
    except ArchiveError as e:
        print(f"アーカイブ展開エラー {file_path}: {e}")
    except Exception as e:
        print(f"アーカイブ展開エラー {file_path}: {e}")
    return None


# 失敗したファイルのキャッシュ（プレースホルダー）
# 1x1の最小JPEGを保存してキャッシュ「あり」と判定させる
_PLACEHOLDER_BYTES: bytes | None = None

def _get_placeholder_bytes() -> bytes:
    """「No image」テキスト付きのプレースホルダーJPEGを返す（遅延生成）"""
    global _PLACEHOLDER_BYTES
    if _PLACEHOLDER_BYTES is None:
        from PIL import ImageDraw, ImageFont
        img = Image.new("RGB", (200, 280), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        # 枠線
        draw.rectangle([2, 2, 197, 277], outline=(200, 200, 200), width=2)
        # テキスト（フォントサイズを試みる）
        text = "No image"
        font = None
        for font_path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
            "C:/Windows/Fonts/arial.ttf",                        # Windows
            "C:/Windows/Fonts/segoeui.ttf",                      # Windows
        ):
            try:
                font = ImageFont.truetype(font_path, 18)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (200 - tw) // 2
        y = (280 - th) // 2
        draw.text((x, y), text, fill=(160, 160, 160), font=font)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        _PLACEHOLDER_BYTES = buf.getvalue()
    return _PLACEHOLDER_BYTES


def get_cache_path(file_path: Path, size: tuple = None) -> Path:
    """ファイルのハッシュからキャッシュファイル名を生成（サイズは無関係）"""
    file_hash = hashlib.md5(str(file_path).encode()).hexdigest()
    return CACHE_ROOT / f"{file_hash}.jpg"


def is_placeholder_cache(cache_path: Path) -> bool:
    """キャッシュがプレースホルダー（失敗記録）かどうか確認"""
    # 同名の .noimg マーカーファイルがあればプレースホルダー
    return cache_path.with_suffix('.noimg').exists()


CACHE_THUMB_SIZE = (400, 600)  # キャッシュは大きめに生成（表示時にデリゲートが縮小）


def create_thumbnail(file_path: Path, size=(220, 300)) -> Image.Image | None:
    """
    サムネイル作成 + キャッシュ。
    キャッシュはCACHE_THUMB_SIZEの大きなサイズで保存。
    表示サイズはデリゲート側で縮小するのでsizeは無視してキャッシュを読む。
    失敗時もプレースホルダーキャッシュを保存して再アクセスを防ぐ。
    """
    cache_file = get_cache_path(file_path)

    if cache_file.exists():
        if is_placeholder_cache(cache_file):
            # プレースホルダーはNo image画像として表示
            try:
                img = Image.open(cache_file)
                img.load()
                return img
            except Exception:
                pass
            return None
        try:
            img = Image.open(cache_file)
            img.load()
            return img
        except Exception:
            cache_file.unlink(missing_ok=True)
            cache_file.with_suffix('.noimg').unlink(missing_ok=True)

    if file_path.suffix.lower() in ('.zip', '.rar', '.cbz', '.cbr', '.7z', '.cb7', '.pdf'):
        img = get_cover_from_archive(file_path)
    else:
        img = safe_open_image_from_path(file_path)

    if img:
        img = img.copy()
        img.thumbnail(CACHE_THUMB_SIZE, Image.Resampling.LANCZOS)
        try:
            CACHE_ROOT.mkdir(parents=True, exist_ok=True)
            img.save(cache_file, "JPEG", quality=85, optimize=True)
        except Exception as e:
            print(f"[キャッシュ保存失敗] {cache_file}: {e}")
        return img

    # 失敗 → No image プレースホルダーキャッシュを保存
    try:
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        placeholder = _get_placeholder_bytes()
        cache_file.write_bytes(placeholder)
        cache_file.with_suffix('.noimg').touch()  # プレースホルダーマーカー
        # No image画像をそのまま返して表示する
        img = Image.open(io.BytesIO(placeholder))
        img.load()
        return img
    except Exception:
        pass
    return None
