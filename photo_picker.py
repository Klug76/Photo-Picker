"""
photo_picker.py  —  fast photo sorter with dynamic group folders
Usage: python photo_picker.py [folder]  or double-click photo_picker.bat
"""

import json
import os
import re
import sys
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import threading
import queue
import time
from pathlib import Path

# ── constants ───────────────────────────────────────────────────────────────
THUMB_W, THUMB_H = 160, 120
PREVIEW_MAX = 900
EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
RAW_EXTS = {'.arw', '.cr2', '.cr3', '.nef', '.dng', '.orf', '.rw2', '.raf'}
CHECK_SIZE = 18
CHECK_PAD  = 4
SEL_BORDER = 3
SEL_COLOR  = '#7ecfff'

SELECT_COLOR = '#2ecc71'
DIM_COLOR    = '#165528'

BTN_DEFAULT_BG = '#555'
BTN_CLEAR_BG   = '#f39c12'
BTN_NEW_BG     = '#1a6b4a'
BTN_SYNC_BG    = '#f39c12'

SETTINGS_FILE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PhotoPicker' / 'settings.json'
DATE_OPTIONS   = ['Date ↑ oldest first', 'Date ↓ newest first']
ORIENT_OPTIONS = ['Mixed', 'Landscape first', 'Portrait first']


