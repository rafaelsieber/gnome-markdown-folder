"""
File history dialog — git log for a single file.

Layout:
  AdwDialog
  └── AdwToolbarView
      ├── top: AdwHeaderBar
      └── content: AdwNavigationSplitView
            ├── sidebar: commit list  (AdwNavigationPage)
            │     └── Gtk.ListBox with one ActionRow per commit
            └── content: commit detail (AdwNavigationPage)
                  ├── AdwBanner  — shows commit metadata
                  └── diff text view with syntax colouring
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
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


@dataclass
class Commit:
    hash_full: str
    hash_short: str
    subject: str
    author: str
    date: str
    body: str = ""


def _parse_log(raw: str) -> list[Commit]:
    """Parse output of git log --format='%H|%h|%s|%an|%ad|%b' --date=short"""
    commits = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 5)
        if len(parts) < 5:
            continue
        commits.append(Commit(
            hash_full=parts[0],
            hash_short=parts[1],
            subject=parts[2],
            author=parts[3],
            date=parts[4],
            body=parts[5] if len(parts) > 5 else "",
        ))
    return commits


class HistoryDialog(Adw.Dialog):
    def __init__(self, file_path: Path, root: Path):
        super().__init__(
            title=f"History — {file_path.name}",
            content_width=960,
            content_height=680,
        )
        self._file = file_path
        self._root = root
        self._commits: list[Commit] = []
        self._rows: list[Gtk.ListBoxRow] = []

        self._build_ui()
        self._load_async()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        hbar = Adw.HeaderBar()
        toolbar.add_top_bar(hbar)

        # Spinner overlay while loading
        self._stack = Gtk.Stack(vexpand=True)

        # Loading page
        spinner_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
            spacing=12,
        )
        spinner = Adw.Spinner()
        spinner.set_size_request(48, 48)
        spinner_box.append(spinner)
        spinner_box.append(Gtk.Label(label="Loading history…",
                                     css_classes=["dim-label"]))
        self._stack.add_named(spinner_box, "loading")

        # Main split view
        self._split = Adw.NavigationSplitView(
            min_sidebar_width=240,
            max_sidebar_width=340,
            sidebar_width_fraction=0.30,
        )
        self._split.set_sidebar(self._build_list_page())
        self._split.set_content(self._build_detail_page())
        self._stack.add_named(self._split, "content")
        self._stack.set_visible_child_name("loading")

        toolbar.set_content(self._stack)

        # Breakpoint: collapse on narrow
        bp = Adw.Breakpoint()
        bp.set_condition(Adw.BreakpointCondition.parse("max-width: 600sp"))
        bp.add_setter(self._split, "collapsed", True)
        self.add_breakpoint(bp)

    def _build_list_page(self) -> Adw.NavigationPage:
        page = Adw.NavigationPage(title="Commits")

        toolbar = Adw.ToolbarView()
        page.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())

        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._listbox = Gtk.ListBox(
            css_classes=["navigation-sidebar"],
            selection_mode=Gtk.SelectionMode.SINGLE,
        )
        self._listbox.set_placeholder(
            Adw.StatusPage(
                title="No history",
                description="This file has no commits yet.",
                icon_name="document-open-recent-symbolic",
            )
        )
        self._listbox.connect("row-activated", self._on_row_activated)
        scroll.set_child(self._listbox)
        toolbar.set_content(scroll)

        return page

    def _build_detail_page(self) -> Adw.NavigationPage:
        self._detail_page = Adw.NavigationPage(title="Diff")

        toolbar = Adw.ToolbarView()
        self._detail_page.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())

        # Metadata banner
        self._meta_banner = Adw.Banner(
            title="",
            revealed=False,
        )
        toolbar.add_top_bar(self._meta_banner)

        # Welcome / empty state
        self._detail_stack = Gtk.Stack(vexpand=True)

        welcome = Adw.StatusPage(
            title="Select a commit",
            description="Choose a commit from the list to see its diff.",
            icon_name="document-open-recent-symbolic",
        )
        self._detail_stack.add_named(welcome, "welcome")

        # Diff view
        scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        self._diff_view = Gtk.TextView(
            editable=False,
            monospace=True,
            left_margin=12,
            right_margin=12,
            top_margin=8,
            bottom_margin=8,
        )
        self._diff_view.set_wrap_mode(Gtk.WrapMode.NONE)
        scroll.set_child(self._diff_view)
        self._detail_stack.add_named(scroll, "diff")
        self._detail_stack.set_visible_child_name("welcome")

        toolbar.set_content(self._detail_stack)
        return self._detail_page

    # ── async loading ─────────────────────────────────────────────────────

    def _load_async(self):
        def worker():
            out, _, rc = _run_git(
                self._root,
                "log",
                "--follow",
                "--format=%H|%h|%s|%an|%ad|%b",
                "--date=short",
                "--",
                str(self._file),
            )
            commits = _parse_log(out) if rc == 0 else []
            GLib.idle_add(self._populate_list, commits)

        threading.Thread(target=worker, daemon=True).start()

    def _populate_list(self, commits: list[Commit]):
        self._commits = commits

        for c in commits:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(c.subject),
                subtitle=f"{c.date}  ·  {c.author}  ·  <tt>{c.hash_short}</tt>",
                subtitle_selectable=False,
                use_markup=True,
                activatable=True,
            )
            row._commit = c  # type: ignore[attr-defined]
            self._listbox.append(row)
            self._rows.append(row)

        self._stack.set_visible_child_name("content")

        # auto-select first
        if self._rows:
            self._listbox.select_row(self._rows[0])
            self._load_diff(self._rows[0]._commit)  # type: ignore[attr-defined]

        return False

    # ── diff loading ──────────────────────────────────────────────────────

    def _on_row_activated(self, _lb, row):
        c: Commit = row._commit  # type: ignore[attr-defined]
        self._split.set_show_content(True)
        self._load_diff(c)

    def _load_diff(self, c: Commit):
        self._meta_banner.set_title(
            f"{c.hash_short}  ·  {c.date}  ·  {c.author}"
        )
        self._meta_banner.set_revealed(True)
        self._detail_page.set_title(c.subject[:60])
        self._diff_view.get_buffer().set_text("Loading…")
        self._detail_stack.set_visible_child_name("diff")

        def worker():
            diff, _, _ = _run_git(
                self._root,
                "show",
                c.hash_full,
                "--",
                str(self._file),
            )
            GLib.idle_add(lambda: _apply_diff(self._diff_view, diff or "(empty)") or False)

        threading.Thread(target=worker, daemon=True).start()


# ── diff colouring ────────────────────────────────────────────────────────────

def _apply_diff(tv: Gtk.TextView, text: str):
    buf = tv.get_buffer()
    buf.set_text("")
    tt = buf.get_tag_table()

    def tag(name: str, **kw):
        t = tt.lookup(name)
        if t is None:
            t = buf.create_tag(name, **kw)

    tag("added",   foreground="#57c35f")
    tag("removed", foreground="#f44747")
    tag("hunk",    foreground="#569cd6")
    tag("header",  foreground="#ce9178", weight=Pango.Weight.BOLD)
    tag("meta",    foreground="#888888", style=Pango.Style.ITALIC)
    tag("commit",  foreground="#e5c07b", weight=Pango.Weight.BOLD)

    for line in text.split("\n"):
        e = buf.get_end_iter()
        if line.startswith("commit "):
            buf.insert_with_tags_by_name(e, line + "\n", "commit")
        elif line.startswith("Author:") or line.startswith("Date:"):
            buf.insert_with_tags_by_name(e, line + "\n", "meta")
        elif line.startswith("+++") or line.startswith("---"):
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
