"""Where synthesized audio goes: the default sound device, through Qt."""

import time
from array import array
from typing import Protocol

from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio

from pagebard.core.errors import PagebardError

MSG_NO_AUDIO = (
    "Nenhuma saída de áudio foi encontrada. Conecte alto-falantes ou fones "
    "de ouvido e tente novamente."
)

_BYTES_PER_SAMPLE = 2  # 16-bit
# The device gets two channels: PipeWire wires a one-channel stream to the
# left speaker only, so each mono sample is sent to both sides.
_DEVICE_CHANNELS = 2
_BUFFER_MS = 200
# Time the sound server may still need after our own estimate says "done".
_DRAIN_MARGIN_SECONDS = 0.15
# QAudioSink.error() returns QtAudio.Error; the older QAudio.Error is a
# different Python enum and never compares equal to it.
_HEALTHY = (QtAudio.Error.NoError, QtAudio.Error.UnderrunError)


class AudioError(PagebardError):
    pass


def mono_to_stereo(data: bytes) -> bytes:
    """Duplicate every 16-bit sample so left and right carry the same sound."""
    mono = array("h")
    mono.frombytes(data)
    stereo = array("h", bytes(len(data) * 2))
    stereo[0::2] = mono
    stereo[1::2] = mono
    return stereo.tobytes()


class AudioOut(Protocol):
    """A device that plays 16-bit mono PCM pushed to it in small pieces.

    Sizes are always in bytes of mono audio, whatever the device needs.
    """

    def start(self, sample_rate: int) -> None: ...
    def bytes_free(self) -> int: ...
    def write(self, data: bytes) -> int: ...
    def suspend(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def is_idle(self) -> bool: ...


class QtAudioOut:
    def __init__(self) -> None:
        self._sink: QAudioSink | None = None
        self._io = None
        self._bytes_per_second = 0
        # When the audio written so far will have finished playing. Tracked by
        # clock because sink state changes lag behind writes on some backends.
        self._ends_at = 0.0
        self._suspended_at: float | None = None

    @property
    def channel_count(self) -> int:
        """Channels of the open device stream; 0 when closed."""
        return self._sink.format().channelCount() if self._sink is not None else 0

    def start(self, sample_rate: int) -> None:
        self.stop()
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise AudioError(MSG_NO_AUDIO)
        audio_format = QAudioFormat()
        audio_format.setSampleRate(sample_rate)
        audio_format.setChannelCount(_DEVICE_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        sink = QAudioSink(device, audio_format)
        sink.setBufferSize(
            sample_rate * _BYTES_PER_SAMPLE * _DEVICE_CHANNELS * _BUFFER_MS // 1000
        )
        io = sink.start()
        if io is None or sink.error() not in _HEALTHY:
            sink.stop()
            raise AudioError(MSG_NO_AUDIO)
        self._sink = sink
        self._io = io
        self._bytes_per_second = sample_rate * _BYTES_PER_SAMPLE
        self._ends_at = 0.0
        self._suspended_at = None

    def bytes_free(self) -> int:
        if self._sink is None:
            return 0
        if self._sink.error() not in _HEALTHY:
            raise AudioError(MSG_NO_AUDIO)
        free = self._sink.bytesFree() // _DEVICE_CHANNELS
        return free - free % _BYTES_PER_SAMPLE

    def write(self, data: bytes) -> int:
        if self._io is None or not data:
            return 0
        written = self._io.write(mono_to_stereo(data)) // _DEVICE_CHANNELS
        written -= written % _BYTES_PER_SAMPLE
        if written <= 0:
            return 0
        self._ends_at = (
            max(self._ends_at, time.monotonic()) + written / self._bytes_per_second
        )
        return written

    def suspend(self) -> None:
        if self._sink is not None and self._suspended_at is None:
            self._sink.suspend()
            self._suspended_at = time.monotonic()

    def resume(self) -> None:
        if self._sink is not None and self._suspended_at is not None:
            self._ends_at += time.monotonic() - self._suspended_at
            self._suspended_at = None
            self._sink.resume()

    def stop(self) -> None:
        if self._sink is not None:
            self._sink.stop()
        self._sink = None
        self._io = None

    def is_idle(self) -> bool:
        if self._sink is None:
            return True
        if self._suspended_at is not None:
            return False
        return time.monotonic() >= self._ends_at + _DRAIN_MARGIN_SECONDS
