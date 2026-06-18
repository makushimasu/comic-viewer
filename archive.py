# archive.py
"""
外部コマンド不要のアーカイブ展開モジュール。
Linux 標準搭載の libarchive を ctypes で呼ぶ。

ZIP/CBZ  → Python標準 zipfile（完全に外部依存ゼロ）
RAR/CBR  → 以下の順で試みる:
  1. libarchive (RAR4は専用パーサ、RAR5は専用パーサを使い分け)
  2. unar コマンド (sudo apt install unar)
  3. 7z  コマンド (sudo apt install p7zip-full)
  いずれもなければエラーメッセージを表示
"""

import ctypes
import ctypes.util
import io
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile, BadZipFile

# Windowsでsubprocess呼び出し時にコンソール窓を出さないフラグ
_NO_WINDOW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if os.name == "nt" else {}
)

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')

ARCHIVE_EOF    =   1
ARCHIVE_OK     =   0
ARCHIVE_WARN   = -20
ARCHIVE_FAILED = -25
ARCHIVE_FATAL  = -30


class ArchiveError(Exception):
    pass


# ============================================================
# RAR4 / RAR5 判別
# ============================================================

_RAR4_MAGIC = bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x00])
_RAR5_MAGIC = bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x01, 0x00])


def _detect_rar_version(file_path: Path) -> int:
    """4 または 5 を返す。判別できなければ 0。"""
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(8)
        if magic[:7] == _RAR4_MAGIC:
            return 4
        if magic[:8] == _RAR5_MAGIC:
            return 5
    except Exception:
        pass
    return 0


# ============================================================
# libarchive ロード
# ============================================================

def _load_libarchive():
    import sys
    lib_name = ctypes.util.find_library("archive")
    # Windows では標準では見つからないため追加候補DLLを試みる
    if not lib_name and sys.platform == "win32":
        for candidate in (
            "libarchive.dll", "archive.dll",
            "libarchive-13.dll", "libarchive-14.dll", "libarchive-15.dll",
        ):
            try:
                ctypes.CDLL(candidate)
                lib_name = candidate
                break
            except OSError:
                continue
    if not lib_name:
        return None
    try:
        lib = ctypes.CDLL(lib_name)
        lib.archive_read_new.restype                      = ctypes.c_void_p
        lib.archive_read_new.argtypes                     = []
        lib.archive_read_support_filter_all.restype       = ctypes.c_int
        lib.archive_read_support_filter_all.argtypes      = [ctypes.c_void_p]
        lib.archive_read_support_format_all.restype       = ctypes.c_int
        lib.archive_read_support_format_all.argtypes      = [ctypes.c_void_p]
        lib.archive_read_support_format_rar.restype       = ctypes.c_int
        lib.archive_read_support_format_rar.argtypes      = [ctypes.c_void_p]
        lib.archive_read_support_format_rar5.restype      = ctypes.c_int
        lib.archive_read_support_format_rar5.argtypes     = [ctypes.c_void_p]
        lib.archive_read_open_filename.restype            = ctypes.c_int
        lib.archive_read_open_filename.argtypes           = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.archive_read_next_header.restype              = ctypes.c_int
        lib.archive_read_next_header.argtypes             = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.archive_entry_pathname_utf8.restype           = ctypes.c_char_p
        lib.archive_entry_pathname_utf8.argtypes          = [ctypes.c_void_p]
        lib.archive_entry_pathname.restype                = ctypes.c_char_p
        lib.archive_entry_pathname.argtypes               = [ctypes.c_void_p]
        lib.archive_entry_size.restype                    = ctypes.c_int64
        lib.archive_entry_size.argtypes                   = [ctypes.c_void_p]
        lib.archive_read_data.restype                     = ctypes.c_ssize_t
        lib.archive_read_data.argtypes                    = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        lib.archive_read_data_skip.restype                = ctypes.c_int
        lib.archive_read_data_skip.argtypes               = [ctypes.c_void_p]
        lib.archive_read_free.restype                     = ctypes.c_int
        lib.archive_read_free.argtypes                    = [ctypes.c_void_p]
        lib.archive_error_string.restype                  = ctypes.c_char_p
        lib.archive_error_string.argtypes                 = [ctypes.c_void_p]
        return lib
    except Exception:
        return None


