"""
Git changes dialog — uses:
  • AdwDialog          (1.5) adaptive modal
  • AdwToolbarView     (1.4) proper toolbar regions
  • AdwTabView         — status / diff / log tabs
  • AdwTabBar          — tab switcher
  • AdwSpinner         (1.6) while loading
  • AdwBanner          (1.3) for error messages
"""

from __future__ import annotations

import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango


def _run_git(cwd: Path, *args: str) -> tuple[str, str, int]:
    import subprocess
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=20
        )
        return r.stdout, r.stderr, r.returncode
    except Exception as e:
        return "", str(e), -1


class GitDialog(Adw.Dialog):
    def __init__(self, root: Path):
        super().__init__(
            title="Git Changes",
            content_width=860,
            content_height=640,
        )
        self._root = root
        self._build_ui()
        self._load_async()

    def _build_ui(self):
        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        # header bar
        hbar = Adw.HeaderBar()
        toolbar.add_top_bar(hbar)

        # error banner
        self._error_banner = Adw.Banner(
            title="Git error",
            button_label="Dismiss",
            revealed=False,
        )
        self._error_banner.connect("button-clicked",
                                   lambda _: self._error_banner.set_revealed(False))
        toolbar.add_top_bar(self._error_banner)

        # Tab view
        self._tab_view = Adw.TabView(vexpand=True)
        tab_bar = Adw.TabBar(view=self._tab_view)
        toolbar.add_top_bar(tab_bar)

        # Content stack: spinner while loading, then tabs
        self._stack = Gtk.Stack(vexpand=True)

        spinner_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
            spacing=12,
        )
        spinner = Adw.Spinner()
        spinner.set_size_request(48, 48)
        lbl = Gtk.Label(label="Loading git data…", css_classes=["dim-label"])
        spinner_box.append(spinner)
        spinner_box.append(lbl)
        self._stack.add_named(spinner_box, "loading")
        self._stack.add_named(self._tab_view, "content")
        self._stack.set_visible_child_name("loading")

        toolbar.set_content(self._stack)

        # Create tab pages (text views, populated after load)
        self._tv_status = self._make_tab("Status", "dialog-information-symbolic")
        self._tv_diff   = self._make_tab("Diff",   "vcs-locally-modified-symbolic")
        self._tv_staged = self._make_tab("Staged", "vcs-added-symbolic")
        self._tv_log    = self._make_tab("Log",    "media-playback-start-symbolic")
        self._tv_stash  = self._make_tab("Stash",  "document-save-symbolic")

    def _make_tab(self, title: str, icon: str) -> Gtk.TextView:
        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        tv = Gtk.TextView(
            editable=False,
            monospace=True,
            left_margin=12,
            right_margin=12,
            top_margin=8,
            bottom_margin=8,
        )
        tv.set_wrap_mode(Gtk.WrapMode.NONE)
        scroll.set_child(tv)

        page = self._tab_view.append(scroll)
        page.set_title(title)
        page.set_icon(Gio.ThemedIcon.new(icon)
                      if False else _gio_icon(icon))
        return tv

    # ── async data loading ────────────────────────────────────────────────

    def _load_async(self):
        def worker():
            root = self._root

            status, _, _ = _run_git(root, "status")
            diff,   _, _ = _run_git(root, "diff")
            staged, _, _ = _run_git(root, "diff", "--cached")
            log,    _, _ = _run_git(
                root, "log", "--oneline", "--graph",
                "--decorate", "--color=never", "-80"
            )
            stash,  _, _ = _run_git(root, "stash", "list")

            GLib.idle_add(self._populate,
                          status, diff, staged, log, stash)

        threading.Thread(target=worker, daemon=True).start()

    def _populate(self, status: str, diff: str,
                  staged: str, log: str, stash: str):
        self._tv_status.get_buffer().set_text(status or "(no output)")
        _apply_diff(self._tv_diff,   diff   or "(no unstaged changes)")
        _apply_diff(self._tv_staged, staged or "(no staged changes)")
        self._tv_log.get_buffer().set_text(log   or "(no commits)")
        self._tv_stash.get_buffer().set_text(stash or "(no stashes)")
        self._stack.set_visible_child_name("content")
        return False  # don't repeat idle call


def _gio_icon(name: str):
    from gi.repository import Gio
    return Gio.ThemedIcon.new(name)


# ── diff colouring ────────────────────────────────────────────────────────────

def _apply_diff(tv: Gtk.TextView, text: str):
    buf = tv.get_buffer()
    buf.set_text("")
    tt = buf.get_tag_table()

    def tag(name: str, **kw):
        t = tt.lookup(name)
        if t is None:
            t = buf.create_tag(name, **kw)
        return t

    tag("added",    foreground="#57c35f")
    tag("removed",  foreground="#f44747")
    tag("hunk",     foreground="#569cd6")
    tag("header",   foreground="#ce9178", weight=Pango.Weight.BOLD)
    tag("meta",     foreground="#888888", style=Pango.Style.ITALIC)

    for line in text.split("\n"):
        e = buf.get_end_iter()
        if line.startswith("+++") or line.startswith("---"):
            buf.insert_with_tags_by_name(e, line + "\n", "header")
        elif line.startswith("+"):
            buf.insert_with_tags_by_name(e, line + "\n", "added")
        elif line.startswith("-"):
            buf.insert_with_tags_by_name(e, line + "\n", "removed")
        elif line.startswith("@@"):
            buf.insert_with_tags_by_name(e, line + "\n", "hunk")
        elif line.startswith("diff ") or line.startswith("index ") \
                or line.startswith("new file") or line.startswith("deleted"):
            buf.insert_with_tags_by_name(e, line + "\n", "meta")
        else:
            buf.insert(e, line + "\n")
