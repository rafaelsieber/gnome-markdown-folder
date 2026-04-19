"""
Main window — uses the most modern libadwaita 1.10 / GTK4 widgets:

  • AdwNavigationSplitView  — responsive sidebar + content
  • AdwBreakpoint           — collapses at narrow widths
  • AdwToolbarView          — proper toolbar regions
  • AdwTabView + AdwTabBar  — multi-file tabs
  • AdwToggleGroup          — Edit / Preview switcher (1.7)
  • AdwBanner               — per-tab unsaved-changes bar (1.3)
  • AdwToastOverlay         — save / error toasts
  • AdwAlertDialog          — "unsaved changes?" prompt (1.5)
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

# Optional: GtkSource for syntax highlighting
try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource
    _HAVE_SOURCE = True
except Exception:
    _HAVE_SOURCE = False


# ── helpers ──────────────────────────────────────────────────────────────────

def _run_git(cwd: Path, *args: str) -> tuple[str, str, int]:
    import subprocess
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15
        )
        return r.stdout, r.stderr, r.returncode
    except Exception as e:
        return "", str(e), -1


def _is_git_repo(path: Path) -> bool:
    _, _, rc = _run_git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0


_MD_EXTS = {".md", ".markdown", ".mdx", ".txt", ".rst"}

APP_ID = "io.github.rafaelsieber.markdownfolder"


# ── user config ───────────────────────────────────────────────────────────────

def _config_path() -> Path:
    cfg_dir = Path(GLib.get_user_config_dir()) / APP_ID
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(_config_path().read_text())
    except Exception:
        return {}


def _save_config(data: dict):
    try:
        _config_path().write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ── per-tab editor state ─────────────────────────────────────────────────────

class EditorPage(GObject.Object):
    """Holds the state for one open file tab."""

    __gtype_name__ = "EditorPage"

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._modified = False

        # --- build widget tree ---
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # unsaved-changes banner
        self.banner = Adw.Banner(
            title="Unsaved changes",
            button_label="Save",
            revealed=False,
        )
        self.banner.connect("button-clicked", lambda _: self.save())
        self.root.append(self.banner)

        # view stack: editor / preview
        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.root.append(self.stack)

        # — editor —
        scroll_ed = Gtk.ScrolledWindow(vexpand=True)
        if _HAVE_SOURCE:
            buf = GtkSource.Buffer()
            lm = GtkSource.LanguageManager.get_default()
            lang = lm.get_language("markdown")
            if lang:
                buf.set_language(lang)
            sm = GtkSource.StyleSchemeManager.get_default()
            scheme = sm.get_scheme("Adwaita-dark") or sm.get_scheme("classic")
            if scheme:
                buf.set_style_scheme(scheme)
            self.text_view = GtkSource.View(buffer=buf)
            self.text_view.set_show_line_numbers(True)
            self.text_view.set_highlight_current_line(True)
            self.text_view.set_auto_indent(True)
            self.text_view.set_tab_width(2)
        else:
            self.text_view = Gtk.TextView()

        self.text_view.set_monospace(True)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_left_margin(12)
        self.text_view.set_right_margin(12)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.text_view.get_buffer().connect("changed", self._on_changed)
        scroll_ed.set_child(self.text_view)
        self.stack.add_named(scroll_ed, "edit")

        # — preview —
        scroll_pr = Gtk.ScrolledWindow(vexpand=True)
        self.preview_view = Gtk.TextView(
            editable=False,
            cursor_visible=False,
            left_margin=20,
            right_margin=20,
            top_margin=16,
            bottom_margin=16,
        )
        self.preview_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll_pr.set_child(self.preview_view)
        self.stack.add_named(scroll_pr, "preview")

        # callbacks
        self._on_save_cb: list = []

    # ── modification tracking ─────────────────────────────────────────────

    def _on_changed(self, _buf):
        if not self._modified:
            self._modified = True
            self.banner.set_revealed(True)
            self.notify("modified")

    def get_modified(self) -> bool:
        return self._modified

    # ── file I/O ──────────────────────────────────────────────────────────

    def load(self) -> bool:
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        buf = self.text_view.get_buffer()
        buf.handler_block_by_func(self._on_changed)
        buf.set_text(text)
        buf.handler_unblock_by_func(self._on_changed)
        self._modified = False
        self.banner.set_revealed(False)
        return True

    def save(self) -> bool:
        buf = self.text_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        try:
            self.path.write_text(text, encoding="utf-8")
        except OSError:
            return False
        self._modified = False
        self.banner.set_revealed(False)
        self.notify("modified")
        for cb in self._on_save_cb:
            cb(self)
        return True

    # ── view switching ────────────────────────────────────────────────────

    def show_edit(self):
        self.stack.set_visible_child_name("edit")

    def show_preview(self):
        buf = self.text_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        _render_markdown(self.preview_view, text)
        self.stack.set_visible_child_name("preview")

    def current_view_name(self) -> str:
        child = self.stack.get_visible_child()
        return self.stack.get_page(child).get_name() if child else "edit"


# ── markdown preview renderer ─────────────────────────────────────────────────

def _render_markdown(tv: Gtk.TextView, text: str):
    buf = tv.get_buffer()
    buf.set_text("")
    tt = buf.get_tag_table()

    def tag(name: str, **kw) -> Gtk.TextTag:
        t = tt.lookup(name)
        if t is None:
            t = buf.create_tag(name, **kw)
        return t

    tag("h1", weight=Pango.Weight.BOLD, scale=2.0,
        pixels_above_lines=14, pixels_below_lines=6)
    tag("h2", weight=Pango.Weight.BOLD, scale=1.6,
        pixels_above_lines=12, pixels_below_lines=4)
    tag("h3", weight=Pango.Weight.BOLD, scale=1.3,
        pixels_above_lines=8, pixels_below_lines=2)
    tag("h4", weight=Pango.Weight.BOLD, scale=1.1)
    tag("bold", weight=Pango.Weight.BOLD)
    tag("italic", style=Pango.Style.ITALIC)
    tag("strike", strikethrough=True)
    tag("code_inline", family="monospace",
        background="#2d2d2d", foreground="#f8f8f2",
        pixels_above_lines=1, pixels_below_lines=1)
    tag("code_block", family="monospace",
        background="#1e1e1e", foreground="#d4d4d4",
        left_margin=16, right_margin=16,
        pixels_above_lines=4, pixels_below_lines=4)
    tag("blockquote", foreground="#aaaaaa",
        style=Pango.Style.ITALIC, left_margin=28)
    tag("hr", foreground="#555555")
    tag("bullet", left_margin=20)
    tag("link", foreground="#4a9eff", underline=Pango.Underline.SINGLE)

    _INLINE = re.compile(
        r'\*\*(.+?)\*\*'       # **bold**
        r'|__(.+?)__'          # __bold__
        r'|\*(.+?)\*'          # *italic*
        r'|_(.+?)_'            # _italic_
        r'|~~(.+?)~~'          # ~~strike~~
        r'|`(.+?)`'            # `code`
        r'|\[(.+?)\]\((.+?)\)' # [text](url)
    )

    def insert_inline(line_text: str, default_tag: str | None = None):
        last = 0
        for m in _INLINE.finditer(line_text):
            before = line_text[last:m.start()]
            if before:
                e = buf.get_end_iter()
                if default_tag:
                    buf.insert_with_tags_by_name(e, before, default_tag)
                else:
                    buf.insert(e, before)
            e = buf.get_end_iter()
            if m.group(1):   buf.insert_with_tags_by_name(e, m.group(1), "bold")
            elif m.group(2): buf.insert_with_tags_by_name(e, m.group(2), "bold")
            elif m.group(3): buf.insert_with_tags_by_name(e, m.group(3), "italic")
            elif m.group(4): buf.insert_with_tags_by_name(e, m.group(4), "italic")
            elif m.group(5): buf.insert_with_tags_by_name(e, m.group(5), "strike")
            elif m.group(6): buf.insert_with_tags_by_name(e, m.group(6), "code_inline")
            elif m.group(7): buf.insert_with_tags_by_name(e, m.group(7), "link")
            last = m.end()
        rest = line_text[last:]
        if rest:
            e = buf.get_end_iter()
            if default_tag:
                buf.insert_with_tags_by_name(e, rest, default_tag)
            else:
                buf.insert(e, rest)

    lines = text.split("\n")
    in_code = False
    code_lines: list[str] = []

    for line in lines:
        e = buf.get_end_iter()

        if line.startswith("```"):
            if in_code:
                in_code = False
                block = "\n".join(code_lines)
                buf.insert_with_tags_by_name(buf.get_end_iter(),
                                             block + "\n", "code_block")
                code_lines = []
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if line.startswith("#### "):
            insert_inline(line[5:], "h4"); buf.insert(buf.get_end_iter(), "\n")
        elif line.startswith("### "):
            insert_inline(line[4:], "h3"); buf.insert(buf.get_end_iter(), "\n")
        elif line.startswith("## "):
            insert_inline(line[3:], "h2"); buf.insert(buf.get_end_iter(), "\n")
        elif line.startswith("# "):
            insert_inline(line[2:], "h1"); buf.insert(buf.get_end_iter(), "\n")
        elif line.startswith("> "):
            insert_inline(line[2:], "blockquote")
            buf.insert(buf.get_end_iter(), "\n")
        elif re.match(r'^[-*_]{3,}$', line.strip()):
            buf.insert_with_tags_by_name(buf.get_end_iter(),
                                         "─" * 72 + "\n", "hr")
        elif re.match(r'^[-*+] ', line):
            buf.insert_with_tags_by_name(buf.get_end_iter(), "  • ", "bullet")
            insert_inline(line[2:], "bullet")
            buf.insert(buf.get_end_iter(), "\n")
        elif re.match(r'^\d+\. ', line):
            m = re.match(r'^(\d+)\. (.*)', line)
            if m:
                buf.insert_with_tags_by_name(
                    buf.get_end_iter(), f"  {m.group(1)}. ", "bullet")
                insert_inline(m.group(2), "bullet")
                buf.insert(buf.get_end_iter(), "\n")
        else:
            insert_inline(line)
            buf.insert(buf.get_end_iter(), "\n")


# ── main window ───────────────────────────────────────────────────────────────

class MarkdownWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Markdown Folder")
        self.set_default_size(1280, 800)
        self.set_icon_name("text-editor-symbolic")

        self._root_path: Path | None = None
        self._is_git = False
        # map path → AdwTabPage
        self._open_tabs: dict[Path, Adw.TabPage] = {}

        self._build_ui()
        self._setup_actions()
        self._setup_breakpoint()
        self._restore_last_folder()

    # ── breakpoint (responsive) ───────────────────────────────────────────

    def _setup_breakpoint(self):
        bp = Adw.Breakpoint()
        condition = Adw.BreakpointCondition.parse("max-width: 720sp")
        bp.set_condition(condition)
        bp.add_setter(self._split_view, "collapsed", True)
        self.add_breakpoint(bp)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        # Toast overlay wraps everything
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # NavigationSplitView: sidebar | content
        self._split_view = Adw.NavigationSplitView(
            min_sidebar_width=200,
            max_sidebar_width=320,
            sidebar_width_fraction=0.22,
        )
        self._toast_overlay.set_child(self._split_view)

        self._split_view.set_sidebar(self._build_sidebar_page())
        self._split_view.set_content(self._build_content_page())

    # ── sidebar ───────────────────────────────────────────────────────────

    def _build_sidebar_page(self) -> Adw.NavigationPage:
        page = Adw.NavigationPage(title="Files")

        toolbar = Adw.ToolbarView()
        page.set_child(toolbar)

        # header bar
        hbar = Adw.HeaderBar()

        open_btn = Gtk.Button(icon_name="folder-open-symbolic",
                              tooltip_text="Open folder (Ctrl+O)")
        open_btn.connect("clicked", self._on_open_folder)
        hbar.pack_start(open_btn)

        # menu button
        menu = Gio.Menu()
        menu.append("New Window", "app.new-window")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
            primary=True,
        )
        hbar.pack_end(menu_btn)

        toolbar.add_top_bar(hbar)

        # folder label
        self._folder_label = Gtk.Label(
            label="No folder open",
            ellipsize=Pango.EllipsizeMode.START,
            margin_start=8, margin_end=8,
            margin_top=4, margin_bottom=4,
            halign=Gtk.Align.START,
            css_classes=["caption", "dim-label"],
        )
        toolbar.add_top_bar(self._folder_label)

        # file tree
        scroll = Gtk.ScrolledWindow(vexpand=True,
                                    hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)

        self._tree_store = Gtk.TreeStore(str, str, bool)  # name, path, is_dir
        self._tree_view = Gtk.TreeView(
            model=self._tree_store,
            headers_visible=False,
            activate_on_single_click=False,
        )
        self._tree_view.add_css_class("navigation-sidebar")

        # column: icon + name
        col = Gtk.TreeViewColumn()
        r_icon = Gtk.CellRendererPixbuf()
        r_text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(r_icon, False)
        col.pack_start(r_text, True)
        col.add_attribute(r_text, "text", 0)
        col.set_cell_data_func(r_icon, self._icon_cell_data)
        self._tree_view.append_column(col)

        self._tree_view.connect("row-activated", self._on_row_activated)
        self._tree_view.connect("test-expand-row", self._on_row_expand)

        scroll.set_child(self._tree_view)
        toolbar.set_content(scroll)

        return page

    def _icon_cell_data(self, _col, cell, model, it, _data):
        is_dir = model.get_value(it, 2)
        cell.set_property(
            "icon-name",
            "folder-symbolic" if is_dir else "text-x-generic-symbolic"
        )

    # ── content (tabs) ────────────────────────────────────────────────────

    def _build_content_page(self) -> Adw.NavigationPage:
        self._content_nav_page = Adw.NavigationPage(title="Editor")

        toolbar = Adw.ToolbarView()
        self._content_nav_page.set_child(toolbar)

        # header bar
        hbar = Adw.HeaderBar()

        self._win_title = Adw.WindowTitle(title="Markdown Folder",
                                          subtitle="")
        hbar.set_title_widget(self._win_title)

        # Save button
        self._save_btn = Gtk.Button(
            icon_name="document-save-symbolic",
            tooltip_text="Save (Ctrl+S)",
            sensitive=False,
        )
        self._save_btn.connect("clicked", lambda _: self._save_current())
        hbar.pack_end(self._save_btn)

        # History button (git log for current file)
        self._history_btn = Gtk.Button(
            icon_name="document-open-recent-symbolic",
            tooltip_text="File history (git log)",
            sensitive=False,
            visible=False,
        )
        self._history_btn.connect("clicked", self._on_show_history)
        hbar.pack_end(self._history_btn)

        # Edit / Preview toggle group (libadwaita 1.7)
        self._toggle_group = Adw.ToggleGroup()
        self._toggle_group.add_css_class("flat")
        self._toggle_group.set_sensitive(False)

        t_edit = Adw.Toggle(label="Edit", name="edit")
        t_prev = Adw.Toggle(label="Preview", name="preview")
        self._toggle_group.add(t_edit)
        self._toggle_group.add(t_prev)
        self._toggle_group.set_active_name("preview")
        self._toggle_group.connect("notify::active-name", self._on_view_toggled)
        hbar.pack_end(self._toggle_group)

        toolbar.add_top_bar(hbar)

        # Tab bar (below header)
        self._tab_view = Adw.TabView(vexpand=True)
        self._tab_view.connect("notify::selected-page", self._on_tab_changed)
        self._tab_view.connect("close-page", self._on_tab_close)

        tab_bar = Adw.TabBar(view=self._tab_view, autohide=False)
        toolbar.add_top_bar(tab_bar)

        # Welcome status page (shown when no tabs)
        self._welcome = Adw.StatusPage(
            title="Markdown Folder",
            description="Open a folder from the sidebar to start browsing "
                        "and editing markdown files.",
            icon_name="text-editor-symbolic",
            vexpand=True,
        )

        self._content_stack = Gtk.Stack(vexpand=True)
        self._content_stack.add_named(self._welcome, "welcome")
        self._content_stack.add_named(self._tab_view, "tabs")
        self._content_stack.set_visible_child_name("welcome")

        toolbar.set_content(self._content_stack)

        return self._content_nav_page

    # ── actions / shortcuts ───────────────────────────────────────────────

    def _setup_actions(self):
        # Close current tab (Ctrl+W) — handled manually so it never closes the window
        a = Gio.SimpleAction.new("close-tab", None)
        a.connect("activate", lambda *_: self._close_current_tab())
        self.add_action(a)
        self.get_application().set_accels_for_action("win.close-tab", ["<primary>w"])

        # Switch to edit mode (Ctrl+E)
        a = Gio.SimpleAction.new("edit-mode", None)
        a.connect("activate", self._on_edit_mode)
        self.add_action(a)
        self.get_application().set_accels_for_action("win.edit-mode", ["<primary>e"])

        # Save
        a = Gio.SimpleAction.new("save", None)
        a.connect("activate", lambda *_: self._save_current())
        self.add_action(a)
        self.get_application().set_accels_for_action("win.save", ["<primary>s"])

        # Open folder
        a = Gio.SimpleAction.new("open-folder", None)
        a.connect("activate", lambda *_: self._on_open_folder(None))
        self.add_action(a)
        self.get_application().set_accels_for_action("win.open-folder",
                                                     ["<primary>o"])

        # New file (Ctrl+N)
        a = Gio.SimpleAction.new("new-file", None)
        a.connect("activate", lambda *_: self._on_new_file())
        self.add_action(a)
        self.get_application().set_accels_for_action("win.new-file", ["<primary>n"])

        # Delete selected file (Ctrl+D)
        a = Gio.SimpleAction.new("delete-file", None)
        a.connect("activate", lambda *_: self._on_delete_file())
        self.add_action(a)
        self.get_application().set_accels_for_action("win.delete-file", ["<primary>d"])

        # F6 — toggle focus between sidebar tree and editor
        a = Gio.SimpleAction.new("focus-toggle", None)
        a.connect("activate", self._on_focus_toggle)
        self.add_action(a)
        self.get_application().set_accels_for_action("win.focus-toggle", ["F6"])

        # Focus sidebar (Ctrl+0)
        a = Gio.SimpleAction.new("focus-sidebar", None)
        a.connect("activate", lambda *_: self._tree_view.grab_focus())
        self.add_action(a)
        self.get_application().set_accels_for_action("win.focus-sidebar",
                                                     ["<primary>0"])

    def _selected_tree_dir(self) -> Path | None:
        """Return the directory that is currently active in the tree.

        If a file row is selected → its parent directory.
        If a directory row is selected → that directory.
        Falls back to the root folder if nothing is selected.
        """
        if self._root_path is None:
            return None
        sel = self._tree_view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return self._root_path
        is_dir = model.get_value(it, 2)
        path = Path(model.get_value(it, 1))
        return path if is_dir else path.parent

    def _on_new_file(self):
        target_dir = self._selected_tree_dir()
        if target_dir is None:
            self._toast("Open a folder first", error=True)
            return

        entry = Adw.EntryRow(title="File name", text="new-file.md")
        listbox = Gtk.ListBox(
            css_classes=["boxed-list"],
            margin_top=8,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        listbox.append(entry)

        dialog = Adw.AlertDialog(
            heading="New file",
            body=str(target_dir),
        )
        dialog.set_extra_child(listbox)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response != "create":
                return
            name = entry.get_text().strip()
            if not name:
                return
            if not name.endswith(tuple(_MD_EXTS)):
                name += ".md"
            new_path = target_dir / name
            if new_path.exists():
                self._toast(f"{name} already exists", error=True)
                return
            try:
                new_path.touch()
            except OSError as e:
                self._toast(f"Could not create file: {e}", error=True)
                return
            # Refresh the tree so the new file appears
            if self._root_path:
                self._tree_store.clear()
                self._populate_tree(None, self._root_path)
            self.open_file(new_path)
            self._split_view.set_show_content(True)
            # Switch straight to edit mode for the new file
            GLib.idle_add(self._switch_new_file_to_edit)

        def _select_entry_text():
            # Select the filename without extension for easy overtyping
            txt = entry.get_text()
            dot = txt.rfind(".")
            entry.grab_focus()
            if dot > 0:
                entry.select_region(0, dot)
            return False

        dialog.connect("response", on_response)
        GLib.idle_add(_select_entry_text)
        dialog.present(self)

    def _switch_new_file_to_edit(self):
        page = self._tab_view.get_selected_page()
        if page is None:
            return False
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        ep.show_edit()
        self._toggle_group.handler_block_by_func(self._on_view_toggled)
        self._toggle_group.set_active_name("edit")
        self._toggle_group.handler_unblock_by_func(self._on_view_toggled)
        ep.text_view.grab_focus()
        return False

    def _on_delete_file(self):
        sel = self._tree_view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        is_dir = model.get_value(it, 2)
        if is_dir:
            self._toast("Cannot delete folders here", error=True)
            return
        path = Path(model.get_value(it, 1))

        dialog = Adw.AlertDialog(
            heading="Delete file?",
            body=str(path.name),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response != "delete":
                return
            # Close the tab if the file is open
            if path in self._open_tabs:
                page = self._open_tabs[path]
                self._close_tab(page)
            try:
                path.unlink()
            except OSError as e:
                self._toast(f"Could not delete: {e}", error=True)
                return
            # Refresh tree
            if self._root_path:
                self._tree_store.clear()
                self._populate_tree(None, self._root_path)
            self._toast(f"Deleted {path.name}")

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_focus_toggle(self, *_):
        """Alternate focus between sidebar tree and active editor."""
        page = self._tab_view.get_selected_page()
        if self._tree_view.has_focus():
            if page:
                ep: EditorPage = page._editor  # type: ignore[attr-defined]
                ep.text_view.grab_focus()
        else:
            self._tree_view.grab_focus()

    def _close_current_tab(self):
        """Close the current tab, or close the window if no tabs are open."""
        page = self._tab_view.get_selected_page()
        if page is None:
            self.close()
            return
        self._tab_view.close_page(page)

    def _on_edit_mode(self, *_):
        page = self._tab_view.get_selected_page()
        if page is None:
            return
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        if ep.current_view_name() == "edit":
            ep.show_preview()
            self._toggle_group.handler_block_by_func(self._on_view_toggled)
            self._toggle_group.set_active_name("preview")
            self._toggle_group.handler_unblock_by_func(self._on_view_toggled)
            ep.preview_view.grab_focus()
        else:
            ep.show_edit()
            self._toggle_group.handler_block_by_func(self._on_view_toggled)
            self._toggle_group.set_active_name("edit")
            self._toggle_group.handler_unblock_by_func(self._on_view_toggled)
            ep.text_view.grab_focus()

    # ── folder loading ────────────────────────────────────────────────────

    def _on_open_folder(self, _btn):
        d = Gtk.FileDialog(title="Open Folder")
        d.select_folder(self, None, self._folder_selected_cb)

    def _folder_selected_cb(self, dialog, result):
        try:
            f = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if f:
            self.load_folder(Path(f.get_path()))

    def load_folder(self, path: Path):
        self._root_path = path
        self._is_git = _is_git_repo(path)
        self._folder_label.set_label(str(path))
        self._win_title.set_subtitle(path.name)
        self.set_title(f"Markdown Folder — {path.name}")
        self._tree_store.clear()
        self._populate_tree(None, path)
        # persist last folder
        cfg = _load_config()
        cfg["last_folder"] = str(path)
        _save_config(cfg)

    def _restore_last_folder(self):
        cfg = _load_config()
        last = cfg.get("last_folder")
        if last:
            p = Path(last)
            if p.is_dir():
                GLib.idle_add(lambda: self.load_folder(p) or False)

    def _populate_tree(self, parent_it, directory: Path, depth: int = 0):
        if depth > 12:
            return
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue
            is_dir = entry.is_dir()
            if is_dir or entry.suffix.lower() in _MD_EXTS:
                row = self._tree_store.append(
                    parent_it, [entry.name, str(entry), is_dir]
                )
                if is_dir:
                    # placeholder child so expander arrow appears
                    self._tree_store.append(row, ["", "", False])

    def _on_row_expand(self, _tv, it, _path):
        """Lazy-load directory children on first expand."""
        child = self._tree_store.iter_children(it)
        while child:
            self._tree_store.remove(child)
            child = self._tree_store.iter_children(it)
        dir_path = Path(self._tree_store.get_value(it, 1))
        self._populate_tree(it, dir_path)
        return False  # allow expansion

    def _on_row_activated(self, _tv, tree_path, _col):
        it = self._tree_store.get_iter(tree_path)
        if not it:
            return
        is_dir = self._tree_store.get_value(it, 2)
        if is_dir:
            # Enter / double-click toggles expand/collapse
            if self._tree_view.row_expanded(tree_path):
                self._tree_view.collapse_row(tree_path)
            else:
                self._tree_view.expand_row(tree_path, False)
            return
        file_path = Path(self._tree_store.get_value(it, 1))
        if file_path.exists():
            self.open_file(file_path)
            self._split_view.set_show_content(True)

    # ── tab management ────────────────────────────────────────────────────

    def open_file(self, path: Path):
        # If already open, just switch to that tab
        if path in self._open_tabs:
            self._tab_view.set_selected_page(self._open_tabs[path])
            return

        ep = EditorPage(path)
        if not ep.load():
            self._toast("Could not read file", error=True)
            return

        ep._on_save_cb.append(self._on_editor_saved)

        self._content_stack.set_visible_child_name("tabs")

        # Block tab-changed signal while setting up the page so that
        # _on_tab_changed doesn't fire before page._editor is assigned
        # (append() auto-selects when it's the first tab).
        self._tab_view.handler_block_by_func(self._on_tab_changed)
        page = self._tab_view.append(ep.root)
        page.set_title(path.name)
        page.set_icon(Gio.ThemedIcon.new("text-x-generic-symbolic"))
        page.set_tooltip(str(path))
        page._editor = ep  # type: ignore[attr-defined]
        self._open_tabs[path] = page
        self._tab_view.handler_unblock_by_func(self._on_tab_changed)

        self._tab_view.set_selected_page(page)
        # Force _on_tab_changed: if append() auto-selected the page (first tab),
        # set_selected_page is a no-op and the signal never fires.
        self._on_tab_changed(self._tab_view, None)

        # always open in preview mode; focus preview widget
        ep.show_preview()
        self._toggle_group.set_active_name("preview")
        ep.preview_view.grab_focus()

    def _on_tab_changed(self, tab_view, _param):
        page = tab_view.get_selected_page()
        if page is None:
            self._win_title.set_title("Markdown Folder")
            self._win_title.set_subtitle(
                self._root_path.name if self._root_path else ""
            )
            self._save_btn.set_sensitive(False)
            self._toggle_group.set_sensitive(False)
            self._history_btn.set_visible(False)
            return

        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        self._win_title.set_title(ep.path.name)
        if self._root_path:
            try:
                rel = ep.path.relative_to(self._root_path)
                self._win_title.set_subtitle(str(rel.parent)
                                             if str(rel.parent) != "."
                                             else "")
            except ValueError:
                self._win_title.set_subtitle("")

        self._save_btn.set_sensitive(ep.get_modified())
        self._toggle_group.set_sensitive(True)
        self._history_btn.set_visible(self._is_git)
        self._history_btn.set_sensitive(self._is_git)
        # sync toggle to current view of this tab (no signal loop)
        self._toggle_group.handler_block_by_func(self._on_view_toggled)
        self._toggle_group.set_active_name(ep.current_view_name())
        self._toggle_group.handler_unblock_by_func(self._on_view_toggled)

    def _on_tab_close(self, _tv, page) -> bool:
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        if ep.get_modified():
            self._ask_save_close(ep, page)
            return True  # we handle closing ourselves
        self._close_tab(page)
        return True

    def _close_tab(self, page: Adw.TabPage):
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        self._open_tabs.pop(ep.path, None)
        self._tab_view.close_page_finish(page, True)
        if self._tab_view.get_n_pages() == 0:
            self._content_stack.set_visible_child_name("welcome")
            self._win_title.set_title("Markdown Folder")
            self._win_title.set_subtitle(
                self._root_path.name if self._root_path else ""
            )
            self._save_btn.set_sensitive(False)
            self._toggle_group.set_sensitive(False)
            self._history_btn.set_sensitive(False)

    def _ask_save_close(self, ep: EditorPage, page: Adw.TabPage):
        dialog = Adw.AlertDialog(
            heading="Save changes?",
            body=f'"{ep.path.name}" has unsaved changes.',
        )
        dialog.add_response("discard", "Discard")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response == "cancel":
                self._tab_view.close_page_finish(page, False)
            elif response == "save":
                ep.save()
                self._close_tab(page)
            else:
                self._close_tab(page)

        dialog.connect("response", on_response)
        dialog.present(self)

    # ── save ──────────────────────────────────────────────────────────────

    def _save_current(self):
        page = self._tab_view.get_selected_page()
        if page is None:
            return
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        if not ep.save():
            self._toast(f"Could not save {ep.path.name}", error=True)
            return
        self._toast(f"Saved {ep.path.name}")
        if self._is_git and self._root_path:
            try:
                rel = ep.path.relative_to(self._root_path)
            except ValueError:
                return
            self._do_git_commit(rel, f"Update {ep.path.name}")

    def _ask_git_commit(self, ep: EditorPage, rel: Path):
        default_msg = f"Update {ep.path.name}"

        entry = Adw.EntryRow(title="Commit message", text=default_msg)
        listbox = Gtk.ListBox(
            css_classes=["boxed-list"],
            margin_top=8,
            selection_mode=Gtk.SelectionMode.NONE,
        )
        listbox.append(entry)

        dialog = Adw.AlertDialog(
            heading="Commit to git?",
            body=str(rel),
        )
        dialog.set_extra_child(listbox)
        dialog.add_response("skip", "Skip")
        dialog.add_response("commit", "Commit")
        dialog.set_response_appearance("commit", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("commit")
        dialog.set_close_response("skip")

        def on_response(_d, response):
            if response != "commit":
                return
            msg = entry.get_text().strip() or default_msg
            self._do_git_commit(rel, msg)

        dialog.connect("response", on_response)
        GLib.idle_add(lambda: entry.grab_focus() or False)
        dialog.present(self)

    def _do_git_commit(self, rel_path: Path, message: str):
        def worker():
            _, err_add, rc_add = _run_git(self._root_path, "add", str(rel_path))
            if rc_add != 0:
                GLib.idle_add(
                    lambda: self._toast(f"git add failed: {err_add.strip()}", error=True) or False
                )
                return
            _, err_cm, rc_cm = _run_git(self._root_path, "commit", "-m", message)
            if rc_cm != 0:
                GLib.idle_add(
                    lambda: self._toast(f"git commit failed: {err_cm.strip()}", error=True) or False
                )
            else:
                GLib.idle_add(
                    lambda: self._toast(f"Committed: {message[:50]}") or False
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_editor_saved(self, ep: EditorPage):
        self._save_btn.set_sensitive(False)
        # update tab title (remove dot indicator if we add one later)
        if ep.path in self._open_tabs:
            self._open_tabs[ep.path].set_title(ep.path.name)

    # ── toggle edit / preview ─────────────────────────────────────────────

    def _on_view_toggled(self, tg, _param):
        page = self._tab_view.get_selected_page()
        if page is None:
            return
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        name = tg.get_active_name()
        if name == "preview":
            ep.show_preview()
        else:
            ep.show_edit()

    # ── git ───────────────────────────────────────────────────────────────

    def _on_show_git(self, _btn):
        if not self._root_path or not self._is_git:
            return
        from .git_dialog import GitDialog
        d = GitDialog(root=self._root_path)
        d.present(self)

    def _on_show_history(self, _btn):
        page = self._tab_view.get_selected_page()
        if page is None or not self._root_path or not self._is_git:
            return
        ep: EditorPage = page._editor  # type: ignore[attr-defined]
        from .history_dialog import HistoryDialog
        d = HistoryDialog(file_path=ep.path, root=self._root_path)
        d.present(self)

    # ── toast helpers ─────────────────────────────────────────────────────

    def _toast(self, title: str, error: bool = False):
        t = Adw.Toast(title=title, timeout=3 if not error else 0)
        if error:
            t.set_button_label("OK")
        self._toast_overlay.add_toast(t)
