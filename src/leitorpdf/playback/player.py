"""Plays sentences one after another, synthesizing a few ahead."""

import time
from collections.abc import Callable, Sequence
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal

from leitorpdf.core.errors import LeitorError, user_message
from leitorpdf.playback.audio_out import AudioOut, QtAudioOut
from leitorpdf.playback.synth_worker import SynthEnd, SynthFailed, SynthWorker

_TICK_MS = 20
_BYTES_PER_SAMPLE = 2


class PlayerState(Enum):
    STOPPED = "stopped"
    LOADING = "loading"  # waiting for the first audio
    PLAYING = "playing"
    PAUSED = "paused"


class Player(QObject):
    state_changed = Signal(object)  # PlayerState
    sentence_started = Signal(int)  # index into the sentences given to play()
    finished = Signal()
    error = Signal(str)  # user-facing message

    def __init__(self, audio_out: AudioOut | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._audio: AudioOut = audio_out if audio_out is not None else QtAudioOut()
        self._state = PlayerState.STOPPED
        self._worker: SynthWorker | None = None
        self._retired: list[SynthWorker] = []  # stopped, possibly still finishing
        self._pending = b""  # audio of the sentence being sent to the device
        self._offset = 0
        self._heard_audio = False
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self.tick)

    @property
    def state(self) -> PlayerState:
        return self._state

    def play(
        self,
        synthesize: Callable[[str], bytes],
        sample_rate: int,
        sentences: Sequence[str],
        start: int = 0,
    ) -> None:
        self.stop()
        try:
            self._audio.start(sample_rate)
        except LeitorError as exc:
            self.error.emit(str(exc))
            return
        self._worker = SynthWorker(synthesize, sentences, start)
        self._worker.start()
        self._set_state(PlayerState.LOADING)
        self._timer.start()

    def pause(self) -> None:
        if self._state in (PlayerState.PLAYING, PlayerState.LOADING):
            self._audio.suspend()
            self._set_state(PlayerState.PAUSED)

    def resume(self) -> None:
        if self._state is PlayerState.PAUSED:
            self._audio.resume()
            self._set_state(
                PlayerState.PLAYING if self._heard_audio else PlayerState.LOADING
            )

    def stop(self) -> None:
        if self._state is PlayerState.STOPPED:
            return
        self._timer.stop()
        self._retire_worker()
        self._audio.stop()
        self._pending = b""
        self._offset = 0
        self._heard_audio = False
        self._set_state(PlayerState.STOPPED)

    def shutdown(self, timeout: float = 3.0) -> None:
        """Stop and wait for synthesis threads to end (before the app exits)."""
        self.stop()
        deadline = time.monotonic() + timeout
        for worker in self._retired:
            worker.join(max(0.0, deadline - time.monotonic()))
        self._retired = [worker for worker in self._retired if worker.is_alive()]

    def _retire_worker(self) -> None:
        self._retired = [worker for worker in self._retired if worker.is_alive()]
        if self._worker is not None:
            self._worker.stop()
            self._retired.append(self._worker)
            self._worker = None

    def tick(self) -> None:
        """Move audio from the synthesis queue to the device. Never blocks."""
        if self._state in (PlayerState.STOPPED, PlayerState.PAUSED):
            return
        try:
            self._advance()
        except LeitorError as exc:
            self.stop()
            self.error.emit(str(exc))

    def _advance(self) -> None:
        if self._offset >= len(self._pending):
            item = self._worker.poll()
            if item is None:
                return
            if isinstance(item, SynthFailed):
                self.stop()
                self.error.emit(user_message(item.error))
                return
            if isinstance(item, SynthEnd):
                if self._audio.is_idle():
                    self.stop()
                    self.finished.emit()
                return
            self._pending = item.audio
            self._offset = 0
            self._heard_audio = True
            self._set_state(PlayerState.PLAYING)
            self.sentence_started.emit(item.index)

        remaining = len(self._pending) - self._offset
        count = min(remaining, self._audio.bytes_free())
        count -= count % _BYTES_PER_SAMPLE  # never split a 16-bit sample
        if count > 0:
            chunk = self._pending[self._offset : self._offset + count]
            self._offset += self._audio.write(chunk)
        elif remaining < _BYTES_PER_SAMPLE:
            self._offset = len(self._pending)  # drop a stray half sample

    def _set_state(self, state: PlayerState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)
