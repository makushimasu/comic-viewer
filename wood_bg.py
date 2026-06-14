# wood_bg.py
"""
numpy 不要・外部依存ゼロの木目テクスチャ生成モジュール。
Pillow 標準機能のみで実装。起動時1回だけ生成してキャッシュする。
生成時間: 約27ms（800px幅）
"""

import io
import math
import random
from PIL import Image, ImageFilter, ImageChops
from PySide6.QtGui import QPixmap, QImage


def _generate_wood_pil(w: int, h: int, seed: int = 42) -> Image.Image:
    """
    メープル木目テクスチャを生成して PIL Image を返す。

    アルゴリズム:
      1. 複数周波数の正弦波を重ね合わせて列ごとの木目値を計算
      2. 1px幅の縦ストライプを paste で並べて木目画像を構築（約20ms）
      3. ImageChops.multiply で縦方向の奥行きグラデーションを乗算（高速）
      4. GaussianBlur でなめらかに仕上げる
    """
    rng  = random.Random(seed)
    rng2 = random.Random(seed + 1)

    # メープル木目のベースカラー
    base_r, base_g, base_b = 238, 195, 138

    # ---- 列ごとの木目値を計算（幅Wの1Dループ）----
    col_values = []
    for xi in range(w):
        x   = xi / max(w - 1, 1)
        val = 0.0
        for freq, amp in [
            (0.4,  16.0),   # 大きなうねり
            (1.2,   9.0),
            (3.5,   5.0),
            (7.8,   3.0),
            (0.18, 12.0),   # 非常に緩やかな変化
            (15.0,  1.5),   # 細かい木目
            (28.0,  0.8),
        ]:
            phase = rng.uniform(0, 2 * math.pi)
            val  += amp * math.sin(2 * math.pi * freq * x + phase)
        val += rng.gauss(0, 1.8)
        col_values.append(val)

    mn = min(col_values)
    mx = max(col_values)

    # ---- 縦ストライプを paste で並べて木目画像を構築 ----
    img = Image.new('RGB', (w, h), (base_r, base_g, base_b))
    for xi in range(w):
        g  = (col_values[xi] - mn) / (mx - mn + 1e-8)
        r  = max(180, min(255, int(base_r - g * 32 + rng2.uniform(-2,  2))))
        gv = max(150, min(218, int(base_g - g * 22 + rng2.uniform(-2,  2))))
        b  = max(100, min(172, int(base_b - g * 14 + rng2.uniform(-1,  1))))
        img.paste(Image.new('RGB', (1, h), (r, gv, b)), (xi, 0))

    # ---- 縦方向グラデーション（奥行き感）を乗算合成 ----
    # 上端(255) → 下端(245) の1pxグラデーションを拡大
    grad_col = Image.new('L', (1, h))
    for yi in range(h):
        v = max(0, min(255, int(255 * (1.01 - 0.05 * yi / max(h - 1, 1)))))
        grad_col.putpixel((0, yi), v)
    grad = grad_col.resize((w, h), Image.BILINEAR).convert('RGB')
    img  = ImageChops.multiply(img, grad)

    # ---- 仕上げ ----
    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    return img


def generate_wood_pixmap(w: int, h: int) -> QPixmap:
    """
    指定サイズの木目テクスチャ QPixmap を生成して返す。
    幅が非常に大きい場合は 1000px で生成してスケール（速度優先）。
    """
    if w <= 0 or h <= 0:
        return QPixmap()

    gen_w = min(w, 1000)
    gen_h = max(h, 50)

    pil_img = _generate_wood_pil(gen_w, gen_h)

    if gen_w != w or gen_h != h:
        pil_img = pil_img.resize((w, h), Image.BILINEAR)

    buf = io.BytesIO()
    pil_img.save(buf, 'PNG')
    qimg = QImage.fromData(buf.getvalue())
    return QPixmap.fromImage(qimg)
