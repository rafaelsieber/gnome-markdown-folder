# Markdown Folder

A modern GNOME application for browsing, reading and editing Markdown files in a folder tree — with Git integration.

Built with **Python**, **GTK4** and **libadwaita 1.10**.

![screenshot placeholder](data/screenshot.png)

## Features

- **Folder tree** — browse folders and subfolders; lazy-loads for performance
- **Multi-tab editor** — open multiple files at once with `AdwTabView`
- **Edit / Preview** — toggle between raw Markdown and a rendered preview via `AdwToggleGroup`
- **Git integration** — when the folder is a git repo, view Status, Diff, Staged changes, Log and Stash via an `AdwDialog`
- **Unsaved-changes banner** — per-tab `AdwBanner` with one-click save
- **Toast notifications** — `AdwToastOverlay` for save/error feedback
- **Responsive layout** — `AdwNavigationSplitView` + `AdwBreakpoint` collapses sidebar on narrow windows
- **Syntax highlighting** — uses GtkSourceView 5 when available
- **GNOME-native** — `AdwAboutDialog`, keyboard shortcuts, dark/light theme follows system

## Requirements

| Package | Distro install |
|---|---|
| Python ≥ 3.11 | (usually pre-installed) |
| PyGObject | `python3-gobject` / `python3-gi` |
| GTK4 | `gtk4` |
| libadwaita ≥ 1.7 | `libadwaita` / `gir1.2-adw-1` |
| GtkSourceView 5 *(optional)* | `gtksourceview5` / `gir1.2-gtksource-5` |

### Fedora / RHEL
```bash
sudo dnf install python3-gobject gtk4 libadwaita gtksourceview5
```

### Debian / Ubuntu
```bash
sudo apt install python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtksource-5
```

### Arch Linux
```bash
sudo pacman -S python-gobject gtk4 libadwaita gtksourceview5
```

## Install

```bash
git clone https://github.com/rafaelsieber/gnome-markdown-folder.git
cd gnome-markdown-folder
./install.sh
```

This installs a launcher to `~/.local/bin/markdown-folder` and a `.desktop` entry so the app appears in your GNOME app grid.

## Uninstall

```bash
./remove.sh
```

## Run from source

```bash
python3 main.py [path/to/folder]
```

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open folder |
| `Ctrl+S` | Save current file |
| `Ctrl+N` | New window |
| `Ctrl+Q` | Quit |

## Architecture

```
main.py                  entry point
src/
  application.py         Adw.Application, global actions, About dialog
  window.py              AdwApplicationWindow
                           AdwNavigationSplitView (sidebar + tabs)
                           AdwBreakpoint (responsive)
                           AdwToastOverlay
                           AdwTabView + AdwTabBar
                           AdwToggleGroup (Edit/Preview)
                           AdwBanner (unsaved changes, per tab)
  git_dialog.py          AdwDialog with AdwTabView
                           Status / Diff / Staged / Log / Stash tabs
                           AdwSpinner while loading (async thread)
data/
  icons/                 SVG app icon
```

## License

GPL-3.0-or-later
