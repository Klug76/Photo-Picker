"""
photo_picker.py  —  fast photo sorter with group assignment
Usage: python photo_picker.py [folder]  or double-click photo_picker.bat
"""

import json
import os
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
MAX_GROUPS = 5
GROUP_COLORS     = ['#e74c3c', '#2ecc71', '#3498db', '#f39c12', '#9b59b6']
GROUP_COLORS_DIM = ['#5a1818', '#165528', '#122d50', '#5a3a08', '#2e1550']
GROUP_NAMES      = ['group1', 'group2', 'group3', 'group4', 'group5']
CHECK_SIZE = 18
CHECK_PAD  = 4
SEL_BORDER = 3          # selection frame thickness (px)
SEL_COLOR  = '#7ecfff'  # selection frame colour

SETTINGS_FILE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PhotoPicker' / 'settings.json'
DATE_OPTIONS   = ['Date ↑ oldest first', 'Date ↓ newest first']

ORIENT_OPTIONS = ['Mixed', 'Landscape first', 'Portrait first']

# ── helpers ─────────────────────────────────────────────────────────────────
def load_thumb(path, w=THUMB_W, h=THUMB_H):
    try:
        img = Image.open(path)
        img.thumbnail((w, h), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

def load_preview(path, maxside=PREVIEW_MAX):
    try:
        img = Image.open(path)
        img.thumbnail((maxside, maxside), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

# ── thumbnail cell with group-circle overlay ────────────────────────────────
class ThumbCell(tk.Frame):
    def __init__(self, master, path, thumb, n_groups, on_preview, on_toggle, **kw):
        super().__init__(master, bg='#1a1a2e', **kw)
        self.path      = path
        self.n_groups  = n_groups
        self.on_preview = on_preview
        self.on_toggle  = on_toggle
        self._is_focused = False

        name = path.name
        name_short = name if len(name) <= 22 else name[:19] + '…'

        # Border frame: always reserves SEL_BORDER px space; colour changes on focus
        self._border = tk.Frame(self, bg='#1a1a2e',
                                padx=SEL_BORDER, pady=SEL_BORDER)
        self._border.pack()

        self.canvas = tk.Canvas(self._border, width=THUMB_W, height=THUMB_H,
                                bg='#222', highlightthickness=0, cursor='hand2')
        self.canvas.pack()
        self.name_lbl = tk.Label(self, text=name_short,
                                 font=('Consolas', 7), bg='#1a1a2e', fg='#666',
                                 cursor='hand2')
        self.name_lbl.pack()

        self._thumb = thumb
        if thumb:
            self.canvas.create_image(THUMB_W // 2, THUMB_H // 2,
                                     anchor='center', image=thumb)

        self._circle_ids = []
        self._check_ids  = []
        self._hit_boxes  = []

        r = CHECK_SIZE // 2
        for i in range(MAX_GROUPS):
            cx = THUMB_W - CHECK_PAD - r - i * (CHECK_SIZE + 3)
            cy = CHECK_PAD + r
            oid = self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                          fill=GROUP_COLORS_DIM[i],
                                          outline='#000', width=1,
                                          state='normal' if i < n_groups else 'hidden')
            tid = self.canvas.create_text(cx, cy + 1, text='✓',
                                          font=('Arial', 9, 'bold'),
                                          fill='#333',
                                          state='normal' if i < n_groups else 'hidden')
            self._circle_ids.append(oid)
            self._check_ids.append(tid)
            if i < n_groups:
                self._hit_boxes.append((cx - r, cy - r, cx + r, cy + r, i))

        self.canvas.bind('<Button-1>', self._on_click)
        self.name_lbl.bind('<Button-1>', lambda e: self.on_preview(self.path))
        self._selected = set()
        self._redraw()

    def set_focused(self, focused: bool):
        self._is_focused = focused
        color = SEL_COLOR if focused else '#1a1a2e'
        self._border.config(bg=color)

    def _rebuild_hitboxes(self, n):
        self._hit_boxes = []
        r = CHECK_SIZE // 2
        for i in range(n):
            cx = THUMB_W - CHECK_PAD - r - i * (CHECK_SIZE + 3)
            cy = CHECK_PAD + r
            self._hit_boxes.append((cx - r, cy - r, cx + r, cy + r, i))

    def _on_click(self, event):
        x, y = event.x, event.y
        for x1, y1, x2, y2, gi in self._hit_boxes:
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.on_toggle(self.path, gi)
                return
        self.on_preview(self.path)

    def set_groups(self, selected_set):
        self._selected = set(selected_set)
        self._redraw()

    def set_n_groups(self, n):
        self.n_groups = n
        self._rebuild_hitboxes(n)
        for i, (oid, tid) in enumerate(zip(self._circle_ids, self._check_ids)):
            state = 'normal' if i < n else 'hidden'
            self.canvas.itemconfig(oid, state=state)
            self.canvas.itemconfig(tid, state=state)
        self._redraw()

    def _redraw(self):
        for i, (oid, tid) in enumerate(zip(self._circle_ids, self._check_ids)):
            if i in self._selected:
                self.canvas.itemconfig(oid, fill=GROUP_COLORS[i],
                                       outline='white', width=2)
                self.canvas.itemconfig(tid, fill='white')
            else:
                self.canvas.itemconfig(oid, fill=GROUP_COLORS_DIM[i],
                                       outline='#000', width=1)
                self.canvas.itemconfig(tid, fill='#333')


# ── main window ────────────────────────────────────────────────────────────
class PhotoPicker(tk.Tk):
    def __init__(self, folder=None):
        super().__init__()
        self.title("Photo Picker")
        self.configure(bg='#1a1a2e')
        self.state('zoomed')

        self.folder = None
        self.images  = []
        self.thumbs  = {}
        self.selection = {}          # path -> set of group indices
        self.group_count = tk.IntVar(value=3)
        self._settings    = self._load_settings()
        self.date_sort    = tk.StringVar(value=self._settings.get('date_sort', DATE_OPTIONS[0]))
        self.orient_sort  = tk.StringVar(value=self._settings.get('orient_sort', ORIENT_OPTIONS[0]))
        self.sort_mode    = self.orient_sort  # alias kept for _save_settings compat
        self.wheel_nav    = tk.BooleanVar(value=self._settings.get('wheel_nav', False))
        self.preview_only = tk.BooleanVar(value=self._settings.get('preview_only', False))
        self.current_preview = None
        self.thumb_cells = {}
        self._focused_idx = 0

        self._build_ui()
        self.after(200, self._restore_splitter)
        self.after(210, self._apply_preview_only)
        self.bind_all('<Left>',  self._on_key_left)
        self.bind_all('<Right>', self._on_key_right)
        self.bind_all('<space>', self._on_key_space)
        for d in range(1, MAX_GROUPS + 1):
            self.bind_all(str(d), self._on_key_digit)

        if folder and os.path.isdir(folder):
            self._open_folder(folder)
        else:
            self.after(100, self._ask_folder)

    def _build_ui(self):
        fn_label = ('Consolas', 9)
        fn_btn   = ('Consolas', 10, 'bold')

        top = tk.Frame(self, bg='#16213e', pady=6)
        top.pack(fill='x', side='top')

        tk.Button(top, text='📂 Open folder', command=self._ask_folder,
                  font=fn_btn, bg='#0f3460', fg='white',
                  relief='flat', padx=12, pady=4).pack(side='left', padx=8)

        self.lbl_folder = tk.Label(top, text='No folder selected',
                                   font=('Consolas', 10), bg='#16213e', fg='#aaa')
        self.lbl_folder.pack(side='left', padx=8)

        self._legend_items = []  # unused; kept for compat

        tk.Label(top, text='Groups:', font=fn_label,
                 bg='#16213e', fg='#aaa').pack(side='left', padx=(4, 2))
        tk.Spinbox(top, from_=2, to=MAX_GROUPS, textvariable=self.group_count,
                   width=2, font=fn_label,
                   command=self._on_group_count_changed).pack(side='left')

        tk.Button(top, text='⚙', command=self._open_settings,
                  font=fn_btn, bg='#2a3a5e', fg='white',
                  relief='flat', padx=8, pady=4).pack(side='left', padx=(6, 0))

        tk.Label(top, text='Sort:', font=fn_label,
                 bg='#16213e', fg='#aaa').pack(side='left', padx=(12, 2))
        self._date_cb = ttk.Combobox(top, textvariable=self.date_sort,
                                     values=DATE_OPTIONS, state='readonly',
                                     width=18, font=fn_label)
        self._date_cb.pack(side='left', padx=(0, 4))
        self._date_cb.bind('<<ComboboxSelected>>', self._on_sort_changed)
        self._orient_cb = ttk.Combobox(top, textvariable=self.orient_sort,
                                       values=ORIENT_OPTIONS, state='readonly',
                                       width=14, font=fn_label)
        self._orient_cb.pack(side='left')
        self._orient_cb.bind('<<ComboboxSelected>>', self._on_sort_changed)

        tk.Button(top, text='💾 Copy selected',
                  command=self._copy_groups,
                  font=fn_btn, bg='#1a6b4a', fg='white',
                  relief='flat', padx=14, pady=4).pack(side='right', padx=8)

        tk.Button(top, text='✖ Clear selection',
                  command=self._clear_selection,
                  font=fn_btn, bg='#555', fg='white',
                  relief='flat', padx=10, pady=4).pack(side='right', padx=4)

        # coloured per-group counters (right side)
        self._count_frame = tk.Frame(top, bg='#16213e')
        self._count_frame.pack(side='right', padx=10)
        self._count_labels = []
        for i in range(MAX_GROUPS):
            lbl = tk.Label(self._count_frame, text='',
                           font=fn_label, bg='#16213e',
                           fg=GROUP_COLORS[i])
            self._count_labels.append(lbl)

        # ── main area ────────────────────────────────────────────────────────
        main = tk.Frame(self, bg='#1a1a2e')
        main.pack(fill='both', expand=True)

        # left panel — initial width; restored from settings after draw
        self.left_panel = tk.Frame(main, bg='#1a1a2e', width=1000)
        self.left_panel.pack(side='left', fill='y')
        self.left_panel.pack_propagate(False)

        self.preview_canvas = tk.Canvas(self.left_panel, bg='#0d0d1a',
                                        highlightthickness=0)
        self.preview_canvas.pack(fill='both', expand=True, padx=8, pady=8)
        self.preview_canvas.create_text(
            0, 0, tags='hint',
            text='Click a photo\nto preview',
            fill='#444', font=('Consolas', 12), anchor='center')
        self.preview_canvas.bind('<Configure>', self._on_preview_canvas_resize)
        # alias so code that references preview_label still works
        self.preview_label = self.preview_canvas

        self.lbl_fname = tk.Label(self.left_panel, text='',
                                  font=('Consolas', 9), bg='#1a1a2e', fg='#888',
                                  wraplength=480)
        self.lbl_fname.pack(pady=(0, 4))

        # ── splitter ─────────────────────────────────────────────────────────
        self._splitter = tk.Frame(main, bg='#2a3a5e', width=6, cursor='sb_h_double_arrow')
        self._splitter.pack(side='left', fill='y')
        self._splitter.pack_propagate(False)
        self._splitter.bind('<ButtonPress-1>',   self._split_start)
        self._splitter.bind('<B1-Motion>',        self._split_move)
        self._splitter.bind('<ButtonRelease-1>',  self._split_end)
        self._splitter.bind('<Enter>', lambda e: self._splitter.config(bg='#4a6aae'))
        self._splitter.bind('<Leave>', lambda e: self._splitter.config(bg='#2a3a5e'))
        self._split_x = None  # mouse x at drag start
        self._split_w = None  # panel width at drag start

        # refresh preview when left panel is resized
        self.left_panel.bind('<Configure>', self._on_panel_resize)

        self._resize_after_id = None

        self._right = tk.Frame(main, bg='#1a1a2e')
        self._right.pack(side='left', fill='both', expand=True)
        right = self._right

        self.canvas = tk.Canvas(right, bg='#1a1a2e', highlightthickness=0)
        vsb = ttk.Scrollbar(right, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg='#1a1a2e')
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.grid_frame, anchor='nw')

        self.grid_frame.bind('<Configure>', lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self._on_grid_canvas_resize)
        # do NOT force canvas_window width — let grid_frame size itself naturally
        # bind_all so mouse wheel works even when a child widget has focus
        self.bind_all('<MouseWheel>', self._on_mousewheel)
        self.bind_all('<Button-4>',   self._on_mousewheel)
        self.bind_all('<Button-5>',   self._on_mousewheel)

        self._update_legend()

    # ── splitter drag ────────────────────────────────────────────────────────
    def _split_start(self, e):
        self._split_x = e.x_root
        self._split_w = self.left_panel.winfo_width()

    def _split_move(self, e):
        if self._split_x is None:
            return
        delta = e.x_root - self._split_x
        new_w = max(200, min(self._split_w + delta,
                             self.winfo_width() - 300))
        self.left_panel.config(width=new_w)

    def _split_end(self, e):
        self._split_x = None
        self._split_w = None
        self._save_splitter()
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _save_splitter(self):
        total = self.winfo_width()
        if total < 10:
            return
        ratio = round(self.left_panel.winfo_width() / total, 4)
        self._save_settings(splitter_ratio=ratio)

    def _restore_splitter(self):
        ratio = self._settings.get('splitter_ratio')
        if ratio is None:
            return
        self.update_idletasks()
        total = self.winfo_width()
        if total < 10:
            return
        new_w = max(200, min(int(ratio * total), total - 300))
        self.left_panel.config(width=new_w)
        if self.current_preview:
            self._show_preview(self.current_preview)

    # ── panel resize -> debounced preview refresh ────────────────────────────
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
            elif e.num == 5: self.canvas.yview_scroll(3,  'units')
            else:            self.canvas.yview_scroll(int(-e.delta / 40), 'units')

    def _update_legend(self):
        n = self.group_count.get()
        # repack counters: active groups only, right-to-left so group 0 is rightmost
        for lbl in self._count_labels:
            lbl.pack_forget()
        for i in range(n - 1, -1, -1):
            self._count_labels[i].pack(side='left', padx=(0, 6))

    def _on_group_count_changed(self):
        self._update_legend()
        n = self.group_count.get()
        # drop selections that fall outside the new group count
        for path in list(self.selection):
            self.selection[path] = {g for g in self.selection[path] if g < n}
            if not self.selection[path]:
                del self.selection[path]
        for path, cell in self.thumb_cells.items():
            cell.set_n_groups(n)
            cell.set_groups(self.selection.get(path, set()))
        self._update_count_label()

    # ── folder ───────────────────────────────────────────────────────────────
    def _ask_folder(self):
        d = filedialog.askdirectory(title='Select photo folder')
        if d:
            self._open_folder(d)

    def _open_folder(self, folder):
        self.folder = Path(folder)
        raw = [p for p in self.folder.iterdir()
               if p.suffix.lower() in EXTS and p.is_file()]
        self.images = self._sort_images(raw)
        self.thumbs.clear()
        self.selection.clear()
        self.lbl_folder.config(text=str(self.folder))
        self._refresh_grid()
        self._update_count_label()
        if self.images:
            self._focused_idx = 0
            self.after(50, lambda: self._show_preview(self.images[0]))

    # ── settings dialog ──────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = tk.Toplevel(self)
        dlg.title('Settings')
        dlg.configure(bg='#1a1a2e')
        dlg.resizable(False, False)
        dlg.grab_set()

        fn = ('Consolas', 10)
        pad = dict(padx=16, pady=6)

        # local vars — applied only on OK
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

        ttk.Separator(dlg, orient='horizontal').grid(
            row=6, column=0, columnspan=2, sticky='ew', padx=16, pady=6)

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
        btn_frame.grid(row=7, column=0, columnspan=2, pady=(0, 12))
        tk.Button(btn_frame, text='OK', command=on_ok,
                  font=('Consolas', 10, 'bold'), bg='#1a6b4a', fg='white',
                  relief='flat', padx=20, pady=4).pack(side='left', padx=8)
        tk.Button(btn_frame, text='Cancel', command=dlg.destroy,
                  font=('Consolas', 10, 'bold'), bg='#555', fg='white',
                  relief='flat', padx=12, pady=4).pack(side='left', padx=8)

        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - dlg.winfo_width())  // 2
        y = self.winfo_y() + (self.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f'+{x}+{y}')

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
            # Cancel any pending panel-resize callbacks that might interfere
            if self._resize_after_id:
                self.after_cancel(self._resize_after_id)
                self._resize_after_id = None
            # Re-pack right panel and splitter first, then let layout settle
            # before reading winfo_width() — fixes the case where the user
            # never dragged the splitter (no splitter_ratio saved) and the
            # geometry manager hadn't yet reported real window dimensions.
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

    # ── settings / sort ──────────────────────────────────────────────────────
    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                return json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
        return {}

    def _save_settings(self, **extra):
        """Persist settings, merging extra keys on top of existing ones."""
        data = self._load_settings()
        data['date_sort']   = self.date_sort.get()
        data['orient_sort'] = self.orient_sort.get()
        data.update(extra)
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _get_orientation(self, path):
        try:
            with Image.open(path) as im:
                return 'h' if im.width >= im.height else 'v'
        except Exception:
            return 'h'

    def _sort_images(self, images):
        # Step 1: date sort
        date_mode = self.date_sort.get()
        reverse_date = (date_mode == DATE_OPTIONS[1])
        images = sorted(images, key=lambda p: p.stat().st_mtime, reverse=reverse_date)
        # Step 2: orientation split (stable sort preserves date order within each bucket)
        orient_mode = self.orient_sort.get()
        if orient_mode == ORIENT_OPTIONS[0]:  # Mixed — no orientation split
            return images
        orientations = {p: self._get_orientation(p) for p in images}
        if orient_mode == ORIENT_OPTIONS[1]:  # Landscape first
            return sorted(images, key=lambda p: (0 if orientations[p] == 'h' else 1))
        else:                                  # Portrait first
            return sorted(images, key=lambda p: (0 if orientations[p] == 'v' else 1))

    def _on_sort_changed(self, event=None):
        self._save_settings()
        if self.folder:
            raw = [p for p in self.folder.iterdir()
                   if p.suffix.lower() in EXTS and p.is_file()]
            self.images = self._sort_images(raw)
            self.thumbs.clear()
            self._refresh_grid()
            if self.images:
                self._focused_idx = 0
                self.after(50, lambda: self._show_preview(self.images[0]))

    # ── thumbnail grid ───────────────────────────────────────────────────────
    def _refresh_grid(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.thumb_cells = {}
        threading.Thread(target=self._load_thumbs_bg, daemon=True).start()

    def _load_thumbs_bg(self):
        for idx, path in enumerate(self.images):
            if path not in self.thumbs:
                th = load_thumb(path)
                if th:
                    self.thumbs[path] = th
            self.after(0, self._place_thumb, path, idx)

    def _get_cols(self):
        w = self.canvas.winfo_width()
        if w < 10:
            w = self.winfo_width() - self.left_panel.winfo_width() - 20
        # cell width = thumb + 2*padx (3+3=6) + border (2) = THUMB_W + 8
        cols = max(1, w // (THUMB_W + 8))
        return cols

    def _on_grid_canvas_resize(self, e):
        new_cols = self._get_cols()
        if getattr(self, '_last_cols', None) != new_cols and self.thumb_cells:
            self._last_cols = new_cols
            self._regrid()

    def _regrid(self):
        cols = self._get_cols()
        for idx, path in enumerate(self.images):
            cell = self.thumb_cells.get(path)
            if cell is None:
                continue
            row, col = divmod(idx, cols)
            cell.grid(row=row, column=col, padx=3, pady=3)

    def _place_thumb(self, path, idx):
        cols = self._get_cols()
        row, col = divmod(idx, cols)
        th = self.thumbs.get(path)
        n  = self.group_count.get()
        cell = ThumbCell(self.grid_frame, path, th, n,
                         on_preview=self._show_preview,
                         on_toggle=self._on_toggle)
        cell.grid(row=row, column=col, padx=3, pady=3)
        self.thumb_cells[path] = cell
        cell.set_groups(self.selection.get(path, set()))

    def _on_toggle(self, path, group_idx):
        s = self.selection.setdefault(path, set())
        if group_idx in s:
            s.discard(group_idx)
        else:
            s.add(group_idx)
        if not s:
            del self.selection[path]
        cell = self.thumb_cells.get(path)
        if cell:
            cell.set_groups(self.selection.get(path, set()))
        self._update_count_label()
        self._draw_preview_circles()

    # ── preview ──────────────────────────────────────────────────────────────
    def _show_preview(self, path):
        self.current_preview = path
        self.lbl_fname.config(text=path.name)
        if path in self.images:
            self._focused_idx = self.images.index(path)
        self._update_focus_highlight()
        threading.Thread(target=self._load_preview_bg, args=(path,),
                         daemon=True).start()

    def _on_key_left(self, event):
        if not self.images:
            return
        self._focused_idx = (self._focused_idx - 1) % len(self.images)
        self._show_preview(self.images[self._focused_idx])
        self._scroll_to_focused()

    def _on_key_right(self, event):
        if not self.images:
            return
        self._focused_idx = (self._focused_idx + 1) % len(self.images)
        self._show_preview(self.images[self._focused_idx])
        self._scroll_to_focused()

    def _on_key_space(self, event):
        if not self.images:
            return
        path = self.images[self._focused_idx]
        self._on_toggle(path, 0)

    def _on_key_digit(self, event):
        if not self.images:
            return
        try:
            g = int(event.char) - 1
        except (ValueError, AttributeError):
            return
        if 0 <= g < self.group_count.get():
            path = self.images[self._focused_idx]
            self._on_toggle(path, g)

    def _update_focus_highlight(self):
        for idx, path in enumerate(self.images):
            cell = self.thumb_cells.get(path)
            if cell:
                cell.set_focused(idx == self._focused_idx)

    def _scroll_to_focused(self):
        path = self.images[self._focused_idx]
        cell = self.thumb_cells.get(path)
        if not cell:
            return
        self.canvas.update_idletasks()
        cy = cell.winfo_y()
        ch = cell.winfo_height()
        total_h = self.grid_frame.winfo_height()
        if total_h <= 0:
            return
        view_top, view_bot = self.canvas.yview()
        canvas_h = self.canvas.winfo_height()
        cell_top = cy / total_h
        cell_bot = (cy + ch) / total_h
        if cell_top < view_top:
            self.canvas.yview_moveto(cell_top)
        elif cell_bot > view_bot:
            self.canvas.yview_moveto(cell_bot - canvas_h / total_h)

    def _load_preview_bg(self, path):
        pw = max(self.left_panel.winfo_width() - 16, 100)
        ph = max(self.preview_canvas.winfo_height() - 16, 100)
        try:
            with Image.open(path) as src:
                iw, ih = src.size
                scale = min(pw / iw, ph / ih)   # fit, never upscale beyond 1×
                scale = min(scale, 1.0)
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
        c._img = img   # keep a reference so GC doesn't collect it
        cw = c.winfo_width()  or 1
        ch = c.winfo_height() or 1
        c.create_image(cw // 2, ch // 2, anchor='center', image=img, tags='photo')
        self._draw_preview_circles()

    # ── group circles on large preview ───────────────────────────────────────
    def _on_preview_canvas_resize(self, e):
        # re-centre the hint text
        self.preview_canvas.coords('hint', e.width // 2, e.height // 2)
        # redraw photo and circles if a preview is active
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _draw_preview_circles(self):
        c = self.preview_canvas
        c.delete('circles')
        if not self.preview_only.get() or not self.current_preview:
            return
        n = self.group_count.get()
        r = CHECK_SIZE // 2
        pad = CHECK_PAD + 8
        cw = c.winfo_width()
        selected = self.selection.get(self.current_preview, set())
        self._preview_hitboxes = []
        for i in range(n):
            cx = cw - pad - r - i * (CHECK_SIZE + 3)
            cy = pad + r
            if i in selected:
                fill, outline, tick_col, lw = GROUP_COLORS[i], 'white', 'white', 2
            else:
                fill, outline, tick_col, lw = GROUP_COLORS_DIM[i], '#555', '#444', 1
            c.create_oval(cx-r, cy-r, cx+r, cy+r,
                          fill=fill, outline=outline, width=lw, tags='circles')
            c.create_text(cx, cy+1, text='✓',
                          font=('Arial', 9, 'bold'), fill=tick_col, tags='circles')
            self._preview_hitboxes.append((cx-r, cy-r, cx+r, cy+r, i))
        c.tag_bind('circles', '<Button-1>', self._preview_circle_click)

    def _preview_circle_click(self, e):
        if not self.current_preview:
            return
        for x1, y1, x2, y2, gi in getattr(self, '_preview_hitboxes', []):
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                self._on_toggle(self.current_preview, gi)
                return

    # ── group counters ───────────────────────────────────────────────────────
    def _update_count_label(self):
        n = self.group_count.get()
        for i in range(MAX_GROUPS):
            c = sum(1 for s in self.selection.values() if i in s)
            self._count_labels[i].config(text=f'{GROUP_NAMES[i]}: {c}')

    # ── clear selection ─────────────────────────────────────────────────────
    def _clear_selection(self):
        self.selection.clear()
        for cell in self.thumb_cells.values():
            cell.set_groups(set())
        self._update_count_label()

    # ── copy to groups ───────────────────────────────────────────────────────
    def _copy_groups(self):
        if not self.selection:
            messagebox.showinfo('Notice', 'No photos selected.')
            return
        n = self.group_count.get()
        copied  = {i: 0 for i in range(n)}
        skipped = {i: 0 for i in range(n)}
        errors  = []
        for path, groups in self.selection.items():
            for g in groups:
                if g >= n:
                    continue
                dest_dir = self.folder / GROUP_NAMES[g]
                dest_dir.mkdir(exist_ok=True)
                dest = dest_dir / path.name
                if dest.exists():
                    skipped[g] += 1
                    continue
                try:
                    shutil.copy2(path, dest)
                    copied[g] += 1
                except Exception as ex:
                    errors.append(f'{path.name} -> {GROUP_NAMES[g]}: {ex}')

        lines = []
        for i in range(n):
            parts = []
            if copied[i]:  parts.append(f'copied {copied[i]}')
            if skipped[i]: parts.append(f'already exists {skipped[i]}')
            if parts:
                lines.append(f'{GROUP_NAMES[i]}: ' + ', '.join(parts))
        summary = '\n'.join(lines)
        if errors:
            summary += '\n\nErrors:\n' + '\n'.join(errors)
        messagebox.showinfo('Done', summary or 'Nothing was copied.')


# ── entry point ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = PhotoPicker(folder)
    app.mainloop()
