# settings.py
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QScrollArea, QWidget,
    QRadioButton, QFrame, QComboBox
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

SETTINGS_FILE = Path.home() / "comic_viewer" / "settings.json"
SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

# デフォルト値
DEFAULTS = {
    "thumbnail_width":        150,   # サムネイル幅 px (80-400)
    "thumbnail_height":       150,   # サムネイル高さ px (80-400)
    "scrollbar_always":       False,
    "show_hierarchy":         True,
    "show_filepath":          True,
    "remember_last_location": True,
    "viewer_mode":              "inline",
    "page_cache_mb":            500,   # ページキャッシュ容量上限 (MB)
    "pages_per_screen":         1,     # 1画面に表示するページ数 (1 or 2)
    "reading_direction":        "rtl", # サムネイル順: "rtl"=右端が1ページ目, "ltr"=左端が1ページ目
    "language":                 "ja",  # UI言語: "ja" or "en"
    "slideshow_interval":       3.0,   # スライドショー: 1ページあたりの表示時間 (秒)
    "slideshow_end_action":     "stop",   # 最後に達したときの動作: "stop"/"first"/"next_book"
    "slideshow_effect":         "none",   # ページ切り替え効果: "none"/"slide_in"/"slide_out"/"dissolve"
    "slideshow_effect_duration": 1.0,  # ページ切り替えアニメーション長さ (秒)
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
            return {**DEFAULTS, **data}
        except Exception:
            pass
    return dict(DEFAULTS)


def save_settings(settings: dict):
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


# ============================================================
# トグルスイッチ風チェックボックス
# ============================================================

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._update_style()
        self.stateChanged.connect(lambda _: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet("""
                QCheckBox::indicator {
                    width: 48px; height: 24px;
                    border-radius: 12px; background: #4caf50; image: none;
                }
                QCheckBox::indicator:hover { background: #43a047; }
                QCheckBox { spacing: 0px; }
            """)
        else:
            self.setStyleSheet("""
                QCheckBox::indicator {
                    width: 48px; height: 24px;
                    border-radius: 12px; background: #aaaaaa; image: none;
                }
                QCheckBox::indicator:hover { background: #999999; }
                QCheckBox { spacing: 0px; }
            """)


# ============================================================
# 設定ダイアログ
# ============================================================

class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        from i18n import tr
        self.setWindowTitle(tr("settings_title"))
        self.setMinimumWidth(440)
        self.settings = dict(settings)

        self._build_ui()
        self._load_values()

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("sans-serif", 10, QFont.Weight.Bold))
        label.setStyleSheet("""
            QLabel {
                border-left: 4px solid #5a8a3c;
                padding-left: 8px;
                color: #1a1a1a;
                margin-top: 6px;
            }
        """)
        return label

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddccbb;")
        return line

    def _spinbox(self, min_val: int, max_val: int, suffix: str, width: int = 180) -> QSpinBox:
        sb = QSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSuffix(suffix)
        sb.setFixedWidth(width)
        return sb

    def _toggle_row(self, layout, label_text: str, attr_name: str):
        from i18n import tr
        layout.addWidget(self._section_label(label_text))
        row = QHBoxLayout()
        toggle = ToggleSwitch()
        state_label = QLabel(tr("tog_off"))
        state_label.setFixedWidth(28)
        state_label.setStyleSheet("color: #1a1a1a;")
        toggle.stateChanged.connect(
            lambda s, sl=state_label: sl.setText(tr("tog_on") if s else tr("tog_off"))
        )
        row.addWidget(state_label)
        row.addWidget(toggle)
        row.addStretch()
        layout.addLayout(row)
        setattr(self, attr_name, toggle)

    def _build_ui(self):
        from i18n import tr
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        header = QLabel(tr("settings_header"))
        header.setFont(QFont("sans-serif", 13, QFont.Weight.Bold))
        header.setStyleSheet("background: #f0e6d2; padding: 14px; color: #1a1a1a;")
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #faf5ee; }")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: #faf5ee; color: #1a1a1a;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)
        scroll.setWidget(content)

        # ---- サムネイルサイズ ----
        layout.addWidget(self._section_label(tr("thumb_width")))
        row_tw = QHBoxLayout()
        self.spin_thumb_w = self._spinbox(80, 400, "  px  (80 - 400)")
        row_tw.addWidget(self.spin_thumb_w)
        row_tw.addStretch()
        layout.addLayout(row_tw)

        layout.addWidget(self._section_label(tr("thumb_height")))
        row_th = QHBoxLayout()
        self.spin_thumb_h = self._spinbox(80, 400, "  px  (80 - 400)")
        row_th.addWidget(self.spin_thumb_h)
        row_th.addStretch()
        layout.addLayout(row_th)

        layout.addWidget(self._divider())

        # ---- 表示設定（トグル群） ----
        self._toggle_row(layout, tr("tog_scrollbar"), "tog_scrollbar")
        self._toggle_row(layout, tr("tog_hierarchy"), "tog_hierarchy")
        self._toggle_row(layout, tr("tog_filepath"),  "tog_filepath")
        self._toggle_row(layout, tr("tog_remember"),  "tog_remember")

        layout.addWidget(self._divider())

        # ---- ページキャッシュ ----
        layout.addWidget(self._section_label(tr("cache_label")))
        row_pc = QHBoxLayout()
        self.spin_page_cache = self._spinbox(0, 10000, tr("cache_spin_suffix"), width=280)
        row_pc.addWidget(self.spin_page_cache)
        row_pc.addStretch()
        layout.addLayout(row_pc)
        cache_note = QLabel(tr("cache_note"))
        cache_note.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(cache_note)

        layout.addWidget(self._divider())

        # ---- ビューア起動モード ----
        layout.addWidget(self._section_label(tr("viewer_mode_label")))
        self.radio_window = QRadioButton(tr("viewer_mode_window"))
        self.radio_inline = QRadioButton(tr("viewer_mode_inline"))
        self.radio_window.setStyleSheet("padding: 4px;")
        self.radio_inline.setStyleSheet("padding: 4px;")
        layout.addWidget(self.radio_window)
        layout.addWidget(self.radio_inline)

        layout.addWidget(self._divider())

        # ---- 言語 / Language ----
        layout.addWidget(self._section_label(tr("language_label")))
        row_lang = QHBoxLayout()
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["日本語", "English"])
        self.combo_lang.setFixedWidth(140)
        self.combo_lang.setStyleSheet("""
            QComboBox {
                background: white; color: #1a1a1a;
                border: 1px solid #aaa; border-radius: 3px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                background: white; color: #1a1a1a;
                selection-background-color: #5a8a3c;
                selection-color: white;
            }
        """)
        row_lang.addWidget(self.combo_lang)
        row_lang.addStretch()
        layout.addLayout(row_lang)
        lang_note = QLabel(tr("language_restart_note"))
        lang_note.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(lang_note)

        layout.addStretch()

        # ---- 保存ボタン ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton(tr("settings_save"))
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #5a8a3c; color: white;
                border-radius: 6px; padding: 8px 20px; font-weight: bold;
            }
            QPushButton:hover { background: #4a7a2c; }
        """)
        ok_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(ok_btn)
        outer.addLayout(btn_row)
        outer.setContentsMargins(0, 0, 10, 10)

    def _load_values(self):
        self.spin_thumb_w.setValue(self.settings["thumbnail_width"])
        self.spin_thumb_h.setValue(self.settings["thumbnail_height"])
        self.tog_scrollbar.setChecked(self.settings["scrollbar_always"])
        self.tog_hierarchy.setChecked(self.settings["show_hierarchy"])
        self.tog_filepath.setChecked(self.settings["show_filepath"])
        self.tog_remember.setChecked(self.settings["remember_last_location"])
        self.spin_page_cache.setValue(self.settings.get("page_cache_mb", 500))
        if self.settings["viewer_mode"] == "inline":
            self.radio_inline.setChecked(True)
        else:
            self.radio_window.setChecked(True)
        lang_map = {"ja": 0, "en": 1}
        self.combo_lang.setCurrentIndex(lang_map.get(self.settings.get("language", "ja"), 0))
        for tog in [self.tog_scrollbar, self.tog_hierarchy, self.tog_filepath,
                    self.tog_remember]:
            tog._update_style()

    def _save_and_close(self):
        self.settings["thumbnail_width"]        = self.spin_thumb_w.value()
        self.settings["thumbnail_height"]       = self.spin_thumb_h.value()
        self.settings["scrollbar_always"]       = self.tog_scrollbar.isChecked()
        self.settings["show_hierarchy"]         = self.tog_hierarchy.isChecked()
        self.settings["show_filepath"]          = self.tog_filepath.isChecked()
        self.settings["remember_last_location"] = self.tog_remember.isChecked()
        self.settings["viewer_mode"]            = "inline" if self.radio_inline.isChecked() else "window"
        self.settings["page_cache_mb"]          = self.spin_page_cache.value()
        self.settings["language"]               = ["ja", "en"][self.combo_lang.currentIndex()]
        save_settings(self.settings)
        self.accept()

    def get_settings(self) -> dict:
        return self.settings
