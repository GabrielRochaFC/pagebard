"""Save the spoken text as an MP3 file, encoding with ffmpeg."""

import os
import subprocess
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from leitorpdf.core.errors import LeitorError

MSG_NO_FFMPEG = (
    "Para exportar em MP3 é preciso o programa ffmpeg, que não foi encontrado "
    "neste computador."
)
MSG_EXPORT = (
    "Não foi possível gravar o arquivo MP3. Verifique se há espaço em disco e "
    "se a pasta permite gravação."
)


# Temporary files are created private (0600); the finished MP3 should get the
# permissions any new file would. Read once: os.umask() can only be read by
# setting it, which is not safe to do from several threads.
_UMASK = os.umask(0)
os.umask(_UMASK)


class ExportError(LeitorError):
    pass


class ExportCancelled(Exception):
    pass


def export_mp3(
    texts: Sequence[str],
    synthesize: Callable[[str], bytes],
    sample_rate: int,
    dest: Path,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    title: str | None = None,
    ffmpeg: str = "ffmpeg",
) -> None:
    """Synthesize each text and encode the result to `dest`.

    The file only gets its final name when it is complete; a cancelled or
    failed export leaves nothing behind and keeps a previous file intact.
    """
    dest = Path(dest)
    try:
        handle, name = tempfile.mkstemp(dir=dest.parent, suffix=".mp3.part")
        os.close(handle)
    except OSError as exc:
        raise ExportError(MSG_EXPORT) from exc
    part = Path(name)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
        "-codec:a", "libmp3lame", "-q:a", "5",
    ]  # fmt: skip
    if title:
        command += ["-metadata", f"title={title}"]
    command += ["-f", "mp3", "-y", str(part)]

    encoder = None
    try:
        try:
            encoder = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ExportError(MSG_NO_FFMPEG) from exc
        wrote_audio = False
        for index, text in enumerate(texts):
            if cancel is not None and cancel.is_set():
                raise ExportCancelled()
            audio = synthesize(text)
            if audio:
                encoder.stdin.write(audio)
                wrote_audio = True
            if progress is not None:
                progress(index + 1, len(texts))
        encoder.stdin.close()
        if encoder.wait() != 0 or not wrote_audio:
            raise ExportError(MSG_EXPORT)
        os.chmod(part, 0o666 & ~_UMASK)
        os.replace(part, dest)
    except OSError as exc:  # the encoder died, or the disk is full
        _abandon(encoder, part)
        raise ExportError(MSG_EXPORT) from exc
    except BaseException:
        _abandon(encoder, part)
        raise


def _abandon(encoder: subprocess.Popen | None, part: Path) -> None:
    if encoder is not None:
        if encoder.poll() is None:
            encoder.kill()
        try:
            encoder.stdin.close()
        except OSError:
            pass
        encoder.wait()
    part.unlink(missing_ok=True)
