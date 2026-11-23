import re

import pytest

from pagebard.core import paths
from pagebard.core.tts import MSG_TTS, Synthesizer, TtsError
from pagebard.core.voices import DEFAULT_VOICE_KEY

# Resolved at import time, before any test redirects XDG_DATA_HOME.
REAL = paths.voices_dir() / f"{DEFAULT_VOICE_KEY}.onnx"
needs_voice = pytest.mark.skipif(not REAL.exists(), reason="default voice not installed")


def fake_model(tmp_path, config='{"audio": {"sample_rate": 22050}}'):
    model = tmp_path / "pt_BR-x-medium.onnx"
    model.write_bytes(b"lixo")
    if config is not None:
        (tmp_path / "pt_BR-x-medium.onnx.json").write_text(config, encoding="utf-8")
    return model


def test_sample_rate_read_without_loading_model(tmp_path):
    assert Synthesizer(fake_model(tmp_path)).sample_rate == 22050


def test_missing_config_is_tts_error(tmp_path):
    with pytest.raises(TtsError, match=re.escape(MSG_TTS)):
        Synthesizer(fake_model(tmp_path, config=None)).sample_rate


def test_invalid_config_is_tts_error(tmp_path):
    with pytest.raises(TtsError, match=re.escape(MSG_TTS)):
        Synthesizer(fake_model(tmp_path, config="{ not json")).sample_rate


def test_corrupt_model_is_tts_error(tmp_path):
    with pytest.raises(TtsError, match=re.escape(MSG_TTS)):
        Synthesizer(fake_model(tmp_path)).synthesize("Olá.")


@needs_voice
def test_synthesizes_speech():
    synth = Synthesizer(REAL)
    pcm = synth.synthesize("Olá, mundo.")
    assert len(pcm) % 2 == 0
    assert len(pcm) > synth.sample_rate  # more than half a second of 16-bit audio


@needs_voice
def test_length_scale_changes_duration():
    synth = Synthesizer(REAL)
    text = "Esta frase serve para medir a duração."
    assert len(synth.synthesize(text, length_scale=0.6)) < len(
        synth.synthesize(text, length_scale=1.0)
    )


@needs_voice
def test_unpronounceable_text_does_not_raise():
    assert isinstance(Synthesizer(REAL).synthesize("***"), bytes)
