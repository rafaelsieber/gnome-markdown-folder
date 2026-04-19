#!/usr/bin/env bash
# remove.sh — uninstalls Markdown Folder from the current user's GNOME session.

set -euo pipefail

APP_ID="io.github.rafaelsieber.markdownfolder"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "==> Removing launcher…"
rm -f "$BIN_DIR/markdown-folder"

echo "==> Removing .desktop entry…"
rm -f "$APP_DIR/${APP_ID}.desktop"
update-desktop-database "$APP_DIR" 2>/dev/null || true

echo "==> Removing icon…"
rm -f "$ICON_DIR/${APP_ID}.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "==> Removing virtual environment…"
rm -rf "$VENV_DIR"

echo ""
echo "✓ Markdown Folder removed."
