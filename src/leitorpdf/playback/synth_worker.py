"""Synthesize sentences ahead of playback, on a background thread."""

import queue
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SynthItem:
    index: int
    audio: bytes


@dataclass(frozen=True)
class SynthFailed:
    index: int
    error: Exception


@dataclass(frozen=True)
class SynthEnd:
    pass


class SynthWorker(threading.Thread):
    """Feeds a bounded queue, so only `lookahead` sentences wait unplayed."""

    def __init__(
        self,
        synthesize: Callable[[str], bytes],
        sentences: Sequence[str],
        start: int = 0,
        lookahead: int = 3,
    ) -> None:
        super().__init__(name="leitorpdf-synth", daemon=True)
        self._synthesize = synthesize
        self._sentences = list(sentences)
        self._first = start
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, lookahead))
        self._stop_requested = threading.Event()
        self._ended = False

    def run(self) -> None:
        for index in range(self._first, len(self._sentences)):
            if self._stop_requested.is_set():
                return
            try:
                audio = self._synthesize(self._sentences[index])
            except Exception as exc:
                self._put(SynthFailed(index, exc))
                break
            # Nothing to say (symbols only, for instance): skip it.
            if audio and not self._put(SynthItem(index, audio)):
                return
        self._put(SynthEnd())

    def poll(self) -> SynthItem | SynthFailed | SynthEnd | None:
        """Next result without blocking; None when nothing is ready yet."""
        if self._ended or self._stop_requested.is_set():
            return SynthEnd()
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return None
        if isinstance(item, SynthEnd):
            self._ended = True
        return item

    def stop(self) -> None:
        self._stop_requested.set()

    def _put(self, item: SynthItem | SynthFailed | SynthEnd) -> bool:
        """Enqueue, waiting for room. False if stopped before there was any."""
        while not self._stop_requested.is_set():
            try:
                self._queue.put(item, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False
