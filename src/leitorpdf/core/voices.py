"""Piper voices: which ones are installed and how to download one."""

import os
import re
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from leitorpdf.core.errors import LeitorError

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DEFAULT_VOICE_KEY = "pt_BR-faber-medium"
MSG_DOWNLOAD = (
    "Não foi possível baixar a voz. Verifique sua conexão com a internet e "
    "tente novamente."
)

_KEY = re.compile(r"^([a-z]{2,3}_[A-Z]{2})-([^-]+)-([a-z_]+)$")
_CHUNK = 64 * 1024
_TIMEOUT_SECONDS = 30
_USER_AGENT = "LeitorPDF/0.1"

ProgressCallback = Callable[[int, int], None]


class VoiceDownloadError(LeitorError):
    pass


class DownloadCancelled(Exception):
    pass


def parse_key(key: str) -> tuple[str, str, str]:
    """Split "pt_BR-faber-medium" into (language, name, quality)."""
    match = _KEY.match(key)
    if not match:
        raise ValueError(f"invalid voice key: {key!r}")
    return match.group(1), match.group(2), match.group(3)


@dataclass(frozen=True)
class Voice:
    key: str
    path: Path  # the .onnx model; its config sits next to it as .onnx.json

    @property
    def language(self) -> str:
        return parse_key(self.key)[0]

    @property
    def name(self) -> str:
        return parse_key(self.key)[1]

    @property
    def quality(self) -> str:
        return parse_key(self.key)[2]

    @property
    def label(self) -> str:
        pretty = self.name.replace("_", " ")
        pretty = pretty[:1].upper() + pretty[1:]
        return f"{pretty} · {self.language} · {self.quality}"


def voice_urls(key: str, base_url: str = HF_BASE) -> tuple[str, str]:
    language, name, quality = parse_key(key)
    family = language.split("_")[0]
    path = urllib.parse.quote(f"{family}/{language}/{name}/{quality}/{key}.onnx")
    onnx_url = f"{base_url}/{path}"
    return onnx_url, onnx_url + ".json"


def installed_voices(voices_dir: Path) -> list[Voice]:
    if not voices_dir.is_dir():
        return []
    found = []
    for model in sorted(voices_dir.glob("*.onnx")):
        key = model.name.removesuffix(".onnx")
        try:
            parse_key(key)
        except ValueError:
            continue
        if _is_complete(model) and _is_complete(_config_path(model)):
            found.append(Voice(key=key, path=model))
    return found


def download_voice(
    key: str,
    voices_dir: Path,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    opener: Callable[[str], Any] | None = None,
    base_url: str = HF_BASE,
) -> Voice:
    """Download a voice into voices_dir. Leaves no partial files on failure."""
    onnx_url, config_url = voice_urls(key, base_url)
    voices_dir.mkdir(parents=True, exist_ok=True)
    model = voices_dir / f"{key}.onnx"
    config = _config_path(model)
    if _is_complete(model) and _is_complete(config):
        return Voice(key=key, path=model)

    opener = opener or _open_url
    try:
        _fetch(config_url, config, None, cancel, opener)
        # The model goes last: its presence is what marks a voice as installed.
        _fetch(onnx_url, model, progress, cancel, opener)
    except DownloadCancelled:
        _remove(model, config)
        raise
    except OSError as exc:
        _remove(model, config)
        raise VoiceDownloadError(MSG_DOWNLOAD) from exc
    return Voice(key=key, path=model)


def _fetch(
    url: str,
    dest: Path,
    progress: ProgressCallback | None,
    cancel: threading.Event | None,
    opener: Callable[[str], Any],
) -> None:
    part = _part_path(dest)
    done = 0
    reported = None
    with opener(url) as response, open(part, "wb") as out:
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
    os.replace(part, dest)
    if progress is not None and reported != (done, done):
        progress(done, done)


def _open_url(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    return urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS)


def _content_length(response: Any) -> int:
    try:
        return max(int(response.headers.get("Content-Length") or 0), 0)
    except (TypeError, ValueError):
        return 0


def _config_path(model: Path) -> Path:
    return model.with_name(model.name + ".json")


def _part_path(path: Path) -> Path:
    return path.with_name(path.name + ".part")


def _is_complete(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _remove(*paths: Path) -> None:
    for path in paths:
        for candidate in (path, _part_path(path)):
            candidate.unlink(missing_ok=True)