_lib = _load_libarchive()


# ============================================================
# libarchive 内部ユーティリティ
# ============================================================

def _entry_name(entry) -> str:
    if _lib is None:
        return ""
    raw = _lib.archive_entry_pathname_utf8(entry)
    if raw:
        return raw.decode("utf-8", errors="replace")
    raw = _lib.archive_entry_pathname(entry)
    if raw:
        for enc in ("utf-8", "cp932", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    return ""


def _read_entry_data(archive) -> bytes:
    buf = io.BytesIO()
    chunk = ctypes.create_string_buffer(65536)
    while True:
        n = _lib.archive_read_data(archive, chunk, 65536)
        if n <= 0:
            break
        buf.write(chunk.raw[:n])
    return buf.getvalue()


def _open_libarchive(file_path: Path, rar_version: int = 0):
    """
    libarchive のアーカイブポインタを返す。
    rar_version: 4=RAR4専用, 5=RAR5専用, 0=全形式
    失敗したら None を返す。
    """
    if _lib is None:
        return None
    a = _lib.archive_read_new()
    if not a:
        return None
    _lib.archive_read_support_filter_all(a)
    if rar_version == 4:
        _lib.archive_read_support_format_rar(a)
    elif rar_version == 5:
        _lib.archive_read_support_format_rar5(a)
    else:
        _lib.archive_read_support_format_all(a)
    r = _lib.archive_read_open_filename(a, str(file_path).encode("utf-8"), 65536)
    if r not in (ARCHIVE_OK, ARCHIVE_WARN):
        _lib.archive_read_free(a)
        return None
    return a


def _scan_names(a) -> list[str]:
    """アーカイブ内の画像ファイル名を全走査して返す（データは読まない）"""
    names = []
    entry = ctypes.c_void_p()
    fatal_count = 0
    while True:
        r = _lib.archive_read_next_header(a, ctypes.byref(entry))
        if r == ARCHIVE_EOF:
            break
        if r == ARCHIVE_FATAL:
            fatal_count += 1
            if fatal_count >= 5:
                break
            continue
        if r == ARCHIVE_FAILED:
            continue
        fatal_count = 0
        name = _entry_name(entry)
        if name and name.lower().endswith(IMAGE_EXTS) and not name.endswith('/'):
            names.append(name)
        _lib.archive_read_data_skip(a)
    return names


def _read_all_data(a) -> list[tuple[str, bytes]]:
    """アーカイブ内の全画像をデータごと読む"""
    collected = []
    entry = ctypes.c_void_p()
    fatal_count = 0
    while True:
        r = _lib.archive_read_next_header(a, ctypes.byref(entry))
        if r == ARCHIVE_EOF:
            break
        if r == ARCHIVE_FATAL:
            fatal_count += 1
            if fatal_count >= 5:
                break
            continue
        if r == ARCHIVE_FAILED:
            continue
        fatal_count = 0
        name = _entry_name(entry)
        if name and name.lower().endswith(IMAGE_EXTS) and not name.endswith('/'):
            data = _read_entry_data(a)
            if data:
                collected.append((name, data))
        else:
            _lib.archive_read_data_skip(a)
    return collected


# ============================================================
# libarchive で RAR を読む（RAR4/5 を判別して専用パーサ使用）
# ============================================================

def _read_rar_libarchive_all(file_path: Path) -> list[bytes] | None:
    pages, _ = _read_rar_libarchive_all_with_names(file_path)
    return pages if pages else None


def _read_rar_libarchive_all_with_names(file_path: Path) -> tuple[list[bytes], list[str]]:
    """libarchiveで全画像とファイル名を読む"""
    if _lib is None:
        return [], []

    ver = _detect_rar_version(file_path)
    for rar_ver in ([ver, 0] if ver else [0]):
        a = _open_libarchive(file_path, rar_ver)
        if a is None:
            continue
        try:
            collected = _read_all_data(a)
        finally:
            _lib.archive_read_free(a)

        if collected:
            collected.sort(key=lambda x: x[0])
            names = [Path(n).name for n, _ in collected]
            pages = [d for _, d in collected]
            return pages, names

    return [], []


# libarchiveで読めなかったRARパスのメモリキャッシュ（セッション内のみ）
_rar_failed_cache: set = set()


def _read_rar_libarchive_cover(file_path: Path) -> bytes | None:
    """
    先頭画像1枚だけ読む（サムネイル用）。
    1回のスキャンで最初の画像ファイルを取得して即返す。
    失敗したパスはメモリにキャッシュして再試行しない。
    """
    if _lib is None:
        return None

    # 既に失敗が確定しているファイルはスキップ（ネットワーク転送ゼロ）
    path_str = str(file_path)
    if path_str in _rar_failed_cache:
        return None

    ver = _detect_rar_version(file_path)
    for rar_ver in ([ver, 0] if ver else [0]):
        a = _open_libarchive(file_path, rar_ver)
        if a is None:
            continue

        entry = ctypes.c_void_p()
        result = None
        first_image_name = None
        fatal_count = 0

        try:
            while True:
                r = _lib.archive_read_next_header(a, ctypes.byref(entry))
                if r == ARCHIVE_EOF:
                    break
                if r == ARCHIVE_FATAL:
                    fatal_count += 1
                    if fatal_count >= 3:
                        break
                    continue
                if r in (ARCHIVE_FAILED, ARCHIVE_WARN):
                    continue
                fatal_count = 0

                name = _entry_name(entry)
                if not name or name.endswith('/'):
                    _lib.archive_read_data_skip(a)
                    continue

                if name.lower().endswith(IMAGE_EXTS):
                    if first_image_name is None:
                        first_image_name = name
                        data = _read_entry_data(a)
                        if data:
                            result = data
                            break
                    else:
                        _lib.archive_read_data_skip(a)
                else:
                    _lib.archive_read_data_skip(a)
        finally:
            _lib.archive_read_free(a)

        if result:
            return result

    # 全て失敗 → メモリキャッシュに記録
    _rar_failed_cache.add(path_str)
    return None


# ============================================================
# 外部コマンドフォールバック（unar / 7z）
# ============================================================

def _find_extractor() -> tuple[str, str] | None:
    """
    利用可能な展開コマンドを探す。
    (コマンドパス, 種別) を返す。なければ None。
    """
    import sys
    if sys.platform == "win32":
        # PATHにある場合を最初に確認
        for name in ("7z", "7za", "7zz"):
            p = shutil.which(name)
            if p:
                return (p, "7z")
        # 7-Zip はデフォルトでPATHに追加されないため標準インストールパスも確認
        for sz_path in (
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ):
            if Path(sz_path).exists():
                return (sz_path, "7z")
        # unrar (PATH)
        p = shutil.which("unrar")
        if p:
            return (p, "unrar")
        return None

    # Linux / macOS
    unar = shutil.which("unar")
    if unar:
        return (unar, "unar")
    for name in ("7z", "7za", "7zz"):
        p = shutil.which(name)
        if p:
            return (p, "7z")
    return None


def _read_rar_via_command(file_path: Path) -> list[bytes]:
    """unar / 7z / unrar コマンドで展開する"""
    import sys
    extractor = _find_extractor()
    if extractor is None:
        if sys.platform == "win32":
            raise ArchiveError(
                f"RARファイルを展開できません: {file_path.name}\n\n"
                "7-Zip をインストールしてください:\n"
                "  https://www.7-zip.org/"
            )
        raise ArchiveError(
            f"RARファイルを展開できません: {file_path.name}\n\n"
            "以下のいずれかをインストールしてください:\n"
            "  sudo apt install unar          # 推奨\n"
            "  sudo apt install p7zip-full    # 代替"
        )

    cmd_path, kind = extractor
    tmp_dir = tempfile.mkdtemp(prefix="comic_rar_")
    try:
        if kind == "unar":
            proc = subprocess.run(
                [cmd_path, "-o", tmp_dir, "-f", str(file_path)],
                capture_output=True, timeout=120, **_NO_WINDOW
            )
        elif kind == "7z":
            proc = subprocess.run(
                [cmd_path, "e", str(file_path), f"-o{tmp_dir}", "-y", "-bd"],
                capture_output=True, timeout=120, **_NO_WINDOW
            )
        else:  # unrar
            proc = subprocess.run(
                [cmd_path, "e", "-y", str(file_path), tmp_dir],
                capture_output=True, timeout=120, **_NO_WINDOW
            )

        # unar/unrarは成功でも1を返すことがある、7zも警告で1を返す
        if proc.returncode not in (0, 1):
            raise ArchiveError(
                f"展開コマンドがエラーを返しました (code {proc.returncode}):\n"
                f"{proc.stderr.decode(errors='replace')[:200]}"
            )

        result = []
        for p in sorted(Path(tmp_dir).rglob("*")):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                result.append((p.name, p.read_bytes()))
        result.sort(key=lambda x: x[0])
        return [d for _, d in result]

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================
# ZIP（標準ライブラリ）
# ============================================================

def _read_zip_all(file_path: Path) -> list[bytes]:
    pages, _ = _read_zip_all_with_names(file_path)
    return pages


def read_zip_streaming(file_path: Path):
    """
    ZIPファイルを先頭から1ファイルずつyieldするジェネレータ。
    (index, name, data) のタプルを返す。
    ネットワークドライブでも先頭ページから即表示可能。
    """
    LOCAL_SIG = b'PK\x03\x04'
    index = 0
    try:
        with open(file_path, 'rb') as f:
            while True:
                sig = f.read(4)
                if len(sig) < 4 or sig != LOCAL_SIG:
                    break
                header = f.read(26)
                if len(header) < 26:
                    break
                (_, flags, compress, _, _,
                 _, comp_size, _,
                 fname_len, extra_len) = struct.unpack('<HHHHHIIIHH', header)
                fname_bytes = f.read(fname_len)
                f.read(extra_len)
                for enc in ('utf-8', 'cp932', 'latin-1'):
                    try:
                        fname = fname_bytes.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    fname = ''
                if (fname.lower().endswith(IMAGE_EXTS)
                        and not fname.endswith('/')
                        and comp_size > 0):
                    data = f.read(comp_size)
                    if compress == 0:
                        yield index, Path(fname).name, data
                        index += 1
                    elif compress == 8:
                        import zlib
                        try:
                            yield index, Path(fname).name, zlib.decompress(data, -15)
                            index += 1
                        except Exception:
                            pass
                    else:
                        f.seek(0, 2)  # 未対応圧縮形式はスキップ
                else:
                    f.seek(comp_size, 1)
    except Exception as e:
        pass


def _decode_zip_name(info) -> str:
    """ZipInfoから正しいファイル名をデコードする。
    日本語ファイル名はCP932で格納されているがnamelist()はCP437で
    デコードしてしまい文字化け・誤ソートの原因になるため、
    raw bytesから再デコードする。"""
    raw = info.filename.encode('cp437', errors='replace')
    # ZIP flag bit 11 (0x800) が立っていればUTF-8格納
    if info.flag_bits & 0x800:
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            pass
    for enc in ('cp932', 'utf-8', 'shift_jis'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return info.filename  # フォールバック（文字化けのまま）


def _read_zip_all_with_names(file_path: Path) -> tuple[list[bytes], list[str]]:
    try:
        with ZipFile(file_path) as z:
            entries = []
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = _decode_zip_name(info)
                if name.lower().endswith(IMAGE_EXTS):
                    entries.append((name, info))
            entries.sort(key=lambda x: x[0])
            pages = [z.read(info) for _, info in entries]
            base_names = [Path(name).name for name, _ in entries]
            return pages, base_names
    except BadZipFile as e:
        raise ArchiveError(f"ZIPが壊れています: {e}")


def _read_zip_cover(file_path: Path) -> bytes | None:
    """
    ZIPの先頭画像（ファイル名でソートして最初）1枚を取得する。

    Central Directory（ファイル末尾の数KB）を読んで正しいファイル名一覧
    を取得し、ソート後の最初のファイルだけを個別に読み込む。
    ZIP内の物理格納順は番号順と一致しないことがあるため、
    単純な先頭ストリーム読みは使わない。
    """
    try:
        with ZipFile(file_path) as z:
            entries = []
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = _decode_zip_name(info)
                if name.lower().endswith(IMAGE_EXTS):
                    entries.append((name, info))
            if not entries:
                return None
            entries.sort(key=lambda x: x[0])
            return z.read(entries[0][1])
    except BadZipFile as e:
        raise ArchiveError(f"ZIPが壊れています: {e}")
    except Exception:
        return None


# ============================================================
# 公開 API
# ============================================================

def read_all_images(file_path: Path) -> list[bytes]:
    """アーカイブ内の全画像を返す（ソート済み）"""
    pages, _ = read_all_images_with_names(file_path)
    return pages


def read_all_images_with_names(file_path: Path) -> tuple[list[bytes], list[str]]:
    """アーカイブ内の全画像とファイル名を返す（ソート済み）"""
    suffix = file_path.suffix.lower()

    if suffix in ('.zip', '.cbz'):
        return _read_zip_all_with_names(file_path)

    if suffix in ('.rar', '.cbr'):
        result = _read_rar_libarchive_all_with_names(file_path)
        if result[0]:
            return result
        pages = _read_rar_via_command(file_path)
        names = [f"{i:04d}.img" for i in range(len(pages))]
        return pages, names

    raise ArchiveError(f"未対応の形式です: {file_path.suffix}")


def _read_rar_cover_via_command(file_path: Path) -> bytes | None:
    """
    外部コマンド（7z / unrar）でRARの先頭画像1枚だけ取得する。
    libarchiveが使えない環境（Windows標準等）でのサムネイル生成に使う。
    全ページ展開ではなく先頭ファイルのみ展開して高速化する。
    """
    extractor = _find_extractor()
    if extractor is None:
        return None
    cmd_path, kind = extractor

    try:
        # Step1: アーカイブ内の画像ファイル名リストを取得してソート
        names = []
        if kind == "7z":
            proc = subprocess.run(
                [cmd_path, "l", "-slt", str(file_path)],
                capture_output=True, timeout=30, **_NO_WINDOW
            )
            for line_b in proc.stdout.splitlines():
                for enc in ("utf-8", "cp932", "latin-1"):
                    try:
                        line = line_b.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    continue
                s = line.strip()
                if s.startswith("Path = "):
                    name = s[7:]
                    if name.lower().endswith(IMAGE_EXTS) and not name.endswith("/"):
                        names.append(name)
        elif kind == "unrar":
            proc = subprocess.run(
                [cmd_path, "lb", str(file_path)],
                capture_output=True, timeout=30, **_NO_WINDOW
            )
            for line_b in proc.stdout.splitlines():
                for enc in ("utf-8", "cp932", "latin-1"):
                    try:
                        name = line_b.decode(enc).strip()
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    continue
                if name.lower().endswith(IMAGE_EXTS):
                    names.append(name)
        elif kind == "unar":
            # unarはファイル一覧取得が複雑なため全展開で対応
            pages = _read_rar_via_command(file_path)
            return pages[0] if pages else None

        if not names:
            return None
        first_file = sorted(names)[0]

        # Step2: 先頭ファイルだけ一時ディレクトリに展開して読む
        tmp_dir = tempfile.mkdtemp(prefix="comic_cover_")
        try:
            if kind == "7z":
                subprocess.run(
                    [cmd_path, "e", str(file_path), first_file,
                     f"-o{tmp_dir}", "-y", "-bd"],
                    capture_output=True, timeout=30, **_NO_WINDOW
                )
            elif kind == "unrar":
                subprocess.run(
                    [cmd_path, "e", "-y", str(file_path), first_file, tmp_dir],
                    capture_output=True, timeout=30, **_NO_WINDOW
                )
            for p in Path(tmp_dir).rglob("*"):
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                    return p.read_bytes()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        print(f"[cover] コマンド失敗 {file_path.name}: {e}")

    return None


def read_cover(file_path: Path) -> bytes | None:
    """
    先頭の画像1枚だけを返す（サムネイル用・高速）。
    RARはlibarchiveを試み、失敗時は外部コマンド（7z/unrar等）で先頭1枚だけ展開する。
    """
    suffix = file_path.suffix.lower()

    if suffix in ('.zip', '.cbz'):
        return _read_zip_cover(file_path)

    if suffix in ('.rar', '.cbr'):
        result = _read_rar_libarchive_cover(file_path)
        if result:
            return result
        # libarchive失敗時（Windows標準環境等）は外部コマンドで先頭画像のみ取得
        return _read_rar_cover_via_command(file_path)

    raise ArchiveError(f"未対応の形式です: {file_path.suffix}")
