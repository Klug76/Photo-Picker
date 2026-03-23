# Photo Picker

A fast, keyboard-friendly photo sorter for Windows. Browse a folder, assign photos to up to 5 named groups, then copy them out in one click.

![screenshot placeholder](docs/screenshot.png)

## Features

- **Thumbnail grid** with lazy background loading
- **Large preview** panel with resizable splitter
- **Group assignment** — up to 5 colour-coded groups per photo
- **Keyboard navigation** — `←` `→` arrows, `Space` / `1`–`5` to toggle groups
- **Mouse wheel** — scrolls the grid or navigates photos (configurable)
- **Sort order** — by name, horizontals first, or verticals first
- **Preview-only mode** — hide the grid, work from the big image alone; group circles appear in the corner
- **Settings dialog** — all options in one place, persisted between sessions
- **Safe copy** — files already present in a destination folder are skipped, never overwritten

## Requirements

- Python 3.8+
- [Pillow](https://python-pillow.org/)

```
pip install Pillow
```

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/photo-picker.git
cd photo-picker
pip install Pillow
python photo_picker.py
```

Or pass a folder directly:

```bash
python photo_picker.py C:\Photos\Vacation
```

### Windows: double-click launcher

Create `photo_picker.bat` next to the script:

```bat
@echo off
python "%~dp0photo_picker.py" %*
pause
```

## Usage

### Basic workflow

1. Click **📂 Open folder** (or pass a path on the command line).
2. Click a thumbnail to see the large preview. Use **← →** or the **mouse wheel** to navigate.
3. Press **Space** to toggle group 1, or **1–5** to toggle any group. You can also click the coloured circles on the thumbnail (or on the preview in preview-only mode).
4. Click **💾 Copy selected** — each group is copied into a subfolder named `group1`, `group2`, … inside the source folder.

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `←` `→` | Previous / next photo |
| `Space` | Toggle group 1 |
| `1` – `5` | Toggle group 1–5 |

### Settings (⚙ button)

| Option | Description |
|--------|-------------|
| Mouse wheel | Scroll the thumbnail grid **or** navigate photos |
| Preview-only mode | Hide the thumbnail grid; group circles appear on the preview |

Settings are saved to `%LOCALAPPDATA%\PhotoPicker\settings.json` and restored on next launch. The file is plain JSON — you can edit it by hand.

### Sort order

The **Sort** dropdown (top bar) controls the order photos appear in the grid:

| Option | Order |
|--------|-------|
| По имени | Alphabetical (default) |
| Горизонтальные первыми | Landscape photos first, then portrait |
| Вертикальные первыми | Portrait photos first, then landscape |

## Supported formats

`.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` `.tiff` `.tif`

## Settings file

`%LOCALAPPDATA%\PhotoPicker\settings.json`

```json
{
  "sort_mode": "По имени",
  "splitter_ratio": 0.42,
  "wheel_nav": false,
  "preview_only": false
}
```

New keys can be added freely — unknown keys are ignored and preserved on save.

## License

MIT — see [LICENSE](LICENSE).
