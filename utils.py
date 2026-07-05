# utils.py
import re
from pathlib import Path

# (カテゴリ) [著者] タイトル+α にマッチするパターン
_BRACKET_PATTERN = re.compile(
    r'^[\(\（].+?[\)\）]\s*[\[\［【].+?[\]\］】]\s*(.+)$'
)

# 数字部分を抽出するためのパターン（自然順ソート用）
_NATSORT_PATTERN = re.compile(r'(\d+)')


def natural_sort_key(name: str):
    """
    Windows/pico viewer風の並び順を再現するソートキー。
    - 大文字小文字を区別しない
    - 数字部分は数値として比較する（例: "第2巻" < "第10巻"）

    使用例: sorted(items, key=lambda p: natural_sort_key(p.name))
    """
    parts = _NATSORT_PATTERN.split(name)
    key = []
    for part in parts:
        if part.isdigit():
            # 数値として比較するため (1, 数値) のタプルにする
            key.append((1, int(part)))
        else:
            # 文字列は大文字小文字を無視して比較
            key.append((0, part.lower()))
    return key


def folder_has_bracket_pattern(folder_name: str) -> bool:
    """
    フォルダ名が (カテゴリ) [著者] タイトル+α 形式かどうかを返す。
    例: (Category) [Author] Title vol.1 → True
    """
    return bool(_BRACKET_PATTERN.match(Path(folder_name).stem if '.' in folder_name else folder_name))


def parse_filename(filename: str, use_bracket_rule: bool = False) -> dict:
    """
    ファイル名から表示名を生成する。

    use_bracket_rule=True（現在フォルダがブラケットパターン）の場合:
      (カテゴリ) [著者] タイトル+α.zip → タイトル+α  を返す
      マッチしなければ拡張子なしのファイル名全体を返す

    use_bracket_rule=False の場合:
      拡張子なしのファイル名全体を返す（旧ルール廃止）
    """
    stem = Path(filename).stem  # 拡張子を除去

    if use_bracket_rule:
        m = _BRACKET_PATTERN.match(stem)
        if m:
            return {"title": m.group(1).strip(), "full_stem": stem}

    # ブラケットルール不適用、またはマッチしない場合 → そのまま全部表示
    return {"title": stem, "full_stem": stem}


# ============================================================
# シリーズ自動グループ化
# ============================================================

# 巻数表現のパターン（シリーズ名の抽出用）
_VOLUME_PATTERNS = [
    re.compile(r'第?\s*\d+\s*[巻話章冊集]'),
    re.compile(r'[vV][oO][lL]\.?\s*\d+'),
    re.compile(r'\b[vV]\d+\b'),
    re.compile(r'[\(（]\d+[\)）]'),
    re.compile(r'[#＃]\d+'),
    re.compile(r'[\s\-_～~・．.,、]*\d{1,4}\s*$'),   # 末尾の数字
    re.compile(r'[\s(（]*[上中下前後][\s)）]*$'),      # 上巻/下巻表現
]


def series_display_title(title: str) -> str:
    """タイトルから巻数表現を取り除いた表示用シリーズ名を返す"""
    s = title
    for pat in _VOLUME_PATTERNS:
        s = pat.sub(' ', s)
    s = re.sub(r'[\s\-_～~・，,、]+$', '', s.strip())
    return s.strip() or title


def series_key(title: str) -> str:
    """シリーズ判定用の正規化キーを返す（巻数除去 + 空白/記号除去 + 小文字化）。
    空文字が返る場合はグループ化しない。"""
    s = series_display_title(title)
    s = re.sub(r'[\s\-_～~・．.，,、!！?？'"'"']+', '', s).lower()
    return s
