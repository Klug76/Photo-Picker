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
from pathlib import Path

# ── constants ───────────────────────────────────────────────────────────────
THUMB_W, THUMB_H = 160, 120
PREVIEW_MAX = 900
EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
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
    def __init__(self, master, path, thumb, on_preview, on_toggle, **kw):
        super().__init__(master, bg='#1a1a2e', **kw)
        self.path = path
        self.on_preview = on_preview
        self.on_toggle = on_toggle
        self._is_focused = False
        self._selected = False

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

        if thumb:
            self.canvas.create_image(THUMB_W // 2, THUMB_H // 2, anchor='center', image=thumb)

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

    def _redraw(self):
        if self._selected:
            fill, outline, width, tick = SELECT_COLOR, 'white', 2, 'white'
        else:
            fill, outline, width, tick = DIM_COLOR, '#000', 1, '#333'
        self.canvas.itemconfig(self._circle_id, fill=fill, outline=outline, width=width)
        self.canvas.itemconfig(self._check_id, fill=tick)


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
        self.thumb_cells = {}
        self._focused_idx = 0
        self._resize_after_id = None
        self._split_x = None
        self._split_w = None

        self._build_ui()
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
                  relief='flat', padx=8, pady=4).pack(side='left', padx=(6, 12))

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

        self.grid_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self._on_grid_canvas_resize)

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
            self.after(50, self._scroll_to_first_selected)   # ← new
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

        for f in list(dest_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in EXTS:
                main_p = self.folder / f.name
                if main_p in self.images and main_p not in self.current_selection:
                    try:
                        f.unlink()
                        removed += 1
                    except Exception as ex:
                        errors.append(str(ex))

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
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.thumb_cells = {}
        threading.Thread(target=self._load_thumbs_bg, daemon=True).start()

    def _load_thumbs_bg(self):
        for idx, path in enumerate(self.images):
            if path not in self.thumbs:
                th = load_thumb(path)
                if th: self.thumbs[path] = th
            self.after(0, self._place_thumb, path, idx)

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

    def _place_thumb(self, path, idx):
        cols = self._get_cols()
        row, col = divmod(idx, cols)
        th = self.thumbs.get(path)
        cell = ThumbCell(self.grid_frame, path, th, self._show_preview, self._on_toggle)
        cell.grid(row=row, column=col, padx=3, pady=3)
        self.thumb_cells[path] = cell
        cell.set_selected(path in self.current_selection)

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

        # Find first selected item in current images order
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

        self.canvas.update_idletasks()

        cy = cell.winfo_y()
        ch = cell.winfo_height()
        total_h = self.grid_frame.winfo_height()

        if total_h <= 0:
            return

        # Scroll so top of selected item is slightly above viewport center
        target = max(0, cy - ch * 2) / total_h
        self.canvas.yview_moveto(target)

    def _load_preview_bg(self, path):
        pw = max(self.left_panel.winfo_width() - 16, 100)
        ph = max(self.preview_canvas.winfo_height() - 16, 100)
        try:
            with Image.open(path) as src:
                iw, ih = src.size
                scale = min(min(pw / iw, ph / ih), 1.0)
                nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                resized = src.resize((nw, nh), Image.LANCZOS)
                img = ImageTk.PhotoImage(resized)
        except Exception:
            img = None
        if img and path == self.current_preview:
            self.after(0, self._set_preview, img)

    def _set_preview(self, img):
        c = self.preview_canvas
        c.delete('all')
        c._img = img
        cw = c.winfo_width() or 1
        ch = c.winfo_height() or 1
        c.create_image(cw//2, ch//2, anchor='center', image=img, tags='photo')
        self._draw_preview_circles()

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
        else:
            fill, outline, lw, tick_col = DIM_COLOR, '#555', 1, '#444'

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

        def on_ok():
            self.wheel_nav.set(v_wheel.get())
            prev_only = self.preview_only.get()
            self.preview_only.set(v_preview.get())
            self._save_settings(
                wheel_nav=v_wheel.get(),
                preview_only=v_preview.get()
            )
            if v_preview.get() != prev_only:
                self._apply_preview_only()
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg='#1a1a2e')
        btn_frame.grid(row=6, column=0, columnspan=2, pady=(0, 12))
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