from fakes import wait_until
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
    wait_until(qapp, lambda: seen)  # the dialog does not wait for the thread
    assert seen == {"cancel_requested": True}
    assert notes == []


def test_cancel_returns_promptly_even_if_the_download_is_stuck(qapp, tmp_path):
    import threading
    import time

    notes = []
    release = threading.Event()

    def stuck_download(key, voices_dir, progress=None, cancel=None):
        release.wait(1.5)  # like a socket waiting for data: deaf to the cancel request
        raise DownloadCancelled()

    QTimer.singleShot(50, lambda: QApplication.activeModalWidget().cancel())
    began = time.monotonic()
    voice = download_default_voice(None, tmp_path, notify=notes.append, download=stuck_download)
    elapsed = time.monotonic() - began
    release.set()
    assert voice is None
    assert elapsed < 0.5
    assert notes == []


def test_stuck_download_ending_after_the_dialog_is_gone_is_harmless(qapp, tmp_path):
    # Regression: the download thread used to hold the last reference to Qt
    # objects of the closed dialog, and destroying them off the UI thread
    # crashed the whole program.
    import threading

    def download_threads():
        return [t for t in threading.enumerate() if t.name == "leitorpdf-download"]

    for _ in range(15):
        release = threading.Event()

        def stuck_download(key, voices_dir, progress=None, cancel=None, release=release):
            release.wait(2.0)
            progress(1, 2)  # reports after nobody is listening any more
            raise DownloadCancelled()

        QTimer.singleShot(20, lambda: QApplication.activeModalWidget().cancel())
        voice = download_default_voice(None, tmp_path, notify=[].append, download=stuck_download)
        assert voice is None
        release.set()
        wait_until(qapp, lambda: not download_threads())


def test_download_thread_is_handed_nothing_that_qt_watches(qapp, tmp_path):
    # Qt signal connections to a bound method watch its object through a weak
    # reference; if the download thread drops the last reference, that watcher
    # runs off the UI thread and crashes. So the cancel event must be unwatched.
    import time
    import weakref

    seen = {}

    def fake_download(key, voices_dir, progress=None, cancel=None):
        time.sleep(0.1)  # let the dialog finish wiring itself up
        seen["watchers"] = weakref.getweakrefcount(cancel)
        return Voice(key, voices_dir / f"{key}.onnx")

    download_default_voice(None, tmp_path, notify=[].append, download=fake_download)
    assert seen == {"watchers": 0}
