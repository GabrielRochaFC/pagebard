"""Text to speech with a Piper voice, on the CPU."""

import json
import threading
from pathlib import Path
from typing import Any

from pagebard.core.i18n import _
from pagebard.core.errors import PagebardError

MSG_TTS = _("This voice could not produce speech. Try downloading the voice again.")


class TtsError(PagebardError):
    pass


class Synthesizer:
    """Turns text into 16-bit mono PCM. The model is loaded on first use."""

    def __init__(self, model_path: Path) -> None:
        self._model_path = Path(model_path)
        self._voice: Any = None
        self._sample_rate: int | None = None
        # A stopping reader and a new one may overlap; Piper's phonemizer
        # keeps global state, so only one synthesis runs at a time.
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        if self._sample_rate is None:
            config = self._model_path.with_name(self._model_path.name + ".json")
            try:
                data = json.loads(config.read_text(encoding="utf-8"))
                rate = int(data["audio"]["sample_rate"])
                if rate <= 0:
                    raise ValueError(f"invalid sample rate: {rate}")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise TtsError(MSG_TTS) from exc
            self._sample_rate = rate
        return self._sample_rate

    def synthesize(self, text: str, length_scale: float = 1.0) -> bytes:
        try:
            with self._lock:
                # Imported here: loading onnxruntime costs startup time.
                from piper import PiperVoice, SynthesisConfig

                if self._voice is None:
                    self._voice = PiperVoice.load(self._model_path, use_cuda=False)
                config = SynthesisConfig(length_scale=length_scale)
                chunks = self._voice.synthesize(text, syn_config=config)
                return b"".join(chunk.audio_int16_bytes for chunk in chunks)
        except Exception as exc:
            raise TtsError(MSG_TTS) from exc
