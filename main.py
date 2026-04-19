#!/usr/bin/env python3
"""Markdown Folder — entry point."""

import sys
import os

# Allow running directly from source tree
sys.path.insert(0, os.path.dirname(__file__))

from src.application import MarkdownFolderApp

if __name__ == "__main__":
    app = MarkdownFolderApp()
    sys.exit(app.run(sys.argv))
