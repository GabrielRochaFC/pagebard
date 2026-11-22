"""Where user data (voices, OCR data) lives, following the XDG spec."""

import os
from pathlib import Path

APP_DIR_NAME = "leitorpdf"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    path = root / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def voices_dir() -> Path:
    path = data_dir() / "voices"
    path.mkdir(parents=True, exist_ok=True)
    return path
