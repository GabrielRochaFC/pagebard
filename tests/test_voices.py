import re
import threading
from pathlib import Path

import pytest

from leitorpdf.core.voices import (
    HF_BASE,
    MSG_DOWNLOAD,
    DownloadCancelled,
    Voice,
    VoiceDownloadError,
    download_voice,
    installed_voices,
    parse_key,
    voice_urls,
)

KEY = "pt_BR-faber-medium"
ONNX = bytes(range(256)) * 800  # 204800 bytes: several 64 KiB chunks
CONFIG = b'{"audio": {"sample_rate": 22050}}'


def make_remote(tmp_path):
    """A local mirror of the Hugging Face layout, served through file:// URLs."""
    root = tmp_path / "remote"
    folder = root / "pt" / "pt_BR" / "faber" / "medium"
    folder.mkdir(parents=True)
    (folder / f"{KEY}.onnx").write_bytes(ONNX)
    (folder / f"{KEY}.onnx.json").write_bytes(CONFIG)
    return root.as_uri()


class FakeResponse:
    def __init__(self, chunks, length=None, fail_after=None):
        self._chunks = list(chunks)
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self._fail_after = fail_after
        self._reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if self._fail_after is not None and self._reads >= self._fail_after:
            raise OSError("connection reset")
        self._reads += 1
        return self._chunks.pop(0) if self._chunks else b""


def opener_with(onnx_response):
    def opener(url):
        if url.endswith(".json"):
            return FakeResponse([CONFIG], length=len(CONFIG))
        return onnx_response()

    return opener


def install(folder, key, onnx=b"model", config=b"{}"):
    if onnx is not None:
        (folder / f"{key}.onnx").write_bytes(onnx)
    if config is not None:
        (folder / f"{key}.onnx.json").write_bytes(config)


def test_parse_key():
    assert parse_key("pt_BR-faber-medium") == ("pt_BR", "faber", "medium")
    assert parse_key("en_GB-northern_english_male-medium") == (
        "en_GB",
        "northern_english_male",
        "medium",
    )
    assert parse_key("en_US-lessac-x_low") == ("en_US", "lessac", "x_low")
    for bad in ("", "faber", "pt_BR-faber", "ptBR-faber-medium"):
        with pytest.raises(ValueError):
            parse_key(bad)


def test_voice_label():
    assert Voice("pt_BR-faber-medium", Path("x.onnx")).label == "Faber · pt_BR · medium"
    assert (
        Voice("en_US-hfc_female-medium", Path("x.onnx")).label
        == "Hfc female · en_US · medium"
    )


def test_voice_urls():
    assert voice_urls("pt_BR-faber-medium") == (
        HF_BASE + "/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        HF_BASE + "/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
    )
    assert "tug%C3%A3o" in voice_urls("pt_PT-tugão-medium")[0]


def test_installed_voices_requires_both_files(tmp_path):
    install(tmp_path, "pt_BR-a-medium")
    install(tmp_path, "pt_BR-b-medium", config=None)
    install(tmp_path, "pt_BR-c-medium", onnx=None)
    (tmp_path / "pt_BR-c-medium.onnx.part").write_bytes(b"half")
    install(tmp_path, "pt_BR-d-medium", onnx=b"")
    install(tmp_path, "lixo")
    assert [v.key for v in installed_voices(tmp_path)] == ["pt_BR-a-medium"]
    assert installed_voices(tmp_path)[0].path == tmp_path / "pt_BR-a-medium.onnx"


def test_installed_voices_sorted(tmp_path):
    install(tmp_path, "pt_BR-faber-medium")
    install(tmp_path, "en_US-amy-low")
    assert [v.key for v in installed_voices(tmp_path)] == [
        "en_US-amy-low",
        "pt_BR-faber-medium",
    ]


def test_installed_voices_missing_directory(tmp_path):
    assert installed_voices(tmp_path / "nao-existe") == []


def test_download_from_file_url(tmp_path):
    base = make_remote(tmp_path)
    dest = tmp_path / "voices"
    calls = []
    voice = download_voice(
        KEY, dest, progress=lambda done, total: calls.append((done, total)), base_url=base
    )
    assert voice == Voice(KEY, dest / f"{KEY}.onnx")
    assert voice.path.read_bytes() == ONNX
    assert (dest / f"{KEY}.onnx.json").read_bytes() == CONFIG
    assert len(calls) > 1 and calls[-1] == (len(ONNX), len(ONNX))
    assert [done for done, _ in calls] == sorted(done for done, _ in calls)
    assert sorted(p.name for p in dest.iterdir()) == [f"{KEY}.onnx", f"{KEY}.onnx.json"]
    assert [v.key for v in installed_voices(dest)] == [KEY]


def test_network_error_mid_download_leaves_nothing(tmp_path):
    dest = tmp_path / "voices"
    opener = opener_with(lambda: FakeResponse([b"x" * 1000], length=5000, fail_after=1))
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_DOWNLOAD)):
        download_voice(KEY, dest, opener=opener)
    assert list(dest.iterdir()) == []
    assert installed_voices(dest) == []


def test_truncated_download_is_an_error(tmp_path):
    dest = tmp_path / "voices"
    opener = opener_with(lambda: FakeResponse([b"x" * 10], length=100))
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_DOWNLOAD)):
        download_voice(KEY, dest, opener=opener)
    assert list(dest.iterdir()) == []


def test_cancel_before_start_leaves_nothing(tmp_path):
    base = make_remote(tmp_path)
    dest = tmp_path / "voices"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        download_voice(KEY, dest, cancel=cancel, base_url=base)
    assert list(dest.iterdir()) == []


def test_cancel_mid_download_leaves_nothing(tmp_path):
    base = make_remote(tmp_path)
    dest = tmp_path / "voices"
    cancel = threading.Event()
    with pytest.raises(DownloadCancelled):
        download_voice(
            KEY, dest, progress=lambda done, total: cancel.set(), cancel=cancel, base_url=base
        )
    assert list(dest.iterdir()) == []


def test_retry_after_failure_succeeds(tmp_path):
    base = make_remote(tmp_path)
    dest = tmp_path / "voices"
    failing = opener_with(lambda: FakeResponse([b"x"], length=5000, fail_after=1))
    with pytest.raises(VoiceDownloadError):
        download_voice(KEY, dest, opener=failing)
    download_voice(KEY, dest, base_url=base)
    assert [v.key for v in installed_voices(dest)] == [KEY]


def test_already_installed_voice_is_not_downloaded_again(tmp_path):
    install(tmp_path, KEY)

    def opener(url):
        raise AssertionError("should not touch the network")

    assert download_voice(KEY, tmp_path, opener=opener) == Voice(KEY, tmp_path / f"{KEY}.onnx")
