import threading
import time
import weakref

from fakes import wait_until
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from leitorpdf.core.errors import LeitorError
from leitorpdf.ui.progress import Cancelled, run_with_progress


def test_returns_the_result(qapp):
    notes = []
    outcome = run_with_progress(None, "Trabalhando…", lambda report, cancel: 42, notes.append)
    assert outcome == ("done", 42)
    assert notes == []


def test_a_result_of_none_still_counts_as_done(qapp):
    assert run_with_progress(None, "…", lambda report, cancel: None) == ("done", None)


def test_progress_is_shown(qapp):
    seen = {}
    looked = threading.Event()

    def work(report, cancel):
        report(50, 200, "Metade do caminho")
        looked.wait(3.0)
        return "ok"

    def look():
        dialog = QApplication.activeModalWidget()
        seen.update(value=dialog.value(), text=dialog.labelText(), top=dialog.maximum())
        looked.set()

    QTimer.singleShot(150, look)
    assert run_with_progress(None, "Trabalhando…", work) == ("done", "ok")
    assert seen == {"value": 25, "text": "Metade do caminho", "top": 100}


def test_unknown_total_shows_a_busy_bar(qapp):
    seen = {}
    looked = threading.Event()

    def work(report, cancel):
        report(3, 0)
        looked.wait(3.0)

    def look():
        dialog = QApplication.activeModalWidget()
        seen.update(top=dialog.maximum(), text=dialog.labelText())
        looked.set()

    QTimer.singleShot(150, look)
    run_with_progress(None, "Trabalhando…", work)
    assert seen == {"top": 0, "text": "Trabalhando…"}


def test_failure_is_reported(qapp):
    notes = []

    def work(report, cancel):
        raise LeitorError("Deu errado.")

    assert run_with_progress(None, "…", work, notes.append) == ("failed", None)
    assert notes == ["Deu errado."]


def test_unexpected_failure_gets_the_generic_message(qapp):
    notes = []

    def work(report, cancel):
        raise RuntimeError("x")

    assert run_with_progress(None, "…", work, notes.append) == ("failed", None)
    assert notes == ["Ocorreu um erro inesperado. Detalhe técnico: x"]


def test_cancel_button(qapp):
    notes = []
    seen = {}

    def work(report, cancel):
        seen["cancel_requested"] = cancel.wait(3.0)
        raise Cancelled()

    QTimer.singleShot(50, lambda: QApplication.activeModalWidget().cancel())
    assert run_with_progress(None, "…", work, notes.append) == ("cancelled", None)
    wait_until(qapp, lambda: seen)
    assert seen == {"cancel_requested": True}
    assert notes == []


def test_work_can_name_its_own_cancel_exception(qapp):
    class Stopped(Exception):
        pass

    def work(report, cancel):
        cancel.wait(3.0)
        raise Stopped()

    QTimer.singleShot(50, lambda: QApplication.activeModalWidget().cancel())
    assert run_with_progress(None, "…", work, cancelled=(Stopped,)) == ("cancelled", None)


def test_cancel_returns_promptly_even_if_the_work_is_stuck(qapp):
    release = threading.Event()

    def stuck(report, cancel):
        release.wait(1.5)  # deaf to the cancel request
        return "tarde demais"

    QTimer.singleShot(50, lambda: QApplication.activeModalWidget().cancel())
    began = time.monotonic()
    outcome = run_with_progress(None, "…", stuck)
    elapsed = time.monotonic() - began
    release.set()
    assert outcome == ("cancelled", None)
    assert elapsed < 0.5


def test_worker_thread_is_handed_nothing_that_qt_watches(qapp):
    seen = {}

    def work(report, cancel):
        time.sleep(0.1)  # let the dialog finish wiring itself up
        seen["watchers"] = weakref.getweakrefcount(cancel)

    run_with_progress(None, "…", work)
    assert seen == {"watchers": 0}
