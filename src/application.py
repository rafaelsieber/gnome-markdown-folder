"""Application bootstrap."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

import sys
from pathlib import Path

APP_ID = "io.github.rafaelsieber.markdownfolder"


class MarkdownFolderApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.connect("activate", self._on_activate)
        self.connect("open", self._on_open)
        self._setup_actions()

    def _setup_actions(self):
        # Quit
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", lambda *_: self.quit())
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        # About
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self._on_about)
        self.add_action(action)

        # New window
        action = Gio.SimpleAction.new("new-window", None)
        action.connect("activate", self._on_new_window)
        self.add_action(action)
        self.set_accels_for_action("app.new-window", ["<primary>n"])

    def _on_activate(self, _app):
        self._create_window()

    def _on_open(self, _app, files, _n_files, _hint):
        win = self._create_window()
        if files:
            path = Path(files[0].get_path())
            if path.is_dir():
                win.load_folder(path)
            elif path.is_file():
                win.load_folder(path.parent)
                win.open_file(path)

    def _on_new_window(self, *_):
        self._create_window()

    def _create_window(self):
        from .window import MarkdownWindow
        win = MarkdownWindow(application=self)
        win.present()
        return win

    def _on_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name="Markdown Folder",
            application_icon="text-editor-symbolic",
            developer_name="Rafael Sieber",
            version="1.0.0",
            website="https://github.com/rafaelsieber/gnome-markdown-folder",
            issue_url="https://github.com/rafaelsieber/gnome-markdown-folder/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="Browse, read and edit Markdown files in a folder tree.\n"
                     "Shows git changes when the folder is a git repository.",
        )
        dialog.present(self.get_active_window())
