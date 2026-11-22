from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from leitorpdf.core.voices import (
    DEFAULT_VOICE_KEY,
    MSG_DOWNLOAD,
    DownloadCancelled,
    Voice,
    VoiceDownloadError,
)
from leitorpdf.ui.voice_download import download_default_voice


def test_returns_the_voice_when_the_download_succeeds(qapp, tmp_path):
    notes = []

    def fake_download(key, voices_dir, progress=None, cancel=None):
        progress(50, 100)
        progress(100, 100)
        return Voice(key, voices_dir / f"{key}.onnx")

    voice = download_default_voice(None, tmp_path, notify=notes.append, download=fake_download)
    assert voice == Voice(DEFAULT_VOICE_KEY, tmp_path / f"{DEFAULT_VOICE_KEY}.onnx")
    assert notes == []


def test_failure_is_reported_and_returns_none(qapp, tmp_path):
    notes = []

    def fake_download(key, voices_dir, progress=None, cancel=None):
        raise VoiceDownloadError(MSG_DOWNLOAD)

    voice = download_default_voice(None, tmp_path, notify=notes.append, download=fake_download)
    assert voice is None
    assert notes == [MSG_DOWNLOAD]


def test_cancel_button_stops_the_download(qapp, tmp_path):
    notes = []
    seen = {}

    def fake_download(key, voices_dir, progress=None, cancel=None):
        seen["cancel_requested"] = cancel.wait(3.0)
        raise DownloadCancelled()

    QTimer.singleShot(50, lambda: QApplication.activeModalWidget().cancel())
    voice = download_default_voice(None, tmp_path, notify=notes.append, download=fake_download)
    assert voice is None
    assert seen == {"cancel_requested": True}
    assert notes == []
