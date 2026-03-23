# Photo Picker

A fast, keyboard-friendly photo sorter for Windows. Browse a folder, assign photos to up to 5 named groups, then copy them out in one click.

![screenshot placeholder](docs/screenshot.png)

## Features

- **Thumbnail grid** with lazy background loading
- **Large preview** panel with resizable splitter
- **Group assignment** — up to 5 colour-coded groups per photo
- **Keyboard navigation** — `←` `→` arrows, `Space` / `1`–`5` to toggle groups
- **Mouse wheel** — scrolls the grid or navigates photos (configurable)
- **Two-axis sort** — date order (oldest/newest) combined with orientation split (mixed / landscape first / portrait first)
- **Preview-only mode** — hide the grid, work from the big image alone; group circles appear in the corner and are clickable
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

`photo_picker.bat` is included — just double-click it. If Python or Pillow is missing it prints an error and pauses.

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

### Sort controls (top bar)

Two dropdowns next to the **Sort:** label work together:

| Dropdown | Options | Effect |
|----------|---------|--------|
| Date | Date ↑ oldest first | Oldest files first |
| | Date ↓ newest first | Newest files first |
| Orientation | Mixed | No orientation split; date order preserved |
| | Landscape first | Landscape photos before portrait (date order within each group) |
| | Portrait first | Portrait photos before landscape |

### Settings (⚙ button)

| Option | Description |
|--------|-------------|
| Mouse wheel | Scroll the thumbnail grid **or** navigate photos |
| Preview only | Hide the thumbnail grid; group circles appear on the preview |

Settings are saved to `%LOCALAPPDATA%\PhotoPicker\settings.json` and restored on next launch.

## Supported formats

`.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` `.tiff` `.tif`

## Settings file

`%LOCALAPPDATA%\PhotoPicker\settings.json`

```json
{
  "date_sort": "Date ↑ oldest first",
  "orient_sort": "Mixed",
  "splitter_ratio": 0.42,
  "wheel_nav": false,
  "preview_only": false
}
```

New keys can be added freely — unknown keys are ignored and preserved on save.

## License

MIT — see [LICENSE](LICENSE).
