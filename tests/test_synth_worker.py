import threading
import time

from pagebard.playback.synth_worker import SynthEnd, SynthFailed, SynthItem, SynthWorker


def drain(worker, timeout=2.0):
    """Poll until SynthEnd (included) or fail after `timeout` seconds."""
    items = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = worker.poll()
        if item is None:
            time.sleep(0.002)
            continue
        items.append(item)
        if isinstance(item, SynthEnd):
            return items
    raise AssertionError(f"worker did not finish; got {items}")


def wait_dead(worker, timeout=1.0):
    deadline = time.monotonic() + timeout
    while worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.002)
    return not worker.is_alive()


def encode(text):
    return text.encode()


def test_delivers_in_order_then_end():
    worker = SynthWorker(encode, ["a", "b", "c"])
    worker.start()
    assert drain(worker) == [
        SynthItem(0, b"a"),
        SynthItem(1, b"b"),
        SynthItem(2, b"c"),
        SynthEnd(),
    ]
    assert wait_dead(worker)


def test_start_index():
    worker = SynthWorker(encode, ["a", "b", "c"], start=1)
    worker.start()
    assert drain(worker) == [SynthItem(1, b"b"), SynthItem(2, b"c"), SynthEnd()]


def test_poll_before_anything_is_ready_returns_none():
    gate = threading.Event()

    def blocked(text):
        gate.wait(2.0)
        return b"x"

    worker = SynthWorker(blocked, ["a"])
    worker.start()
    assert worker.poll() is None
    gate.set()
    assert drain(worker) == [SynthItem(0, b"x"), SynthEnd()]


def test_backpressure():
    calls = []

    def synth(text):
        calls.append(text)
        return b"x"

    worker = SynthWorker(synth, ["s"] * 20, lookahead=2)
    worker.start()
    time.sleep(0.2)
    assert len(calls) <= 3  # 2 queued + 1 waiting for room in the queue
    worker.stop()


def test_stop_while_queue_is_full():
    worker = SynthWorker(encode, ["s"] * 20, lookahead=2)
    worker.start()
    time.sleep(0.05)
    worker.stop()
    assert wait_dead(worker)
    assert worker.poll() == SynthEnd()
    assert worker.poll() == SynthEnd()


def test_failure_is_delivered_and_ends():
    boom = RuntimeError("boom")

    def synth(text):
        if text == "b":
            raise boom
        return text.encode()

    worker = SynthWorker(synth, ["a", "b", "c"])
    worker.start()
    assert drain(worker) == [SynthItem(0, b"a"), SynthFailed(1, boom), SynthEnd()]
    assert wait_dead(worker)


def test_empty_audio_is_skipped():
    worker = SynthWorker(lambda text: b"" if text == "b" else text.encode(), ["a", "b", "c"])
    worker.start()
    assert drain(worker) == [SynthItem(0, b"a"), SynthItem(2, b"c"), SynthEnd()]


def test_empty_sentence_list():
    worker = SynthWorker(encode, [])
    worker.start()
    assert drain(worker) == [SynthEnd()]


def test_poll_after_end_keeps_returning_end():
    worker = SynthWorker(encode, ["a"])
    worker.start()
    drain(worker)
    assert worker.poll() == SynthEnd()


def test_worker_thread_is_daemon():
    worker = SynthWorker(encode, [])
    assert worker.daemon
