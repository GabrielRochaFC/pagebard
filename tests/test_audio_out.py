"""QtAudioOut against the machine's real sound device. Only silence is played."""

import time

import pytest
from PySide6.QtMultimedia import QMediaDevices

from leitorpdf.playback.audio_out import QtAudioOut

RATE = 22050
SILENCE_100MS = b"\x00" * (RATE * 2 // 10)


@pytest.fixture
def out(qapp):
    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("no audio output device")
    out = QtAudioOut()
    yield out
    out.stop()


def wait_idle(out, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not out.is_idle() and time.monotonic() < deadline:
        time.sleep(0.01)
    return out.is_idle()


def test_opens_the_default_device_and_accepts_audio(out):
    out.start(RATE)
    assert out.bytes_free() >= len(SILENCE_100MS)
    assert out.write(SILENCE_100MS) == len(SILENCE_100MS)
    assert not out.is_idle()
    assert wait_idle(out)


def test_time_spent_paused_is_not_playing_time(out):
    out.start(RATE)
    out.write(SILENCE_100MS)
    out.suspend()
    time.sleep(0.4)  # longer than the audio itself
    assert not out.is_idle()
    out.resume()
    assert not out.is_idle()
    assert wait_idle(out)


def test_stopped_device_is_idle_and_takes_nothing(out):
    out.start(RATE)
    out.stop()
    assert out.is_idle()
    assert out.bytes_free() == 0
    assert out.write(SILENCE_100MS) == 0


def test_mono_samples_are_copied_to_both_channels():
    from leitorpdf.playback.audio_out import mono_to_stereo

    assert mono_to_stereo(b"\x01\x00\x02\xff") == b"\x01\x00\x01\x00\x02\xff\x02\xff"
    assert mono_to_stereo(b"") == b""


def test_stream_is_stereo_so_sound_reaches_both_ears(out):
    # A one-channel stream is wired to the left speaker only by PipeWire.
    out.start(RATE)
    assert out.channel_count == 2


def test_sizes_are_reported_in_mono_bytes(out):
    out.start(RATE)
    free = out.bytes_free()
    assert free % 2 == 0
    # 200 ms buffer, counted as the mono audio the player hands over
    assert free == RATE * 2 * 200 // 1000
    assert out.write(SILENCE_100MS) == len(SILENCE_100MS)
    assert out.bytes_free() <= free - len(SILENCE_100MS) + RATE * 2 // 20  # minus what played meanwhile
