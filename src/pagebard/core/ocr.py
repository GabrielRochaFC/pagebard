"""Recognize the text of scanned pages (OCR) with the engine built into PyMuPDF."""

import json
import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pagebard.core.i18n import _, language
from pagebard.core.download import DownloadCancelled, discard, fetch_to_temp, open_url
from pagebard.core.errors import PagebardError
from pagebard.core.worker_client import WorkerProcess

TESSDATA_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"
MSG_OCR_DATA = (
    _(
        "The text recognition data could not be downloaded. Check your internet "
        "connection and try again."
    )
)
MSG_OCR = _("The text of this PDF could not be recognized.")

_DPI = 300
# Used when the voice language has no recognition data of its own.
_DEFAULT_LANGUAGE = {"pt_BR": "por", "es": "spa"}.get(language(), "eng")
_LANGUAGES = {"pt": "por", "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita"}

ProgressCallback = Callable[[int, int], None]


class OcrError(PagebardError):
    pass


class OcrCancelled(Exception):
    pass


def language_for(voice_language: str) -> str:
    """Recognition language that goes with a voice, e.g. "pt_BR" -> "por"."""
    return _LANGUAGES.get(voice_language.split("_")[0], _DEFAULT_LANGUAGE)


def has_language(language: str, tessdata: Path) -> bool:
    data = tessdata / f"{language}.traineddata"
    return data.is_file() and data.stat().st_size > 0


def download_language(
    language: str,
    tessdata: Path,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    opener: Callable[[str], Any] | None = None,
    base_url: str = TESSDATA_BASE,
) -> None:
    """Fetch the recognition data of a language. Leaves nothing on failure."""
    if has_language(language, tessdata):
        return
    tessdata.mkdir(parents=True, exist_ok=True)
    temps: list[Path] = []
    try:
        part = fetch_to_temp(
            f"{base_url}/{language}.traineddata",
            tessdata,
            progress,
            cancel,
            opener or open_url,
            temps,
        )
        os.replace(part, tessdata / f"{language}.traineddata")
    except DownloadCancelled:
        discard(temps)
        raise OcrCancelled() from None
    except Exception as exc:
        discard(temps)
        raise OcrError(MSG_OCR_DATA) from exc


def recognize(
    path: Path,
    pages: Sequence[int],
    language: str,
    tessdata: Path,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> dict[int, list]:
    """Words found on each of the given pages (0-based).

    Runs in a child process, so the program stays responsive. Each word is
    [x0, y0, x1, y1, text, block, line, number], in displayed-page coordinates.
    """
    worker = WorkerProcess()
    try:
        _ask(worker, {"op": "open", "path": str(path)})
        recognized: dict[int, list] = {}
        for index, page in enumerate(pages):
            if cancel is not None and cancel.is_set():
                raise OcrCancelled()
            request = {
                "op": "ocr",
                "page": page,
                "language": language,
                "tessdata": str(tessdata),
                "dpi": _DPI,
            }
            recognized[page] = json.loads(_ask(worker, request))
            if progress is not None:
                progress(index + 1, len(pages))
        return recognized
    except ValueError as exc:
        raise OcrError(MSG_OCR) from exc
    finally:
        worker.stop()


def _ask(worker: WorkerProcess, request: dict) -> bytes:
    reply = worker.exchange(request)
    if reply is None or not reply[0].get("ok"):
        raise OcrError(MSG_OCR)
    return reply[1]
