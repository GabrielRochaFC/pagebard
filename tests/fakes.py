"""Test doubles shared by the playback and UI tests."""


class FakeAudioOut:
    """Stands in for the sound card: records what the player sends to it."""

    def __init__(self):
        self.written = bytearray()
        self.started_rates = []
        self.suspended = False
        self.stopped = True
        self.free = 1 << 20  # bytes accepted per tick
        self.idle = True  # everything written has finished playing
        self.fail_on_start = None
        self.fail_on_write = None
        self.writes_while_suspended = 0

    def start(self, sample_rate):
        if self.fail_on_start is not None:
            raise self.fail_on_start
        self.started_rates.append(sample_rate)
        self.written.clear()
        self.suspended = False
        self.stopped = False

    def bytes_free(self):
        return self.free

    def write(self, data):
        if self.fail_on_write is not None:
            raise self.fail_on_write
        if self.suspended:
            self.writes_while_suspended += 1
        self.written += data
        return len(data)

    def suspend(self):
        self.suspended = True

    def resume(self):
        self.suspended = False

    def stop(self):
        self.stopped = True

    def is_idle(self):
        return self.idle


class FakeSynth:
    """Stands in for core.tts.Synthesizer."""

    sample_rate = 22050

    def __init__(self, audio=b"\x00\x00" * 10, error=None):
        self.audio = audio
        self.error = error
        self.spoken = []

    def synthesize(self, text, length_scale=1.0):
        if self.error is not None:
            raise self.error
        self.spoken.append(text)
        return self.audio


def wait_until(qapp, condition, timeout=3.0):
    """Run the Qt event loop until `condition()` holds."""
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the UI")
        qapp.processEvents()
        time.sleep(0.005)
