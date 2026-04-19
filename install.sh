#!/usr/bin/env bash
# install.sh — installs Markdown Folder into the current user's GNOME session.
# No root required; everything goes under ~/.local.

set -euo pipefail

APP_ID="io.github.rafaelsieber.markdownfolder"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── directories ──────────────────────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
VENV_DIR="$SCRIPT_DIR/.venv"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

echo "==> Checking system dependencies…"
python3 -c "import gi; gi.require_version('Adw','1'); from gi.repository import Adw" 2>/dev/null || {
    echo ""
    echo "  ERROR: libadwaita Python bindings not found."
    echo "  Install with one of:"
    echo "    Fedora:  sudo dnf install python3-gobject gtk4 libadwaita gtksourceview5"
    echo "    Ubuntu:  sudo apt install python3-gi gir1.2-adw-1 gir1.2-gtksource-5"
    echo "    Arch:    sudo pacman -S python-gobject gtk4 libadwaita gtksourceview5"
    echo ""
    exit 1
}

echo "==> Creating virtual environment at $VENV_DIR…"
python3 -m venv --system-site-packages "$VENV_DIR"
# system-site-packages lets venv see PyGObject / GTK4 installed system-wide

echo "==> Installing launcher script to $BIN_DIR/markdown-folder…"
cat > "$BIN_DIR/markdown-folder" <<LAUNCHER
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python3" "$SCRIPT_DIR/main.py" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/markdown-folder"

echo "==> Installing icon…"
cp "$SCRIPT_DIR/data/icons/${APP_ID}.svg" "$ICON_DIR/${APP_ID}.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "==> Installing .desktop entry…"
cat > "$APP_DIR/${APP_ID}.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Markdown Folder
GenericName=Markdown Editor
Comment=Browse, read and edit Markdown files in a folder tree with Git support
Exec=$BIN_DIR/markdown-folder %u
Icon=${APP_ID}
Terminal=false
Categories=Office;TextEditor;GNOME;GTK;
MimeType=text/markdown;text/x-markdown;inode/directory;
Keywords=markdown;editor;git;notes;
StartupNotify=true
StartupWMClass=io.github.rafaelsieber.markdownfolder
DESKTOP

update-desktop-database "$APP_DIR" 2>/dev/null || true

echo ""
echo "✓ Markdown Folder installed."
echo "  Launch via: markdown-folder"
echo "  Or search 'Markdown Folder' in your GNOME app grid."
echo ""
echo "  If '~/.local/bin' is not in your PATH, add this to ~/.bashrc:"
echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
