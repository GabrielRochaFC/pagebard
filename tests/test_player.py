import threading
import time

import pytest
from fakes import FakeAudioOut

from leitorpdf.core.errors import LeitorError
from leitorpdf.playback.audio_out import MSG_NO_AUDIO, AudioError
from leitorpdf.playback.player import Player, PlayerState

RATE = 22050


def run(player, until, timeout=2.0):
    """Drive the player by hand until `until()` holds."""
    deadline = time.monotonic() + timeout
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the player")
        player.tick()
        time.sleep(0.002)


def synth_threads():
    return [t for t in threading.enumerate() if t.name == "leitorpdf-synth"]


def wait_no_synth_threads(timeout=1.0):
    deadline = time.monotonic() + timeout
    while synth_threads() and time.monotonic() < deadline:
        time.sleep(0.002)
    return not synth_threads()


def repeat4(text):
    return text.encode() * 4


class Recorder:
    def __init__(self, player):
        self.states = []
        self.started = []
        self.errors = []
        self.finished = 0
        player.state_changed.connect(self.states.append)
        player.sentence_started.connect(self.started.append)
        player.error.connect(self.errors.append)
        player.finished.connect(self._on_finished)

    def _on_finished(self):
        self.finished += 1


@pytest.fixture
def out():
    return FakeAudioOut()


@pytest.fixture
def player(qapp, out):
    player = Player(out)
    yield player
    player.stop()
    assert wait_no_synth_threads()


@pytest.fixture
def rec(player):
    return Recorder(player)


def test_plays_all_sentences_in_order(player, out, rec):
    player.play(repeat4, RATE, ["aa", "bb", "cc"])
    run(player, lambda: rec.finished)
    assert rec.started == [0, 1, 2]
    assert bytes(out.written) == b"aaaaaaaa" + b"bbbbbbbb" + b"cccccccc"
    assert rec.states == [PlayerState.LOADING, PlayerState.PLAYING, PlayerState.STOPPED]
    assert rec.finished == 1
    assert rec.errors == []
    assert out.stopped
    assert out.started_rates == [RATE]
    assert player.state is PlayerState.STOPPED


def test_respects_bytes_free(player, out):
    out.free = 10
    player.play(lambda text: b"z" * 26, RATE, ["s"])
    run(player, lambda: len(out.written) > 0)
    assert len(out.written) == 10
    player.tick()
    assert len(out.written) == 20
    player.tick()
    assert len(out.written) == 26


def test_writes_whole_samples_only(player, out):
    out.free = 5  # room for two 16-bit samples and a half
    player.play(lambda text: b"z" * 8, RATE, ["s"])
    run(player, lambda: len(out.written) > 0)
    assert len(out.written) == 4


def test_pause_and_resume(player, out, rec):
    out.free = 4
    player.play(repeat4, RATE, ["aaaa", "bbbb"])
    run(player, lambda: player.state is PlayerState.PLAYING)
    player.pause()
    assert player.state is PlayerState.PAUSED
    assert out.suspended
    before = len(out.written)
    for _ in range(10):
        player.tick()
    assert len(out.written) == before
    player.resume()
    assert not out.suspended
    assert player.state is PlayerState.PLAYING
    run(player, lambda: rec.finished)
    assert bytes(out.written) == b"aaaa" * 4 + b"bbbb" * 4
    assert out.writes_while_suspended == 0


def test_resume_before_first_audio_returns_to_loading(player, out, rec):
    gate = threading.Event()

    def slow(text):
        gate.wait(2.0)
        return b"zz"

    player.play(slow, RATE, ["s"])
    player.pause()
    player.resume()
    gate.set()
    run(player, lambda: rec.finished)
    assert rec.states == [
        PlayerState.LOADING,
        PlayerState.PAUSED,
        PlayerState.LOADING,
        PlayerState.PLAYING,
        PlayerState.STOPPED,
    ]


def test_does_not_finish_while_audio_still_playing(player, out, rec):
    out.idle = False
    player.play(repeat4, RATE, ["aa"])
    run(player, lambda: len(out.written) == 8)
    for _ in range(50):
        player.tick()
        time.sleep(0.002)
    assert rec.finished == 0
    assert player.state is PlayerState.PLAYING
    out.idle = True
    run(player, lambda: rec.finished)
    assert rec.finished == 1


def test_synthesis_failure_reports_error(player, out, rec):
    def failing(text):
        raise LeitorError("Falhou.")

    player.play(failing, RATE, ["a", "b"])
    run(player, lambda: rec.errors)
    assert rec.errors == ["Falhou."]
    assert player.state is PlayerState.STOPPED
    assert rec.finished == 0
    assert out.stopped


def test_unexpected_synthesis_failure_gets_generic_message(player, rec):
    def failing(text):
        raise RuntimeError("x")

    player.play(failing, RATE, ["a"])
    run(player, lambda: rec.errors)
    assert rec.errors == ["Ocorreu um erro inesperado. Detalhe técnico: x"]


def test_audio_device_error_reports_error(player, out, rec):
    out.fail_on_start = AudioError(MSG_NO_AUDIO)
    player.play(repeat4, RATE, ["a"])
    assert rec.errors == [MSG_NO_AUDIO]
    assert player.state is PlayerState.STOPPED
    assert rec.states == []
    assert synth_threads() == []


