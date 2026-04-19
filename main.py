#!/usr/bin/env python3
"""Markdown Folder — entry point."""

import sys
import os

VERSION = "1.1.0"

# Allow running directly from source tree
sys.path.insert(0, os.path.dirname(__file__))

if "--version" in sys.argv or "-v" in sys.argv:
    print(f"markdown-folder {VERSION}")
    sys.exit(0)

from src.application import MarkdownFolderApp

if __name__ == "__main__":
    app = MarkdownFolderApp()
    sys.exit(app.run(sys.argv))
