"""Piper voices: which ones are installed, which exist, how to get one."""

import http.client
import json
import os
import re
import tempfile
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pagebard.core.i18n import _, language, N_
from pagebard.core.download import (
    DownloadCancelled,  # noqa: F401  (raised by download_voice; callers import it here)
    ProgressCallback,
    discard,
    fetch_to_temp,
    open_url,
)
from pagebard.core.errors import PagebardError

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
# The voice offered on first use follows the language of the interface.
_DEFAULT_VOICES = {"pt_BR": "pt_BR-faber-medium", "es": "es_ES-davefx-medium"}
DEFAULT_VOICE_KEY = _DEFAULT_VOICES.get(language(), "en_US-lessac-medium")
# The language of that voice, e.g. "pt_BR": it comes first in lists of voices.
PREFERRED_LANGUAGE = DEFAULT_VOICE_KEY.split("-")[0]
MSG_DOWNLOAD = (
    _("The voice could not be downloaded. Check your internet connection and try again.")
)

CATALOG_URL = HF_BASE + "/voices.json"
MSG_CATALOG = (
    _("The list of voices could not be fetched. Check your internet connection.")
)

_LANGUAGES = {
    "pt_BR": N_("Portuguese (Brazil)"),
    "pt_PT": N_("Portuguese (Portugal)"),
    "en_US": N_("English (US)"),
    "en_GB": N_("English (UK)"),
    "es_ES": N_("Spanish (Spain)"),
    "es_MX": N_("Spanish (Mexico)"),
    "es_AR": N_("Spanish (Argentina)"),
    "fr_FR": N_("French"),
    "de_DE": N_("German"),
    "it_IT": N_("Italian"),
}
_QUALITIES = {"x_low": N_("very low"), "low": N_("low"), "medium": N_("medium"), "high": N_("high")}
_QUALITY_ORDER = ["x_low", "low", "medium", "high"]

_KEY = re.compile(r"^([a-z]{2,3}_[A-Z]{2})-([^-]+)-([a-z_]+)$")



class VoiceDownloadError(PagebardError):
    pass


def parse_key(key: str) -> tuple[str, str, str]:
    """Split "pt_BR-faber-medium" into (language, name, quality)."""
    match = _KEY.match(key)
    if not match:
        raise ValueError(f"invalid voice key: {key!r}")
    return match.group(1), match.group(2), match.group(3)


def language_label(code: str) -> str:
    """Name of a voice language for the user, e.g. "Portuguese (Brazil)"; the code if unknown."""
    name = _LANGUAGES.get(code)
    return _(name) if name else code


def quality_label(quality: str) -> str:
    name = _QUALITIES.get(quality)
    return _(name) if name else quality


def _label(key: str) -> str:
    language, name, quality = parse_key(key)
    pretty = name.replace("_", " ")
    pretty = pretty[:1].upper() + pretty[1:]
    return f"{pretty} · {language_label(language)} · {quality_label(quality)}"


@dataclass(frozen=True)
class CatalogVoice:
    """A voice that exists for download."""

    key: str
    language: str
    name: str
    quality: str
    size_bytes: int

    @property
    def label(self) -> str:
        return _label(self.key)


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
        return _label(self.key)


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


def remove_voice(key: str, voices_dir: Path) -> None:
    model = voices_dir / f"{key}.onnx"
    # The model first: without it the voice no longer counts as installed.
    for path in (model, _config_path(model)):
        path.unlink(missing_ok=True)


def parse_catalog(data: Any) -> list[CatalogVoice]:
    """Voices in a voices.json document; entries that make no sense are skipped."""
    voices = []
    if not isinstance(data, dict):
        raise ValueError("catalog is not an object")
    for entry in data.values():
        try:
            key = entry["key"]
            language, name, quality = parse_key(key)
            size = sum(int(item["size_bytes"]) for item in entry["files"].values())
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        voices.append(CatalogVoice(key, language, name, quality, size))
    voices.sort(key=_catalog_order)
    return voices


def _catalog_order(voice: CatalogVoice) -> tuple:
    rank = _QUALITY_ORDER.index(voice.quality) if voice.quality in _QUALITY_ORDER else 99
    return (
        voice.language != PREFERRED_LANGUAGE,
        language_label(voice.language).casefold(),
        voice.name,
        rank,
    )


def fetch_catalog(
    cache_file: Path, opener: Callable[[str], Any] | None = None
) -> list[CatalogVoice]:
    """The list of downloadable voices; the last good copy when offline."""
    opener = opener or open_url
    try:
        with opener(CATALOG_URL) as response:
            raw = response.read()
        voices = parse_catalog(json.loads(raw))
        if not voices:
            raise ValueError("catalog has no voices")
    except (OSError, ValueError, http.client.HTTPException) as exc:
        try:
            return parse_catalog(json.loads(cache_file.read_bytes()))
        except (OSError, ValueError):
            raise VoiceDownloadError(MSG_CATALOG) from exc
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=cache_file.parent, suffix=".part")
        with os.fdopen(handle, "wb") as out:
            out.write(raw)
        os.replace(name, cache_file)
    except OSError:
        pass  # no cache this time; the list itself is fine
    return voices


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

    opener = opener or open_url
    # Each attempt writes to its own temporary files, so an older attempt that
    # is still winding down can never damage a newer one.
    temps: list[Path] = []
    try:
        config_part = fetch_to_temp(config_url, voices_dir, None, cancel, opener, temps)
        model_part = fetch_to_temp(onnx_url, voices_dir, progress, cancel, opener, temps)
        os.replace(config_part, config)
        # The model goes last: its presence is what marks a voice as installed.
        os.replace(model_part, model)
    except DownloadCancelled:
        discard(temps)
        raise
    except Exception as exc:
        discard(temps)
        raise VoiceDownloadError(MSG_DOWNLOAD) from exc
    return Voice(key=key, path=model)


def _config_path(model: Path) -> Path:
    return model.with_name(model.name + ".json")


def _is_complete(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0
