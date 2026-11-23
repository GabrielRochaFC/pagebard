import threading

from fakes import wait_until

from pagebard.ui.tasks import run_async


def test_result_is_delivered_on_the_ui_thread(qapp):
    seen = {}

    def work():
        seen["worker"] = threading.current_thread()
        return 42

    def done(value):
        seen["value"] = value
        seen["callback"] = threading.current_thread()

    run_async(work, done, lambda exc: seen.setdefault("error", exc))
    wait_until(qapp, lambda: "value" in seen)
    assert seen["value"] == 42
    assert seen["worker"] is not threading.main_thread()
    assert seen["callback"] is threading.main_thread()
    assert "error" not in seen


def test_exception_goes_to_on_error(qapp):
    seen = {}
    boom = RuntimeError("boom")

    def work():
        raise boom

    def failed(exc):
        seen["error"] = exc
        seen["callback"] = threading.current_thread()

    run_async(work, lambda value: seen.setdefault("value", value), failed)
    wait_until(qapp, lambda: "error" in seen)
    assert seen["error"] is boom
    assert seen["callback"] is threading.main_thread()
    assert "value" not in seen


def test_many_tasks_all_report_back(qapp):
    results = []
    for n in range(20):
        run_async(lambda n=n: n * 2, results.append, results.append)
    wait_until(qapp, lambda: len(results) == 20)
    assert sorted(results) == [n * 2 for n in range(20)]


def test_result_arriving_after_qt_is_gone_is_dropped_quietly(qapp):
    # Closing the program while a file is still loading: the worker thread
    # finishes after Qt has torn down the object that carries results.
    import shiboken6

    from pagebard.ui import tasks

    bridge = tasks._Bridge()
    succeeding = tasks._Task(1, lambda: 42, bridge)
    failing = tasks._Task(2, lambda: 1 / 0, bridge)
    shiboken6.delete(bridge)
    succeeding.run()  # must not raise
    failing.run()