def load_thumb(path, w=THUMB_W, h=THUMB_H):
    try:
        img = Image.open(path)
        img.thumbnail((w, h), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


class ThumbCell(tk.Frame):
    def __init__(self, master, path, thumb, on_preview, on_toggle, on_hover=None, **kw):
        super().__init__(master, bg='#1a1a2e', **kw)
        self.path = path
        self.on_preview = on_preview
        self.on_toggle = on_toggle
        self.on_hover = on_hover or (lambda p: None)
        self._is_focused = False
        self._selected = False
        self._thumb_image = None

        name = path.name
        name_short = name if len(name) <= 22 else name[:19] + '…'

        self._border = tk.Frame(self, bg='#1a1a2e', padx=SEL_BORDER, pady=SEL_BORDER)
        self._border.pack()

        self.canvas = tk.Canvas(self._border, width=THUMB_W, height=THUMB_H,
                                bg='#222', highlightthickness=0, cursor='hand2')
        self.canvas.pack()
        self.name_lbl = tk.Label(self, text=name_short,
                                 font=('Consolas', 7), bg='#1a1a2e', fg='#666',
                                 cursor='hand2')
        self.name_lbl.pack()

        r = CHECK_SIZE // 2
        self._cx = THUMB_W - CHECK_PAD - r
        self._cy = CHECK_PAD + r
        self._circle_id = self.canvas.create_oval(self._cx-r, self._cy-r, self._cx+r, self._cy+r,
                                                  fill=DIM_COLOR, outline='#000', width=1)
        self._check_id = self.canvas.create_text(self._cx, self._cy+1, text='✓',
                                                 font=('Arial', 9, 'bold'), fill='#333')

        self._hit_box = (self._cx-r, self._cy-r, self._cx+r, self._cy+r)

        self.canvas.bind('<Button-1>', self._on_click)
        self.name_lbl.bind('<Button-1>', lambda e: self.on_preview(self.path))
        self.canvas.bind('<Enter>', lambda e: self.on_hover(self.path))
        self.canvas.bind('<Leave>', lambda e: self.on_hover(None))
        self.name_lbl.bind('<Enter>', lambda e: self.on_hover(self.path))
        self.name_lbl.bind('<Leave>', lambda e: self.on_hover(None))

        self._redraw()

    def set_focused(self, focused: bool):
        self._is_focused = focused
        self._border.config(bg=SEL_COLOR if focused else '#1a1a2e')

    def set_selected(self, selected: bool):
        self._selected = selected
        self._redraw()

    def _on_click(self, event):
        x, y = event.x, event.y
        x1, y1, x2, y2 = self._hit_box
        if x1 <= x <= x2 and y1 <= y <= y2:
            self.on_toggle(self.path)
            return
        self.on_preview(self.path)

    def set_thumb(self, thumb):
        """Set thumbnail after cell creation"""
        self._thumb_image = thumb
        self.canvas.delete('thumb')
        if thumb:
            self.canvas.create_image(THUMB_W // 2, THUMB_H // 2, anchor='center', image=thumb, tag='thumb')
            # Bring check mark above thumbnail z-index
            self.canvas.tag_raise(self._circle_id)
            self.canvas.tag_raise(self._check_id)

    def _redraw(self):
        if self._selected:
            fill, outline, width, tick = SELECT_COLOR, 'white', 2, 'white'
            self.canvas.itemconfig(self._circle_id, state='normal', fill=fill, outline=outline, width=width)
            self.canvas.itemconfig(self._check_id, state='normal', fill=tick)
        else:
            self.canvas.itemconfig(self._circle_id, state='hidden')
            self.canvas.itemconfig(self._check_id, state='hidden')


class PhotoPicker(tk.Tk):
    def __init__(self, folder=None):
        super().__init__()
        self.title("Photo Picker")
        self.configure(bg='#1a1a2e')
        self.state('zoomed')

        self.folder = None
        self.images = []
        self.thumbs = {}
        self.current_selection = set()
        self.current_group = None
        self.groups = []

        self._settings = self._load_settings()
        self.date_sort = tk.StringVar(value=self._settings.get('date_sort', DATE_OPTIONS[0]))
        self.orient_sort = tk.StringVar(value=self._settings.get('orient_sort', ORIENT_OPTIONS[0]))
        self.wheel_nav = tk.BooleanVar(value=self._settings.get('wheel_nav', False))
        self.preview_only = tk.BooleanVar(value=self._settings.get('preview_only', False))
        self.group_name_var = tk.StringVar()

        self.current_preview = None

        self._preview_zoom_active = False
        self._preview_zoom_img = None
        self._preview_zoom_photo = None
        self._zoom_offset_x = 0
        self._zoom_offset_y = 0
        self._last_mouse_x = 0
        self._last_mouse_y = 0
        self.zoom_factor = int(self._settings.get('zoom_factor', 200))  # percent, e.g. 200 = 2x
        self.show_histogram = tk.BooleanVar(value=self._settings.get('show_histogram', True))
        self._histogram_data = None  # list of (r_vals, g_vals, b_vals) length-256 tuples
        self._thumb_histo_after_id = None  # pending hover histogram update
        self._histogram_cache = {}  # path -> (r[256], g[256], b[256])

        self.thumb_cells = {}
        self._focused_idx = 0
        self._resize_after_id = None
        self._split_x = None
        self._split_w = None

        # Smart thumbnail loader
        self._thumb_queue = queue.PriorityQueue()
        self._thumb_workers = []
        self._thumb_stop = False
        self._scroll_after_id = None

        self._build_ui()
        self.bind('<FocusOut>', lambda e: self._end_zoom())
        self.after(200, self._restore_splitter)
        self.after(210, self._apply_preview_only)

        self.bind_all('<Left>',  self._on_key_left)
        self.bind_all('<Right>', self._on_key_right)
        self.bind_all('<space>', self._on_key_space)

        if folder and os.path.isdir(folder):
            self._open_folder(folder)
        else:
            self.after(100, self._ask_folder)

    def _build_ui(self):
        fn_label = ('Consolas', 9)
        fn_btn = ('Consolas', 10, 'bold')

        top = tk.Frame(self, bg='#16213e', pady=6)
        top.pack(fill='x', side='top')

        tk.Button(top, text='📂 Open folder', command=self._ask_folder,
                  font=fn_btn, bg='#0f3460', fg='white', relief='flat', padx=12, pady=4).pack(side='left', padx=8)

        tk.Button(top, text='⚙', command=self._open_settings,
                  font=fn_btn, bg='#2a3a5e', fg='white',
                  relief='flat', padx=8, pady=4).pack(side='left', padx=(6, 4))

        self._hist_btn = tk.Button(top, text='▦', command=self._toggle_histogram,
                  font=fn_btn, bg='#2a3a5e', fg='white',
                  relief='flat', padx=8, pady=4)
        self._hist_btn.pack(side='left', padx=(0, 12))
        self._update_hist_btn()

        tk.Label(top, text='Sort:', font=fn_label, bg='#16213e', fg='#aaa').pack(side='left', padx=(20, 2))
        self._date_cb = ttk.Combobox(top, textvariable=self.date_sort, values=DATE_OPTIONS, state='readonly', width=18, font=fn_label)
        self._date_cb.pack(side='left', padx=(0, 4))
        self._date_cb.bind('<<ComboboxSelected>>', self._on_sort_changed)

        self._orient_cb = ttk.Combobox(top, textvariable=self.orient_sort, values=ORIENT_OPTIONS, state='readonly', width=14, font=fn_label)
        self._orient_cb.pack(side='left')
        self._orient_cb.bind('<<ComboboxSelected>>', self._on_sort_changed)

        tk.Label(top, text='   Group:', font=fn_label, bg='#16213e', fg='#aaa').pack(side='left', padx=(20, 2))
        self.group_cb = ttk.Combobox(top, state='readonly', width=22, font=fn_label)
        self.group_cb.pack(side='left', padx=(0, 8))
        self.group_cb.bind('<<ComboboxSelected>>', self._on_group_selected)

        tk.Label(top, text='New group name:', font=fn_label, bg='#16213e', fg='#aaa').pack(side='left', padx=(12, 2))
        self.new_group_entry = tk.Entry(top, textvariable=self.group_name_var, width=16, font=fn_label, bg='#222', fg='#ddd')
        self.new_group_entry.pack(side='left', padx=(0, 12))

        self.selected_label = tk.Label(top, text='Selected: 0',
                                       font=('Consolas', 10, 'bold'), bg='#16213e', fg='#7ecfff')
        self.selected_label.pack(side='left', padx=(10, 20))

        # iOS-style spinner
        self._spinner_frame = tk.Frame(top, bg='#16213e')
        self._spinner_canvas = tk.Canvas(self._spinner_frame, width=40, height=40,
                                         bg='#16213e', highlightthickness=0)
        self._spinner_canvas.pack()
        self._spinner_angle = 0
        self._spinner_after_id = None
        self._loading_total = 0
        self._loading_done = 0

        # Fixed width buttons — prevents jumping when text length changes
        self.copy_btn = tk.Button(top, text='💾 Copy selected\nto "group1"', command=self._apply_groups,
                                  font=fn_btn, bg=BTN_DEFAULT_BG, fg='white', relief='flat',
                                  padx=12, pady=8, width=28, height=2, anchor='center')
        self.copy_btn.pack(side='right', padx=8)

        self.clear_btn = tk.Button(top, text='✖ Clear\nselection', command=self._clear_current_selection,
                                   font=fn_btn, bg=BTN_DEFAULT_BG, fg='white', relief='flat',
                                   padx=10, pady=8, width=16, height=2, anchor='center')
        self.clear_btn.pack(side='right', padx=4)

        # Main area
        main = tk.Frame(self, bg='#1a1a2e')
        main.pack(fill='both', expand=True)

        self.left_panel = tk.Frame(main, bg='#1a1a2e', width=1000)
        self.left_panel.pack(side='left', fill='y')
        self.left_panel.pack_propagate(False)

        self.preview_canvas = tk.Canvas(self.left_panel, bg='#0d0d1a', highlightthickness=0)
        self.preview_canvas.pack(fill='both', expand=True, padx=8, pady=8)
        self.preview_canvas.create_text(0, 0, tags='hint', text='Click a photo\nto preview',
                                        fill='#444', font=('Consolas', 12), anchor='center')
        self.preview_canvas.bind('<Configure>', self._on_preview_canvas_resize)

        self.lbl_fname = tk.Label(self.left_panel, text='', font=('Consolas', 9), bg='#1a1a2e', fg='#888', wraplength=480)
        self.lbl_fname.pack(pady=(0, 4))

        self._splitter = tk.Frame(main, bg='#2a3a5e', width=6, cursor='sb_h_double_arrow')
        self._splitter.pack(side='left', fill='y')
        self._splitter.pack_propagate(False)
        self._splitter.bind('<ButtonPress-1>', self._split_start)
        self._splitter.bind('<B1-Motion>', self._split_move)
        self._splitter.bind('<ButtonRelease-1>', self._split_end)
        self._splitter.bind('<Enter>', lambda e: self._splitter.config(bg='#4a6aae'))
        self._splitter.bind('<Leave>', lambda e: self._splitter.config(bg='#2a3a5e'))

        self.left_panel.bind('<Configure>', self._on_panel_resize)

        self._right = tk.Frame(main, bg='#1a1a2e')
        self._right.pack(side='left', fill='both', expand=True)

        self.canvas = tk.Canvas(self._right, bg='#1a1a2e', highlightthickness=0)
        vsb = ttk.Scrollbar(self._right, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg='#1a1a2e')
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')

        # Fixed histogram panel at the bottom of the right panel
        self._thumb_hist_canvas = tk.Canvas(self._right, bg='#0d0d1a',
                                            width=200, height=80,
                                            highlightthickness=1,
                                            highlightbackground='#334')
        self._thumb_hist_canvas.pack(side='bottom', anchor='center', pady=(0, 6))

        self.grid_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self._on_grid_canvas_resize)

        self.canvas.bind('<MouseWheel>', self._on_grid_scroll)
        self.canvas.bind('<Button-4>', self._on_grid_scroll)
        self.canvas.bind('<Button-5>', self._on_grid_scroll)
        self.canvas.bind('<B1-Motion>', self._on_grid_scroll)

        self.bind_all('<MouseWheel>', self._on_mousewheel)
        self.bind_all('<Button-4>', self._on_mousewheel)
        self.bind_all('<Button-5>', self._on_mousewheel)

        self.group_name_var.trace('w', lambda *args: self._update_ui_state())

    # ==================== ALL REQUIRED METHODS ====================

    def _ask_folder(self):
        d = filedialog.askdirectory(title='Select photo folder')
        if d:
            self._open_folder(d)

    def _open_folder(self, folder):
        self.folder = Path(folder)
        raw = [p for p in self.folder.iterdir() if p.suffix.lower() in EXTS and p.is_file()]
        self.images = self._sort_images(raw)

        # Complete state reset
        self.thumbs.clear()
        self._histogram_cache.clear()
        self.current_selection.clear()
        self.current_group = None          # ← Important fix

        self.title(f"Photo Picker — {self.folder}")

        self._refresh_groups_list()
        self.group_cb.set('(no group)')    # ← Reset combobox
        self.group_name_var.set(self._get_next_group_name())

        self._refresh_grid()
        self.canvas.yview_moveto(0)        # reset scroll

        if self.images:
            self._focused_idx = 0
            self.after(50, lambda: self._show_preview(self.images[0]))

        self._update_ui_state()

    def _update_ui_state(self, *args):
        count = len(self.current_selection)
        self.selected_label.config(text=f'Selected: {count}')

        self.clear_btn.config(bg=BTN_CLEAR_BG if count > 0 else BTN_DEFAULT_BG)

        if count == 0:
            # Nothing selected
            next_name = self.group_name_var.get().strip() or self._get_next_group_name()
            self.copy_btn.config(
                bg=BTN_DEFAULT_BG,
                text=f'💾 Copy selected\nto "{next_name}"'
            )
            return

        if self.current_group:
            # Existing group selected
            dest_dir = self.folder / self.current_group
            current_in_group = set()

            if dest_dir.exists():
                for f in dest_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in EXTS:
                        main_p = self.folder / f.name
                        if main_p in self.images:
                            current_in_group.add(main_p)

            to_add = self.current_selection - current_in_group
            to_remove = current_in_group - self.current_selection

            if to_add and not to_remove:
                # Only adding new photos → green button (like new group)
                self.copy_btn.config(
                    bg=BTN_NEW_BG,
                    text=f'💾 Add to\n"{self.current_group}"'
                )
            elif to_remove:
                # There are items to delete (synchronization needed) → orange
                self.copy_btn.config(
                    bg=BTN_SYNC_BG,
                    text=f'Synchronize\n"{self.current_group}"'
                )
            else:
                # Fully synchronized
                self.copy_btn.config(
                    bg=BTN_DEFAULT_BG,
                    text=f'💾 Copy selected\nto "{self.current_group}"\n(already synced)'
                )
        else:
            # Creating new group
            name = self.group_name_var.get().strip() or self._get_next_group_name()
            self.copy_btn.config(
                bg=BTN_NEW_BG,
                text=f'💾 Copy selected\nto "{name}"'
            )

    def _split_start(self, e):
        self._split_x = e.x_root
        self._split_w = self.left_panel.winfo_width()

    def _split_move(self, e):
        if self._split_x is None:
            return
        delta = e.x_root - self._split_x
        new_w = max(200, min(self._split_w + delta, self.winfo_width() - 300))
        self.left_panel.config(width=new_w)

    def _split_end(self, e):
        self._split_x = self._split_w = None
        self._save_splitter()
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _save_splitter(self):
        total = self.winfo_width()
        if total < 10: return
        ratio = round(self.left_panel.winfo_width() / total, 4)
        self._save_settings(splitter_ratio=ratio)

    def _restore_splitter(self):
        ratio = self._settings.get('splitter_ratio')
        if ratio is None: return
        self.update_idletasks()
        total = self.winfo_width()
        if total < 10: return
        new_w = max(200, min(int(ratio * total), total - 300))
        self.left_panel.config(width=new_w)
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _on_panel_resize(self, e):
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(120, self._on_panel_resize_done)

    def _on_panel_resize_done(self):
        self._resize_after_id = None
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _on_mousewheel(self, e):
        if self.wheel_nav.get() and self.images:
            if e.num == 4 or (hasattr(e, 'delta') and e.delta > 0):
                self._on_key_left(e)
            else:
                self._on_key_right(e)
        else:
            if e.num == 4:   self.canvas.yview_scroll(-3, 'units')
            elif e.num == 5: self.canvas.yview_scroll(3, 'units')
            else:            self.canvas.yview_scroll(int(-e.delta / 40), 'units')

    def _refresh_groups_list(self):
        if not self.folder: return
        groups = [d.name for d in self.folder.iterdir() if d.is_dir()]
        groups.sort()
        self.groups = groups
        self.group_cb['values'] = ['(no group)'] + groups

    def _get_next_group_name(self):
        return self._get_next_available_name("group1")

    def _get_next_available_name(self, proposed: str) -> str:
        if not proposed: proposed = "group1"
        if not self.folder or not (self.folder / proposed).exists():
            return proposed
        match = re.search(r'(\d+)$', proposed)
        prefix = proposed[:match.start()] if match else proposed
        num = int(match.group(1)) + 1 if match else 1
        while (self.folder / f"{prefix}{num}").exists():
            num += 1
        return f"{prefix}{num}"

    def _on_group_selected(self, event=None):
        val = self.group_cb.get()
        self.current_group = None if val == '(no group)' or not val else val

        if self.current_group:
            self._load_group_selection(self.current_group)
            self._update_all_cells()
            self.after(100, self._scroll_to_first_selected)
        else:
            self.current_selection.clear()
            self._update_all_cells()

        self._update_ui_state()

    def _load_group_selection(self, group_name: str):
        self.current_selection.clear()
        dest_dir = self.folder / group_name
        if dest_dir.exists():
            for f in dest_dir.iterdir():
                if f.is_file() and f.suffix.lower() in EXTS:
                    main_p = self.folder / f.name
                    if main_p in self.images:
                        self.current_selection.add(main_p)

    def _update_all_cells(self):
        for path, cell in self.thumb_cells.items():
            cell.set_selected(path in self.current_selection)

    def _on_toggle(self, path):
        if path in self.current_selection:
            self.current_selection.discard(path)
        else:
            self.current_selection.add(path)
        cell = self.thumb_cells.get(path)
        if cell: cell.set_selected(path in self.current_selection)
        if self.current_preview == path:
            self._draw_preview_circles()
        self._update_ui_state()

    def _clear_current_selection(self):
        self.current_selection.clear()
        self.current_group = None
        self.group_cb.set('(no group)')
        self.group_name_var.set(self._get_next_group_name())

        self._update_all_cells()
        self._draw_preview_circles()
        self._update_ui_state()

    def _apply_groups(self):
        if not self.current_selection:
            return
        if self.current_group:
            self._sync_group(self.current_group)
        else:
            self._create_and_copy()

    def _find_raw_sidecar(self, jpeg_path):
        """Return a list of RAW files in the same folder with the same stem."""
        stem = jpeg_path.stem
        folder = jpeg_path.parent
        return [
            folder / (stem + ext)
            for ext in RAW_EXTS
            if (folder / (stem + ext)).exists()
        ] + [
            folder / (stem + ext.upper())
            for ext in RAW_EXTS
            if (folder / (stem + ext.upper())).exists()
        ]

    def _create_and_copy(self):
        proposed = self.group_name_var.get().strip() or "group1"
        actual_name = self._get_next_available_name(proposed)
        dest_dir = self.folder / actual_name
        dest_dir.mkdir(exist_ok=True)

        copied = 0
        errors = []
        for path in self.current_selection:
            dest = dest_dir / path.name
            if not dest.exists():
                try:
                    shutil.copy2(path, dest)
                    copied += 1
                except Exception as ex:
                    errors.append(f'{path.name}: {ex}')
            for raw in self._find_raw_sidecar(path):
                raw_dest = dest_dir / raw.name
                if not raw_dest.exists():
                    try:
                        shutil.copy2(raw, raw_dest)
                    except Exception as ex:
                        errors.append(f'{raw.name}: {ex}')

        summary = f'Created group "{actual_name}" and copied {copied} photo(s).'
        if errors:
            summary += '\n\nErrors:\n' + '\n'.join(errors)
        messagebox.showinfo('Done', summary)

        self.current_selection.clear()
        self.current_group = None
        self.group_cb.set('(no group)')
        self._update_all_cells()
        self._refresh_groups_list()
        self.group_name_var.set(self._get_next_group_name())
        self._update_ui_state()

    def _sync_group(self, group_name: str):
        dest_dir = self.folder / group_name
        if not dest_dir.exists(): return

        added = removed = 0
        errors = []

        for path in list(self.current_selection):
            dest = dest_dir / path.name
            if not dest.exists():
                try:
                    shutil.copy2(path, dest)
                    added += 1
                except Exception as ex:
                    errors.append(str(ex))
            for raw in self._find_raw_sidecar(path):
                raw_dest = dest_dir / raw.name
                if not raw_dest.exists():
                    try:
                        shutil.copy2(raw, raw_dest)
                    except Exception as ex:
                        errors.append(f'{raw.name}: {ex}')

        for f in list(dest_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in EXTS:
                main_p = self.folder / f.name
                if main_p in self.images and main_p not in self.current_selection:
                    try:
                        f.unlink()
                        removed += 1
                    except Exception as ex:
                        errors.append(str(ex))
                    # Also remove the RAW sidecar if it exists in the group folder
                    for raw in self._find_raw_sidecar(path):
                        raw_in_dest = dest_dir / raw.name
                        if raw_in_dest.exists():
                            try:
                                raw_in_dest.unlink()
                            except Exception as ex:
                                errors.append(f'{raw_in_dest.name}: {ex}')

        summary = f'Synchronized "{group_name}": added {added}, removed {removed}'
        if errors:
            summary += '\n\nErrors:\n' + '\n'.join(errors)
        messagebox.showinfo('Done', summary)

        self._load_group_selection(group_name)
        self._update_all_cells()
        self._draw_preview_circles()
        self._update_ui_state()

    def _sort_images(self, images):
        date_mode = self.date_sort.get()
        reverse = (date_mode == DATE_OPTIONS[1])
        images = sorted(images, key=lambda p: p.stat().st_mtime, reverse=reverse)

        orient_mode = self.orient_sort.get()
        if orient_mode == ORIENT_OPTIONS[0]:
            return images

        orientations = {}
        for p in images:
            try:
                with Image.open(p) as im:
                    orientations[p] = 'h' if im.width >= im.height else 'v'
            except:
                orientations[p] = 'h'

        if orient_mode == ORIENT_OPTIONS[1]:
            return sorted(images, key=lambda p: 0 if orientations[p] == 'h' else 1)
        else:
            return sorted(images, key=lambda p: 0 if orientations[p] == 'v' else 1)

    def _on_sort_changed(self, event=None):
        self._save_settings()
        if self.folder:
            raw = [p for p in self.folder.iterdir() if p.suffix.lower() in EXTS and p.is_file()]
            self.images = self._sort_images(raw)
            self.thumbs.clear()
            self._refresh_grid()
            if self.images:
                self._focused_idx = 0
                self.after(50, lambda: self._show_preview(self.images[0]))

    def _refresh_grid(self):
        # Stop existing worker threads
        self._thumb_stop = True
        while not self._thumb_queue.empty():
            try: self._thumb_queue.get(block=False)
            except: pass

        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.thumb_cells = {}

        # Create ALL cells first, before thumbnails load
        cols = self._get_cols()
        for idx, path in enumerate(self.images):
            th = self.thumbs.get(path)
            cell = ThumbCell(self.grid_frame, path, th, self._show_preview, self._on_toggle,
                            on_hover=self._on_thumb_hover)
            row, col = divmod(idx, cols)
            cell.grid(row=row, column=col, padx=3, pady=3)
            self.thumb_cells[path] = cell
            cell.set_selected(path in self.current_selection)

        # Grid is fully ready, scroll works immediately!
        self._thumb_stop = False

        # Start 3 worker threads for loading
        for _ in range(3):
            t = threading.Thread(target=self._thumb_worker, daemon=True)
            t.start()
            self._thumb_workers.append(t)

        if self.images:
            self.after(10, self._spinner_show)
            self.after(50, self._schedule_thumb_load)

    def _on_grid_scroll(self, e=None):
        """Handler for any scroll position changes"""
        if self._scroll_after_id:
            self.after_cancel(self._scroll_after_id)
        # Wait until user stops scrolling for 120ms
        self._scroll_after_id = self.after(120, self._schedule_thumb_load)

    def _schedule_thumb_load(self):
        """Redistribute loading priorities based on visible area"""
        if not self.images:
            return

        total_h = self.grid_frame.winfo_height() or 1
        view_top, view_bot = self.canvas.yview()
        canvas_h = self.canvas.winfo_height()
        cell_h = THUMB_H + 6
        cols = self._get_cols()

        first_visible_idx = int(view_top * total_h / cell_h) * cols
        last_visible_idx = int(view_bot * total_h / cell_h) * cols

        # Clear old queue
        while not self._thumb_queue.empty():
            try: self._thumb_queue.get(block=False)
            except: pass

        # Add tasks with priority
        for idx, path in enumerate(self.images):
            if path in self.thumbs:
                continue

            # Calculate priority (lower = higher priority)
            dist = abs(idx - (first_visible_idx + last_visible_idx)//2)
            # Currently visible - highest priority
            if first_visible_idx - cols*2 <= idx <= last_visible_idx + cols*2:
                priority = 0
            # Near visible area
            elif first_visible_idx - cols*10 <= idx <= last_visible_idx + cols*10:
                priority = 1000
            # Further down the list
            else:
                priority = 10000 + dist

            self._thumb_queue.put( (priority, idx, path) )

        # Check if loading is complete every second
        self.after(1000, self._check_loading_complete)

    def _thumb_worker(self):
        """Worker thread for loading thumbnails"""
        while not self._thumb_stop:
            try:
                priority, idx, path = self._thumb_queue.get(timeout=0.2)
                if self._thumb_stop:
                    break

                if path in self.thumbs:
                    self._thumb_queue.task_done()
                    continue

                th = load_thumb(path)
                if th:
                    self.thumbs[path] = th
                    self.after(0, self._update_thumb, path, th)

                self._thumb_queue.task_done()

            except queue.Empty:
                continue

        # When all threads finish - hide spinner
        self.after(0, self._check_loading_complete)

    def _check_loading_complete(self):
        """Check if all thumbnails have finished loading"""
        if not self._thumb_stop and all(p in self.thumbs for p in self.images):
            self._spinner_hide()
        elif not self._thumb_stop:
            # Keep checking until everything is loaded
            self.after(1000, self._check_loading_complete)

    def _get_cols(self):
        w = self.canvas.winfo_width() or (self.winfo_width() - self.left_panel.winfo_width() - 20)
        return max(1, w // (THUMB_W + 8))

    def _on_grid_canvas_resize(self, e):
        if getattr(self, '_last_cols', None) != self._get_cols() and self.thumb_cells:
            self._last_cols = self._get_cols()
            self._regrid()

    def _regrid(self):
        cols = self._get_cols()
        for idx, path in enumerate(self.images):
            cell = self.thumb_cells.get(path)
            if cell:
                row, col = divmod(idx, cols)
                cell.grid(row=row, column=col, padx=3, pady=3)

    def _update_thumb(self, path, thumb):
        """Update thumbnail in already created cell"""
        cell = self.thumb_cells.get(path)
        if cell:
            cell.set_thumb(thumb)

    def _spinner_show(self):
        if self._spinner_after_id:
            return
        self._spinner_frame.pack(side='right', padx=4)
        self._spinner_tick()

    def _spinner_hide(self):
        if self._spinner_after_id:
            self.after_cancel(self._spinner_after_id)
            self._spinner_after_id = None
        self._spinner_frame.pack_forget()

    def _spinner_tick(self):
        import math
        c = self._spinner_canvas
        c.delete('all')
        cx, cy, r_out, r_in = 20, 20, 16, 8
        n = 12
        for i in range(n):
            angle = math.radians((self._spinner_angle + i * 30) % 360)
            val = int(40 + (i + 1) / n * 185)
            color = f'#{val:02x}{val:02x}{val:02x}'
            x1 = cx + r_in * math.cos(angle)
            y1 = cy + r_in * math.sin(angle)
            x2 = cx + r_out * math.cos(angle)
            y2 = cy + r_out * math.sin(angle)
            c.create_line(x1, y1, x2, y2, fill=color, width=2.5, capstyle='round')
        self._spinner_angle = (self._spinner_angle - 30) % 360
        self._spinner_after_id = self.after(80, self._spinner_tick)

    def _show_preview(self, path):
        self.current_preview = path
        self.lbl_fname.config(text=path.name)
        if path in self.images:
            self._focused_idx = self.images.index(path)
        self._update_focus_highlight()
        threading.Thread(target=self._load_preview_bg, args=(path,), daemon=True).start()

    def _on_key_left(self, event):
        if not self.images: return
        self._focused_idx = (self._focused_idx - 1) % len(self.images)
        self._show_preview(self.images[self._focused_idx])
        self._scroll_to_focused()

    def _on_key_right(self, event):
        if not self.images: return
        self._focused_idx = (self._focused_idx + 1) % len(self.images)
        self._show_preview(self.images[self._focused_idx])
        self._scroll_to_focused()

    def _on_key_space(self, event):
        if self.images:
            self._on_toggle(self.images[self._focused_idx])

    def _update_focus_highlight(self):
        for idx, path in enumerate(self.images):
            if path in self.thumb_cells:
                self.thumb_cells[path].set_focused(idx == self._focused_idx)

    def _scroll_to_focused(self):
        path = self.images[self._focused_idx]
        cell = self.thumb_cells.get(path)
        if not cell: return
        self.canvas.update_idletasks()
        cy = cell.winfo_y()
        ch = cell.winfo_height()
        total_h = self.grid_frame.winfo_height()
        if total_h <= 0: return
        view_top, view_bot = self.canvas.yview()
        canvas_h = self.canvas.winfo_height()
        cell_top = cy / total_h
        cell_bot = (cy + ch) / total_h
        if cell_top < view_top:
            self.canvas.yview_moveto(cell_top)
        elif cell_bot > view_bot:
            self.canvas.yview_moveto(cell_bot - canvas_h / total_h)

    def _scroll_to_first_selected(self):
        """Scrolls the grid to show the first selected item"""
        if not self.current_selection:
            return

        first_selected = None
        for path in self.images:
            if path in self.current_selection:
                first_selected = path
                break

        if not first_selected:
            return

        cell = self.thumb_cells.get(first_selected)
        if not cell:
            return

        self.canvas.config(scrollregion=self.canvas.bbox('all'))
        self.update_idletasks()

        cy = cell.winfo_y()
        ch = cell.winfo_height()
        total_h = self.grid_frame.winfo_height()

        if total_h <= 0:
            return

        target = max(0, cy - ch * 2) / total_h
        self.canvas.yview_moveto(target)

    def _load_preview_bg(self, path):
        try:
            with Image.open(path) as src:
                self._preview_zoom_img = src.copy()  # full-res copy for zoom
                pw = max(self.left_panel.winfo_width() - 32, 200)
                ph = max(self.preview_canvas.winfo_height() - 32, 200)
                scale = min(pw / src.width, ph / src.height, 1.0)
                resized = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
                if path not in self._histogram_cache:
                    self._histogram_cache[path] = self._compute_histogram(resized)
                hdata = self._histogram_cache[path]
                img = ImageTk.PhotoImage(resized)
        except Exception:
            img = None
            hdata = None
            self._preview_zoom_img = None

        if path == self.current_preview:
            self._histogram_data = hdata
            self.after(0, lambda: self._set_preview(img))


    def _set_preview(self, img):
        c = self.preview_canvas
        c.delete('all')
        c._img = img
        cw = c.winfo_width() or 1
        ch = c.winfo_height() or 1
        c.create_image(cw//2, ch//2, anchor='center', image=img, tags='photo')

        self._draw_preview_circles()
        self._draw_histogram()

        c.bind('<ButtonPress-1>', self._start_zoom)
        c.bind('<ButtonRelease-1>', self._end_zoom)
        c.bind('<B1-Motion>', self._on_zoom_motion)



    # ── Histogram ─────────────────────────────────────────────────────────────

    def _compute_histogram(self, pil_img):
        """Return (r[256], g[256], b[256]) raw counts from a PIL image."""
        rgb = pil_img.convert('RGB')
        raw = rgb.histogram()   # 768 values: R*256 + G*256 + B*256
        r = raw[0:256]
        g = raw[256:512]
        b = raw[512:768]
        return (r, g, b)

    def _toggle_histogram(self):
        self.show_histogram.set(not self.show_histogram.get())
        self._update_hist_btn()
        self._save_settings(show_histogram=self.show_histogram.get())
        if self.current_preview:
            self._draw_histogram()

    def _update_hist_btn(self):
        active = self.show_histogram.get()
        self._hist_btn.config(bg='#1a6b4a' if active else '#2a3a5e')

    def _draw_histogram(self):
        """Draw RGB histogram overlay in the bottom-left corner of the preview canvas."""
        c = self.preview_canvas
        c.delete('histogram')

        if not self.show_histogram.get() or not self._histogram_data:
            return

        PAD   = 10   # margin from canvas edge
        W, H  = 200, 80
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 10 or ch < 10:
            return

        x0 = PAD
        y0 = ch - PAD - H
        x1 = x0 + W
        y1 = y0 + H

        # Semi-transparent background (stipple trick — no true alpha in tkinter Canvas)
        c.create_rectangle(x0, y0, x1, y1,
                           fill='#0d0d1a', outline='#334', width=1,
                           stipple='gray50', tags='histogram')
        # Solid inner backdrop at reduced opacity feel
        c.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1,
                           fill='#0d0d1a', outline='',
                           tags='histogram')

        r_vals, g_vals, b_vals = self._histogram_data

        # Skip pure-black bucket (index 0) to avoid it dominating the scale
        peak = max(
            max(r_vals[1:]), max(g_vals[1:]), max(b_vals[1:]), 1
        )

        INNER_X = x0 + 4
        INNER_W = W - 8
        INNER_Y = y0 + 4
        INNER_H = H - 8

        for channel, color in ((r_vals, '#e05555'), (g_vals, '#55e055'), (b_vals, '#5588e0')):
            pts = []
            for i, val in enumerate(channel):
                cx = INNER_X + int(i / 255 * (INNER_W - 1))
                bar_h = int(val / peak * INNER_H)
                cy = INNER_Y + INNER_H - bar_h
                pts.append((cx, cy))

            # Draw as polyline (fast, one canvas item per channel)
            if len(pts) >= 2:
                flat = [coord for pt in pts for coord in pt]
                c.create_line(*flat, fill=color, width=1,
                              tags='histogram')

        # Thin border on top
        c.create_rectangle(x0, y0, x1, y1,
                           fill='', outline='#446', width=1,
                           tags='histogram')

    # ── Thumbnail hover histogram ──────────────────────────────────────────────

    def _on_thumb_hover(self, path):
        """Called when mouse enters/leaves a thumbnail cell. path=None on leave."""
        if self._thumb_histo_after_id:
            self.after_cancel(self._thumb_histo_after_id)
            self._thumb_histo_after_id = None

        if path is None:
            self._draw_thumb_histogram(None)
            return

        # Use cached histogram immediately if available (same data as large preview)
        if path in self._histogram_cache:
            self._draw_thumb_histogram(self._histogram_cache[path])
            return

        # Not yet cached — load in background with small delay to avoid thrashing
        self._thumb_histo_after_id = self.after(80, lambda: self._load_thumb_histogram(path))

    def _load_thumb_histogram(self, path):
        """Load thumbnail histogram in background thread and cache the result."""
        self._thumb_histo_after_id = None
        def _work():
            try:
                with Image.open(path) as im:
                    small = im.copy()
                    small.thumbnail((160, 120), Image.BILINEAR)
                    hdata = self._compute_histogram(small)
                    self._histogram_cache[path] = hdata
            except Exception:
                hdata = None
            self.after(0, lambda: self._draw_thumb_histogram(hdata))
        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _draw_thumb_histogram(self, hdata):
        """Render RGB histogram into the fixed panel below the thumbnail grid."""
        c = self._thumb_hist_canvas
        c.delete('all')
        if not hdata:
            return

        W = c.winfo_width() or 200
        H = c.winfo_height() or 80

        # Background
        c.create_rectangle(0, 0, W, H, fill='#0d0d1a', outline='')

        r_vals, g_vals, b_vals = hdata
        peak = max(max(r_vals[1:]), max(g_vals[1:]), max(b_vals[1:]), 1)

        PAD_X, PAD_Y = 4, 4
        IW = W - PAD_X * 2
        IH = H - PAD_Y * 2

        for channel, color in ((r_vals, '#e05555'), (g_vals, '#55e055'), (b_vals, '#5588e0')):
            pts = []
            for i, val in enumerate(channel):
                cx = PAD_X + int(i / 255 * (IW - 1))
                bar_h = int(val / peak * IH)
                cy = PAD_Y + IH - bar_h
                pts.append((cx, cy))
            if len(pts) >= 2:
                flat = [coord for pt in pts for coord in pt]
                c.create_line(*flat, fill=color, width=1)

        # Border
        c.create_rectangle(0, 0, W - 1, H - 1, fill='', outline='#446', width=1)

    def _cursor_to_orig(self, mouse_x, mouse_y):
        """Convert canvas mouse coordinates to original image pixel coordinates."""
        c = self.preview_canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        ow, oh = self._preview_zoom_img.size
        scale_fit = min(cw / ow, ch / oh, 1.0)
        img_display_w = ow * scale_fit
        img_display_h = oh * scale_fit
        offset_x = (cw - img_display_w) / 2
        offset_y = (ch - img_display_h) / 2
        x_orig = (mouse_x - offset_x) / scale_fit
        y_orig = (mouse_y - offset_y) / scale_fit
        return x_orig, y_orig

    def _start_zoom(self, event):
        if not self._preview_zoom_img:
            return
        self._preview_zoom_active = True
        self._apply_zoom(event.x, event.y)


    def _apply_zoom(self, mouse_x=None, mouse_y=None):
        """Render zoomed view centered on the current cursor position in the original image."""
        if not self._preview_zoom_img or not self._preview_zoom_active:
            return

        c = self.preview_canvas
        cw = c.winfo_width()
        ch = c.winfo_height()
        ow, oh = self._preview_zoom_img.size

        # Use last known mouse position if not provided
        if mouse_x is None:
            mouse_x = self._last_mouse_x
        if mouse_y is None:
            mouse_y = self._last_mouse_y

        self._last_mouse_x = mouse_x
        self._last_mouse_y = mouse_y

        # Factor: e.g. 200% means 1 canvas pixel = 1/2 original pixel
        factor = self.zoom_factor / 100.0  # e.g. 2.0
        # Crop size in original pixels that fills the canvas at this zoom level
        crop_w = cw / factor
        crop_h = ch / factor

        # Map cursor to original image coordinates
        x_orig, y_orig = self._cursor_to_orig(mouse_x, mouse_y)

        # Top-left of the crop so cursor point is at canvas center
        left = x_orig - crop_w / 2
        top  = y_orig - crop_h / 2

        # Clamp so we never go outside the image
        left = max(0.0, min(left, ow - crop_w))
        top  = max(0.0, min(top,  oh - crop_h))
        right  = left + crop_w
        bottom = top  + crop_h

        try:
            cropped = self._preview_zoom_img.crop((int(left), int(top), int(right), int(bottom)))
            zoomed = cropped.resize((cw, ch), Image.NEAREST)

            self._preview_zoom_photo = ImageTk.PhotoImage(zoomed)
            c.delete('photo')
            c.create_image(cw // 2, ch // 2, anchor='center', image=self._preview_zoom_photo, tags='photo')

        except Exception as e:
            print(f"[ZOOM ERROR] {e}")

    def _end_zoom(self, event=None):
        self._preview_zoom_active = False
        if self.current_preview:
            threading.Thread(target=self._load_preview_bg,
                             args=(self.current_preview,), daemon=True).start()


    def _on_zoom_motion(self, event):
        if not self._preview_zoom_active:
            return
        self._apply_zoom(event.x, event.y)


    def _on_preview_canvas_resize(self, e):
        self.preview_canvas.coords('hint', e.width//2, e.height//2)
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _draw_preview_circles(self):
        c = self.preview_canvas
        c.delete('circles')
        if not self.preview_only.get() or not self.current_preview:
            return
        selected = self.current_preview in self.current_selection
        r = CHECK_SIZE // 2
        pad = CHECK_PAD + 8
        cw = c.winfo_width()
        cx = cw - pad - r
        cy = pad + r

        if selected:
            fill, outline, lw, tick_col = SELECT_COLOR, 'white', 2, 'white'
            c.create_oval(cx-r, cy-r, cx+r, cy+r, fill=fill, outline=outline, width=lw, tags='circles')
            c.create_text(cx, cy+1, text='✓', font=('Arial', 9, 'bold'), fill=tick_col, tags='circles')

        self._preview_hitbox = (cx-r, cy-r, cx+r, cy+r)
        c.tag_bind('circles', '<Button-1>', self._preview_circle_click)

    def _preview_circle_click(self, e):
        if not self.current_preview: return
        x1,y1,x2,y2 = getattr(self, '_preview_hitbox', (0,0,0,0))
        if x1 <= e.x <= x2 and y1 <= e.y <= y2:
            self._on_toggle(self.current_preview)

    def _apply_preview_only(self):
        mode = self.preview_only.get()
        if mode:
            self._splitter.pack_forget()
            self._right.pack_forget()
            def _set_width():
                w = max(self.winfo_width(), 200)
                self.left_panel.config(width=w)
            self.after(20, _set_width)
        else:
            if self._resize_after_id:
                self.after_cancel(self._resize_after_id)
                self._resize_after_id = None
            self._splitter.pack_forget()
            self._right.pack_forget()
            self._splitter.pack(side='left', fill='y')
            self._right.pack(side='left', fill='both', expand=True)
            self.update_idletasks()
            ratio = self._settings.get('splitter_ratio', 0.5)
            total = self.winfo_width()
            if total > 10:
                safe_w = max(200, int(total * ratio))
                self.left_panel.config(width=safe_w)
            self.after(50, self._restore_splitter)
        if self.current_preview:
            self.after(100, lambda: self._show_preview(self.current_preview))

    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                return json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {}

    def _save_settings(self, **extra):
        data = self._load_settings()
        data['date_sort'] = self.date_sort.get()
        data['orient_sort'] = self.orient_sort.get()
        data.update(extra)
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _open_settings(self):
        dlg = tk.Toplevel(self)
        dlg.title('Settings')
        dlg.configure(bg='#1a1a2e')
        dlg.resizable(False, False)
        dlg.grab_set()

        fn = ('Consolas', 10)
        pad = dict(padx=16, pady=6)

        # local vars
        v_wheel   = tk.BooleanVar(value=self.wheel_nav.get())
        v_preview = tk.BooleanVar(value=self.preview_only.get())
        v_zoom    = tk.IntVar(value=self.zoom_factor)

        tk.Label(dlg, text='Mouse wheel behaviour',
                 font=('Consolas', 10, 'bold'), bg='#1a1a2e', fg='#7ecfff'
                 ).grid(row=0, column=0, columnspan=2, sticky='w', padx=16, pady=(14, 2))

        tk.Radiobutton(dlg, text='Scroll thumbnail grid',
                       variable=v_wheel, value=False,
                       font=fn, bg='#1a1a2e', fg='#ccc',
                       selectcolor='#0f3460', activebackground='#1a1a2e'
                       ).grid(row=1, column=0, columnspan=2, sticky='w', **pad)

        tk.Radiobutton(dlg, text='Navigate photos (prev / next)',
                       variable=v_wheel, value=True,
                       font=fn, bg='#1a1a2e', fg='#ccc',
                       selectcolor='#0f3460', activebackground='#1a1a2e'
                       ).grid(row=2, column=0, columnspan=2, sticky='w', **pad)

        ttk.Separator(dlg, orient='horizontal').grid(
            row=3, column=0, columnspan=2, sticky='ew', padx=16, pady=6)

        tk.Label(dlg, text='View',
                 font=('Consolas', 10, 'bold'), bg='#1a1a2e', fg='#7ecfff'
                 ).grid(row=4, column=0, columnspan=2, sticky='w', padx=16, pady=(2, 2))

        tk.Checkbutton(dlg, text='Preview only (hide thumbnail grid)',
                       variable=v_preview,
                       font=fn, bg='#1a1a2e', fg='#ccc',
                       selectcolor='#0f3460', activebackground='#1a1a2e'
                       ).grid(row=5, column=0, columnspan=2, sticky='w', **pad)

        ttk.Separator(dlg, orient='horizontal').grid(
            row=6, column=0, columnspan=2, sticky='ew', padx=16, pady=6)

        tk.Label(dlg, text='Right-click zoom',
                 font=('Consolas', 10, 'bold'), bg='#1a1a2e', fg='#7ecfff'
                 ).grid(row=7, column=0, columnspan=2, sticky='w', padx=16, pady=(2, 2))

        zoom_row = tk.Frame(dlg, bg='#1a1a2e')
        zoom_row.grid(row=8, column=0, columnspan=2, sticky='w', padx=16, pady=6)
        tk.Label(zoom_row, text='Zoom level:', font=fn, bg='#1a1a2e', fg='#ccc').pack(side='left')
        zoom_spin = tk.Spinbox(zoom_row, from_=110, to=800, increment=10,
                               textvariable=v_zoom, width=5, font=fn,
                               bg='#222', fg='#ddd', buttonbackground='#444',
                               relief='flat', justify='center')
        zoom_spin.pack(side='left', padx=(8, 4))
        tk.Label(zoom_row, text='%', font=fn, bg='#1a1a2e', fg='#ccc').pack(side='left')

        def on_ok():
            self.wheel_nav.set(v_wheel.get())
            prev_only = self.preview_only.get()
            self.preview_only.set(v_preview.get())
            zoom_val = max(110, min(800, v_zoom.get()))
            self.zoom_factor = zoom_val
            self._save_settings(
                wheel_nav=v_wheel.get(),
                preview_only=v_preview.get(),
                zoom_factor=zoom_val,
                show_histogram=self.show_histogram.get()
            )
            if v_preview.get() != prev_only:
                self._apply_preview_only()
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg='#1a1a2e')
        btn_frame.grid(row=9, column=0, columnspan=2, pady=(0, 12))
        tk.Button(btn_frame, text='OK', command=on_ok,
                  font=('Consolas', 10, 'bold'), bg='#1a6b4a', fg='white',
                  relief='flat', padx=20, pady=4).pack(side='left', padx=8)
        tk.Button(btn_frame, text='Cancel', command=dlg.destroy,
                  font=('Consolas', 10, 'bold'), bg='#555', fg='white',
                  relief='flat', padx=12, pady=4).pack(side='left', padx=8)

        # center dialog
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - dlg.winfo_width())  // 2
        y = self.winfo_y() + (self.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f'+{x}+{y}')

if __name__ == '__main__':
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = PhotoPicker(folder)
    app.mainloop()