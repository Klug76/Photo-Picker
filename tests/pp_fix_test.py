import sys, tempfile, shutil, time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import photo_picker as pp
from PIL import Image

tmp = Path(tempfile.mkdtemp(prefix='pp_fix_'))
Image.new('RGB', (100, 80), 'red').save(tmp / 'a.jpg')
(tmp / 'a.arw').write_bytes(b'RAWDATA')
Image.new('RGB', (100, 80), 'blue').save(tmp / 'b.jpg')

app = pp.PhotoPicker(str(tmp))
app.update_idletasks()
app.update()
assert len(app.images) == 2, app.images
entry = app.new_group_entry

# 0. Caret and focus indication configured on the entry
assert entry.cget('insertbackground') == '#ddd', entry.cget('insertbackground')
assert entry.cget('highlightcolor') == '#7ecfff', entry.cget('highlightcolor')

# 1. Space in the name entry: text is typed, photo is NOT toggled
entry.focus_set()
app.update()
entry.delete(0, 'end')
entry.insert(0, 'Море')
app.update()
entry.event_generate('<KeyPress-space>')
app.update()
assert app.group_name_var.get() == 'Море ', repr(app.group_name_var.get())
assert len(app.current_selection) == 0, 'photo toggled while typing'

# 2. Enter commits the name, focus leaves the entry, then Space toggles
entry.event_generate('<KeyPress-Return>')
app.update()
assert app.focus_get() is not entry, 'focus stayed in entry'
assert app.group_name_var.get() == 'Море', repr(app.group_name_var.get())
app.event_generate('<KeyPress-space>')
app.update()
assert len(app.current_selection) == 1, 'space did not toggle photo after commit'

# 2b. Grid click (preview callback) moves focus out of the entry; Space works
entry.focus_set()
app.update()
assert app.focus_get() is entry
app._show_preview(app.images[0])
app.update()
assert app.focus_get() is not entry, 'grid click did not move focus from entry'
app.event_generate('<KeyPress-space>')
app.update()
assert len(app.current_selection) != 1, 'space dead after grid click'

app.clear_btn.focus_set()
app._clear_current_selection()
app.update()
assert str(entry.cget('state')) == 'normal', entry.cget('state')
assert app.focus_get() is not app.clear_btn, 'clear button keeps focus'

# 3. Invalid names -> warning, nothing created
with mock.patch.object(pp.messagebox, 'showwarning') as warn, \
     mock.patch.object(pp.messagebox, 'showinfo') as info:
    app.group_name_var.set('Лето/2024')
    app.current_selection.add(tmp / 'a.jpg')
    app._create_and_copy()
    assert warn.call_count == 1, warn.call_count
    assert info.call_count == 0, 'created despite invalid name'
    assert not any(p.name.startswith('Лето') for p in tmp.iterdir())

    app.group_name_var.set('Море.')
    app._create_and_copy()
    assert warn.call_count == 2, warn.call_count
    assert info.call_count == 0
    assert not (tmp / 'Море').exists()

    # 4. Valid Cyrillic name with a space -> folder + JPEG + RAW sidecar
    app.group_name_var.set('Отпуск 2024')
    app._create_and_copy()
    assert info.call_count == 1, info.call_count
    grp = tmp / 'Отпуск 2024'
    assert grp.is_dir(), 'cyrillic group not created'
    assert (grp / 'a.jpg').exists()
    assert (grp / 'a.arw').exists(), 'RAW sidecar not copied'

assert str(entry.cget('state')) == 'normal', entry.cget('state')

# 5. Selecting an existing group disables the name entry
app.group_cb.set('Отпуск 2024')
app._on_group_selected()
app.update()
assert app.current_group == 'Отпуск 2024'
assert str(entry.cget('state')) == 'disabled', entry.cget('state')

# 5b. Arrows and Space work right after picking a group (focus left the combobox)
idx_before = app._focused_idx
app.event_generate('<KeyPress-Right>')
app.update()
assert app._focused_idx != idx_before, 'arrows dead after group selection'
sel_before = len(app.current_selection)
app.event_generate('<KeyPress-space>')
app.update()
assert len(app.current_selection) != sel_before, 'space dead after group selection'

# 5c. Same for the sort combobox: focus must not stick in it
app._date_cb.focus_set()
app._on_sort_changed()
app.update()
assert app.focus_get() is not app._date_cb, 'focus stuck in sort combobox'

# 6. Sync: remove a.jpg (its RAW sidecar must go too), add b.jpg
app.current_selection.clear()
app.current_selection.add(tmp / 'b.jpg')
with mock.patch.object(pp.messagebox, 'showinfo'):
    app._sync_group('Отпуск 2024')
assert not (grp / 'a.jpg').exists(), 'a.jpg not removed'
assert not (grp / 'a.arw').exists(), 'RAW sidecar of removed photo not removed'
assert (grp / 'b.jpg').exists(), 'b.jpg not added'

# 7. Compare peek: RMB on a thumbnail shows it over the current photo, release restores.
#    Assertions run inside mainloop so cross-thread after() callbacks are serviced.
time.sleep(0.3)
app.update()  # let pending after() callbacks (e.g. deferred _show_preview) fire first
cur = app.current_preview
idx = app._focused_idx
sel = set(app.current_selection)
peek_path = tmp / 'a.jpg' if cur == tmp / 'b.jpg' else tmp / 'b.jpg'
cell = app.thumb_cells[peek_path]
state = {}

def _timeout():
    state.setdefault('err', AssertionError('peek timed out'))
    app.quit()

def check_release():
    if app.preview_canvas.find_withtag('peek') or app._peek_path:
        app.after(20, check_release)
        return
    try:
        assert not app._peek_path
        assert not app.preview_canvas.find_withtag('peek'), 'peek frame not removed'
        assert app.lbl_fname.cget('text') == cur.name, app.lbl_fname.cget('text')
        assert app.current_preview == cur
    except AssertionError as e:
        state['err'] = e
    app.quit()

def check_peek():
    if not app.preview_canvas.find_withtag('peek'):
        app.after(20, check_peek)
        return
    try:
        assert app._peek_path == peek_path
        assert app.current_preview == cur, 'current preview changed by peek'
        assert app._focused_idx == idx, 'focus changed by peek'
        assert app.current_selection == sel, 'selection changed by peek'
        assert peek_path.name in app.lbl_fname.cget('text'), app.lbl_fname.cget('text')
        cell.canvas.event_generate('<ButtonRelease-3>')
        app.after(20, check_release)
    except AssertionError as e:
        state['err'] = e
        app.quit()

app.after(8000, _timeout)
cell.canvas.event_generate('<Button-3>')
app.after(50, check_peek)
app.mainloop()
if 'err' in state:
    raise state['err']

# 7b. RMB on the current photo's own thumbnail does nothing
cell_cur = app.thumb_cells[cur]
cell_cur.canvas.event_generate('<Button-3>')
app.update()
assert not app._peek_path, 'peek started on the current photo itself'
assert not app.preview_canvas.find_withtag('peek')
cell_cur.canvas.event_generate('<ButtonRelease-3>')
app.update()
assert not app._peek_path
assert not app.preview_canvas.find_withtag('peek')

print('ALL CHECKS PASSED')
app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
