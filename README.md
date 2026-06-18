# Comic Viewer

[English](README_EN.md) | 日本語

Linux / Windows 向けのコミック・画像ビューアです。ZIP / RAR アーカイブや画像フォルダを本棚形式で管理し、快適に閲覧できます。

---

## 機能

### 本棚
- フォルダ・ファイルを登録してサムネイル一覧で管理
- フォルダ内をブラウズして ZIP / RAR / 画像フォルダを開く
- 「本として開く」でフォルダ内の画像ファイルをまとめて1冊として閲覧
- キーワード検索（サブフォルダまで再帰検索）
- 最後に開いた場所とスクロール位置を記憶

### ビューア
- **1ページ表示** / **見開き2ページ表示**
- **読む方向**: 右→左（日本式）/ 左→右
- **ズーム**: マウスホイール・キーボード操作
- **フィットモード**: 全体・横幅・縦幅を切り替え（`F` キー）
- **ページ回転**: 各ページを90°単位で回転（次回起動時も維持）
- **サムネイルストリップ**: 下部にページ一覧を表示、クリックで移動
- **しおり**: ページにラベル付きしおりを設定
- **スライドショー**: 秒数・終了時の動作・切り替えエフェクトを設定
- **進捗保存**: 最後に読んでいたページを次回起動時に復元
- **全画面表示**

### キーボードショートカット（ビューア内）

| キー | 動作 |
|------|------|
| `→` / `D` / `Space` | 次のページ |
| `←` / `A` | 前のページ |
| `+` / `=` | ズームイン |
| `-` / `_` | ズームアウト |
| `F` | フィットモード切り替え |
| `Esc` | 本棚へ戻る / 全画面解除 |
| マウスホイール | ズーム |

---

## 対応フォーマット

| 種類 | 拡張子 |
|------|--------|
| ZIP アーカイブ | `.zip` `.cbz` |
| RAR アーカイブ | `.rar` `.cbr` ※要追加インストール |
| 画像フォルダ | フォルダ内の `.jpg` `.jpeg` `.png` `.webp` `.gif` `.bmp` |

### RAR ファイルを開くには

```bash
sudo apt install unar
```

または

```bash
sudo apt install unrar
```

---

## 動作環境

| | Linux | Windows |
|---|---|---|
| OS | Ubuntu 22.04 / Linux Mint 21 以降 | Windows 10 / 11 |
| Python | 3.10 以上 | 3.10 以上 |
| RAR サポート | `unar` または `unrar` | 7-Zip |

---

## インストールと起動

### Linux

```bash
# 1. リポジトリをクローン
git clone https://github.com/makushimasu/comic-viewer.git
cd comic-viewer

# 2. 仮想環境を作成して有効化
python3 -m venv venv
source venv/bin/activate

# 3. 依存パッケージをインストール
pip install -r requirements.txt

# 4. 起動
python main.py
```

### Windows

```bat
# 1. リポジトリをクローン（またはZIPをダウンロードして解凍）
git clone https://github.com/makushimasu/comic-viewer.git
cd comic-viewer

# 2. start.bat をダブルクリック（初回は仮想環境を自動構築して起動）
start.bat
```

**RAR サポート（Windows）**: [7-Zip](https://www.7-zip.org/) をインストールしてください。

---

## データの保存場所

| OS | パス |
|---|---|
| Linux | `~/comic_viewer/` |
| Windows | `%LOCALAPPDATA%\comic_viewer\` |

アプリのデータはすべて上記フォルダに保存されます。アンインストール時はこのフォルダを削除してください。

| パス | 内容 |
|------|------|
| `~/comic_viewer/library.json` | 登録済みフォルダ・ファイルのリスト |
| `~/comic_viewer/progress.json` | ページ進捗・しおり・回転角度 |
| `~/comic_viewer/settings.json` | 設定 |
| `~/comic_viewer/thumb_cache/` | 表紙サムネイルのキャッシュ |
| `~/comic_viewer/page_cache/` | ページキャッシュ |

---

## ライセンス

MIT License — Copyright (c) 2026 まくします
