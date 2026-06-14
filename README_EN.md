# Comic Viewer

A comic and image viewer for Linux. Manage your ZIP / RAR archives and image folders in a bookshelf view and read them comfortably.

---

## Features

### Bookshelf
- Register folders and files and browse them as thumbnail grids
- Navigate into folders to open ZIP / RAR archives or image folders
- "Open as Book" — read all images in a folder as a single book
- Keyword search (recursive, including subfolders)
- Remembers the last visited location and scroll position

### Viewer
- **Single page** / **Two-page spread** display
- **Reading direction**: Right-to-Left (manga style) / Left-to-Right
- **Zoom**: mouse wheel or keyboard
- **Fit mode**: fit to window / fit width / fit height — cycle with `F`
- **Page rotation**: rotate each page in 90° steps (persisted across sessions)
- **Thumbnail strip**: page list at the bottom, click to jump
- **Bookmarks**: add labeled bookmarks to any page
- **Slideshow**: configurable interval, end action, and transition effects
- **Progress saving**: resumes from where you left off on next launch
- **Fullscreen** support

### Keyboard Shortcuts (Viewer)

| Key | Action |
|-----|--------|
| `→` / `D` / `Space` | Next page |
| `←` / `A` | Previous page |
| `+` / `=` | Zoom in |
| `-` / `_` | Zoom out |
| `F` | Cycle fit mode |
| `Esc` | Back to bookshelf / exit fullscreen |
| Mouse wheel | Zoom |

---

## Supported Formats

| Type | Extensions |
|------|-----------|
| ZIP archive | `.zip` `.cbz` |
| RAR archive | `.rar` `.cbr` ※ requires extra install |
| Image folder | `.jpg` `.jpeg` `.png` `.webp` `.gif` `.bmp` inside a folder |

### Opening RAR Files

RAR support requires `unar` or `unrar`:

```bash
sudo apt install unar
```

or

```bash
sudo apt install unrar
```

---

## System Requirements

- **OS**: Linux (Ubuntu 22.04 / Linux Mint 21 or later recommended)
- **Python**: 3.10 or higher
- **IME**: fcitx5 or ibus with a Japanese engine recommended for Japanese input

---

## Installation

### Binary (recommended)

Download `comic_viewer_linux.zip` from the [Releases](https://github.com/yourname/comic_viewer/releases) page, extract it, and run the installer:

```bash
unzip comic_viewer_linux.zip
cd comic_viewer
bash install.sh
```

`install.sh` registers the app in your application menu with the correct icon. After that, launch **Comic Viewer** from your app menu or run:

```bash
./comic_viewer
```

### From Source

```bash
# 1. Clone the repository
git clone https://github.com/yourname/comic_viewer.git
cd comic_viewer

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install PySide6 Pillow

# 4. Run
python main.py
```

---

## Data Location

All app data is stored under `~/comic_viewer/`. To uninstall, delete that folder.

| Path | Contents |
|------|----------|
| `~/comic_viewer/library.json` | Registered folders and files |
| `~/comic_viewer/progress.json` | Page progress, bookmarks, rotation |
| `~/comic_viewer/settings.json` | User settings |
| `~/comic_viewer/thumb_cache/` | Cover thumbnail cache |
| `~/comic_viewer/page_cache/` | Page cache |

---

## Uninstall

```bash
# Remove the app shortcut and icon
rm ~/.local/share/applications/comic_viewer.desktop
rm ~/.local/share/icons/comic_viewer.png

# Remove app data (optional)
rm -rf ~/comic_viewer/
```

---

## License

MIT License — Copyright (c) 2026 makushimasu
