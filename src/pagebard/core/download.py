"""Fetch files from the internet without ever leaving half a file behind."""

import os
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

_CHUNK = 64 * 1024
_TIMEOUT_SECONDS = 30
_USER_AGENT = "Pagebard/0.1"

ProgressCallback = Callable[[int, int], None]


class DownloadCancelled(Exception):
    pass


def open_url(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    return urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS)


def fetch_to_temp(
    url: str,
    folder: Path,
    progress: ProgressCallback | None,
    cancel: threading.Event | None,
    opener: Callable[[str], Any],
    temps: list[Path],
) -> Path:
    """Download url into a new temporary file in folder and return its path.

    The path is added to `temps` before anything is written, so the caller can
    always clean up. Raises DownloadCancelled, or OSError when the transfer
    fails or ends early.
    """
    handle, name = tempfile.mkstemp(dir=folder, suffix=".part")
    part = Path(name)
    temps.append(part)
    done = 0
    reported = None
    with os.fdopen(handle, "wb") as out, opener(url) as response:
        total = _content_length(response)
        while True:
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled()
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress is not None:
                reported = (done, total)
                progress(done, total)
    if done < total:
        raise OSError(f"download ended early: {done} of {total} bytes")
    if progress is not None and reported != (done, done):
        progress(done, done)
    return part


def discard(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _content_length(response: Any) -> int:
    try:
        return max(int(response.headers.get("Content-Length") or 0), 0)
    except (TypeError, ValueError):
        return 0