def test_audio_error_during_playback_reports_error(player, out, rec):
    out.fail_on_write = AudioError(MSG_NO_AUDIO)
    player.play(repeat4, RATE, ["a"])
    run(player, lambda: rec.errors)
    assert rec.errors == [MSG_NO_AUDIO]
    assert player.state is PlayerState.STOPPED
    assert rec.finished == 0


def test_play_while_playing_restarts_cleanly(player, out, rec):
    out.free = 2
    player.play(lambda text: b"xx" * 4, RATE, ["s"] * 50)
    run(player, lambda: player.state is PlayerState.PLAYING)
    player.play(repeat4, RATE, ["yy"])
    assert len(synth_threads()) <= 2  # the old one may still be winding down
    run(player, lambda: rec.finished)
    assert bytes(out.written) == b"yyyyyyyy"
    assert rec.finished == 1
    assert out.started_rates == [RATE, RATE]
    assert wait_no_synth_threads()


def test_start_index_is_forwarded(player, rec):
    player.play(repeat4, RATE, ["aa", "bb", "cc"], start=2)
    run(player, lambda: rec.finished)
    assert rec.started == [2]


def test_stop_during_playback(player, out, rec):
    out.free = 2
    player.play(repeat4, RATE, ["aaaa"] * 20)
    run(player, lambda: player.state is PlayerState.PLAYING)
    player.stop()
    assert player.state is PlayerState.STOPPED
    assert out.stopped
    before = len(out.written)
    for _ in range(10):
        player.tick()
    assert len(out.written) == before
    assert rec.finished == 0
    assert wait_no_synth_threads()


def test_everything_is_a_noop_when_stopped(player, out, rec):
    player.stop()
    player.pause()
    player.resume()
    player.tick()
    assert rec.states == []
    assert player.state is PlayerState.STOPPED
    assert out.started_rates == []


def test_rapid_toggle(player, out, rec):
    out.free = 2
    player.play(repeat4, RATE, ["aa", "bb", "cc"])
    run(player, lambda: player.state is PlayerState.PLAYING)
    for _ in range(100):
        player.pause()
        player.tick()
        player.resume()
        player.tick()
    run(player, lambda: rec.finished)
    assert bytes(out.written) == b"aaaaaaaa" + b"bbbbbbbb" + b"cccccccc"
    assert out.writes_while_suspended == 0
    assert rec.finished == 1


def test_shutdown_waits_for_synthesis_in_flight(player, out):
    def slow(text):
        time.sleep(0.3)
        return b"zz"

    player.play(slow, RATE, ["a", "b", "c"])
    time.sleep(0.05)  # the worker is now inside the first synthesis
    player.shutdown()
    assert synth_threads() == []
    assert player.state is PlayerState.STOPPED


def test_current_index_follows_playback(player, out, rec):
    assert player.current_index is None
    out.free = 2
    player.play(repeat4, RATE, ["aa", "bb"])
    assert player.current_index is None  # nothing has reached the device yet
    run(player, lambda: rec.started == [0])
    assert player.current_index == 0
    run(player, lambda: rec.started == [0, 1])
    assert player.current_index == 1
    run(player, lambda: rec.finished)
    assert player.current_index is None


def test_resynthesize_applies_to_following_sentences(player, out, rec):
    mode = {"sound": b"a"}
    out.free = 2
    player.play(lambda text: mode["sound"] * 4, RATE, ["s"] * 4)
    run(player, lambda: rec.started == [0])
    mode["sound"] = b"b"
    player.resynthesize_upcoming()
    run(player, lambda: rec.finished)
    assert bytes(out.written) == b"aaaa" + b"bbbb" * 3
    assert rec.started == [0, 1, 2, 3]
    assert rec.finished == 1


def test_resynthesize_before_first_audio_restarts_from_start_index(player, out, rec):
    gate = threading.Event()

    def slow(text):
        gate.wait(2.0)
        return text.encode() * 2

    player.play(slow, RATE, ["aa", "bb", "cc"], start=1)
    player.resynthesize_upcoming()
    gate.set()
    run(player, lambda: rec.finished)
    assert rec.started == [1, 2]
    assert bytes(out.written) == b"bbbb" + b"cccc"


def test_resynthesize_many_times_in_a_row(player, out, rec):
    out.free = 2
    player.play(repeat4, RATE, ["aa", "bb", "cc", "dd"])
    run(player, lambda: rec.started == [0])
    for _ in range(50):
        player.resynthesize_upcoming()
        player.tick()
    run(player, lambda: rec.finished)
    assert rec.started == [0, 1, 2, 3]
    assert bytes(out.written) == b"aaaaaaaa" + b"bbbbbbbb" + b"cccccccc" + b"dddddddd"
    assert wait_no_synth_threads()


def test_resynthesize_when_stopped_is_a_noop(player, rec):
    player.resynthesize_upcoming()
    assert rec.states == []
    assert synth_threads() == []


def test_resynthesize_while_paused_stays_paused(player, out, rec):
    out.free = 2
    player.play(repeat4, RATE, ["aa", "bb"])
    run(player, lambda: rec.started == [0])
    player.pause()
    player.resynthesize_upcoming()
    assert player.state is PlayerState.PAUSED
    assert out.suspended
    player.resume()
    run(player, lambda: rec.finished)
    assert rec.started == [0, 1]
