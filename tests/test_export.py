import json
import math
import re
import shutil
import subprocess
import threading
from array import array

import pytest

from pagebard.core.errors import PagebardError
from pagebard.core.export import (
    MSG_EXPORT,
    MSG_NO_FFMPEG,
    ExportCancelled,
    ExportError,
    export_mp3,
)

RATE = 22050
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def tone(seconds=0.5, frequency=440.0):
    samples = array(
        "h",
        (int(12000 * math.sin(2 * math.pi * frequency * n / RATE)) for n in range(int(RATE * seconds))),
    )
    return samples.tobytes()


def speak(text):
    return tone()


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:format_tags=title:stream=codec_name,channels,sample_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)


def test_writes_a_playable_mp3(tmp_path):
    dest = tmp_path / "livro.mp3"
    export_mp3(["um", "dois", "três"], speak, RATE, dest, title="Meu livro")
    info = probe(dest)
    assert info["streams"][0]["codec_name"] == "mp3"
    assert info["streams"][0]["channels"] == 1
    assert abs(float(info["format"]["duration"]) - 1.5) < 0.3
    assert info["format"]["tags"]["title"] == "Meu livro"
    assert [p.name for p in tmp_path.iterdir()] == ["livro.mp3"]


def test_progress_per_sentence(tmp_path):
    calls = []
    export_mp3(["a", "b", "c"], speak, RATE, tmp_path / "x.mp3", progress=lambda d, t: calls.append((d, t)))
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_empty_audio_is_skipped(tmp_path):
    dest = tmp_path / "x.mp3"
    export_mp3(["a", "nada", "c"], lambda text: b"" if text == "nada" else tone(), RATE, dest)
    assert abs(float(probe(dest)["format"]["duration"]) - 1.0) < 0.3


def test_cancel_leaves_nothing(tmp_path):
    cancel = threading.Event()
    with pytest.raises(ExportCancelled):
        export_mp3(
            ["a", "b", "c"], speak, RATE, tmp_path / "x.mp3",
            progress=lambda done, total: cancel.set(), cancel=cancel,
        )  # fmt: skip
    assert list(tmp_path.iterdir()) == []


def test_existing_file_is_replaced_only_on_success(tmp_path):
    dest = tmp_path / "x.mp3"
    dest.write_bytes(b"antigo")

    def failing(text):
        if text == "b":
            raise PagebardError("A voz falhou.")
        return tone()

    with pytest.raises(PagebardError, match="A voz falhou."):
        export_mp3(["a", "b"], failing, RATE, dest)
    assert dest.read_bytes() == b"antigo"
    assert [p.name for p in tmp_path.iterdir()] == ["x.mp3"]

    export_mp3(["a"], speak, RATE, dest)
    assert probe(dest)["streams"][0]["codec_name"] == "mp3"


def test_missing_ffmpeg(tmp_path):
    with pytest.raises(ExportError, match=re.escape(MSG_NO_FFMPEG)):
        export_mp3(["a"], speak, RATE, tmp_path / "x.mp3", ffmpeg="/nao/existe/ffmpeg")
    assert list(tmp_path.iterdir()) == []


def test_ffmpeg_failure_is_reported(tmp_path):
    with pytest.raises(ExportError, match=re.escape(MSG_EXPORT)):
        export_mp3(["a", "b"], speak, RATE, tmp_path / "x.mp3", ffmpeg="false")
    assert list(tmp_path.iterdir()) == []


def test_unwritable_destination_is_reported(tmp_path):
    with pytest.raises(ExportError, match=re.escape(MSG_EXPORT)):
        export_mp3(["a"], speak, RATE, tmp_path / "pasta-que-nao-existe" / "x.mp3")


def test_nothing_to_say_is_an_error(tmp_path):
    with pytest.raises(ExportError, match=re.escape(MSG_EXPORT)):
        export_mp3(["a", "b"], lambda text: b"", RATE, tmp_path / "x.mp3")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ExportError, match=re.escape(MSG_EXPORT)):
        export_mp3([], speak, RATE, tmp_path / "x.mp3")
    assert list(tmp_path.iterdir()) == []


def test_file_gets_ordinary_permissions(tmp_path):
    import os
    import stat

    dest = tmp_path / "x.mp3"
    export_mp3(["a"], speak, RATE, dest)
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o666 & ~umask
