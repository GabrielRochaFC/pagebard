import re
import threading
from pathlib import Path

import pytest

from leitorpdf.core.voices import (
    CATALOG_URL,
    HF_BASE,
    MSG_CATALOG,
    MSG_DOWNLOAD,
    CatalogVoice,
    DownloadCancelled,
    Voice,
    VoiceDownloadError,
    download_voice,
    fetch_catalog,
    installed_voices,
    language_label,
    parse_catalog,
    parse_key,
    quality_label,
    remove_voice,
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


def test_voice_label_in_portuguese():
    assert (
        Voice("pt_BR-faber-medium", Path("x.onnx")).label
        == "Faber · Português (Brasil) · média"
    )
    assert (
        Voice("en_US-hfc_female-x_low", Path("x.onnx")).label
        == "Hfc female · Inglês (EUA) · muito baixa"
    )
    assert Voice("sw_CD-lanfrica-high", Path("x.onnx")).label == "Lanfrica · sw_CD · alta"


def test_language_and_quality_labels():
    assert language_label("pt_BR") == "Português (Brasil)"
    assert language_label("pt_PT") == "Português (Portugal)"
    assert language_label("es_ES") == "Espanhol (Espanha)"
    assert language_label("xx_YY") == "xx_YY"
    assert [quality_label(q) for q in ("x_low", "low", "medium", "high", "ultra")] == [
        "muito baixa", "baixa", "média", "alta", "ultra",
    ]  # fmt: skip


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


def test_cancelled_attempt_that_wakes_up_late_does_not_touch_a_later_download(tmp_path):
    base = make_remote(tmp_path)
    dest = tmp_path / "voices"
    reading_started = threading.Event()
    release = threading.Event()

    class StalledResponse(FakeResponse):
        def read(self, size=-1):
            reading_started.set()
            release.wait(5.0)  # a dead connection: the read does not return
            return super().read(size)

    stalled = opener_with(lambda: StalledResponse([b"x" * 1000], length=5000))
    cancel = threading.Event()
    outcome = {}

    def first_attempt():
        try:
            download_voice(KEY, dest, cancel=cancel, opener=stalled)
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=first_attempt)
    thread.start()
    assert reading_started.wait(2.0)
    cancel.set()  # the user gave up on it...
    download_voice(KEY, dest, base_url=base)  # ...and tried again, successfully
    release.set()  # only now does the first attempt notice it was cancelled
    thread.join(2.0)

    assert isinstance(outcome["error"], DownloadCancelled)
    assert (dest / f"{KEY}.onnx").read_bytes() == ONNX
    assert sorted(p.name for p in dest.iterdir()) == [f"{KEY}.onnx", f"{KEY}.onnx.json"]
    assert [v.key for v in installed_voices(dest)] == [KEY]


def test_unexpected_exception_is_cleaned_up_and_reported(tmp_path):
    import http.client

    class BrokenResponse(FakeResponse):
        def read(self, size=-1):
            raise http.client.IncompleteRead(b"")

    dest = tmp_path / "voices"
    opener = opener_with(lambda: BrokenResponse([], length=10))
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_DOWNLOAD)):
        download_voice(KEY, dest, opener=opener)
    assert list(dest.iterdir()) == []


# ---- catalog ---------------------------------------------------------------------


def catalog_entry(key, size=1000):
    language, name, quality = key.split("-")
    return {
        "key": key,
        "name": name,
        "language": {"code": language},
        "quality": quality,
        "files": {f"x/{key}.onnx": {"size_bytes": size}, f"x/{key}.onnx.json": {"size_bytes": 24}},
    }


CATALOG = {
    key: catalog_entry(key, size)
    for key, size in [
        ("en_US-amy-low", 60_000_000),
        ("pt_BR-faber-medium", 63_221_984),
        ("pt_BR-cadu-medium", 63_000_000),
        ("de_DE-thorsten-high", 110_000_000),
    ]
}


def catalog_opener(payload):
    calls = []

    def opener(url):
        calls.append(url)
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse([payload], length=len(payload))

    opener.calls = calls
    return opener


def test_parse_catalog_orders_and_sizes():
    data = dict(CATALOG)
    data["quebrada"] = {"key": "quebrada"}  # malformed entries are skipped
    data["pt_BR-semarquivos-low"] = {"key": "pt_BR-semarquivos-low", "files": "?"}
    voices = parse_catalog(data)
    assert [v.key for v in voices] == [
        "pt_BR-cadu-medium",
        "pt_BR-faber-medium",
        "de_DE-thorsten-high",
        "en_US-amy-low",
    ]  # pt_BR first, then by language name in Portuguese: Alemão, Inglês
    faber = voices[1]
    assert faber == CatalogVoice("pt_BR-faber-medium", "pt_BR", "faber", "medium", 63_222_008)
    assert faber.label == "Faber · Português (Brasil) · média"


def test_fetch_catalog_writes_cache(tmp_path):
    import json

    cache = tmp_path / "dados" / "voices.json"
    opener = catalog_opener(json.dumps(CATALOG).encode())
    voices = fetch_catalog(cache, opener=opener)
    assert opener.calls == [CATALOG_URL]
    assert len(voices) == 4
    assert json.loads(cache.read_text()) == CATALOG
    assert [p.name for p in cache.parent.iterdir()] == ["voices.json"]


def test_fetch_catalog_falls_back_to_cache_when_offline(tmp_path):
    import json

    cache = tmp_path / "voices.json"
    fetch_catalog(cache, opener=catalog_opener(json.dumps(CATALOG).encode()))
    voices = fetch_catalog(cache, opener=catalog_opener(OSError("sem rede")))
    assert len(voices) == 4


def test_fetch_catalog_without_cache_reports_error(tmp_path):
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_CATALOG)):
        fetch_catalog(tmp_path / "voices.json", opener=catalog_opener(OSError("sem rede")))
    assert list(tmp_path.iterdir()) == []


def test_fetch_catalog_ignores_a_garbage_response(tmp_path):
    import json

    cache = tmp_path / "voices.json"
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_CATALOG)):
        fetch_catalog(cache, opener=catalog_opener(b"<html>erro do servidor</html>"))
    assert not cache.exists()
    fetch_catalog(cache, opener=catalog_opener(json.dumps(CATALOG).encode()))
    voices = fetch_catalog(cache, opener=catalog_opener(b"[1, 2, 3]"))  # valid JSON, wrong shape
    assert len(voices) == 4
    assert json.loads(cache.read_text()) == CATALOG  # the good copy was kept


def test_remove_voice(tmp_path):
    install(tmp_path, "pt_BR-a-medium")
    install(tmp_path, "pt_BR-b-medium")
    remove_voice("pt_BR-a-medium", tmp_path)
    assert [v.key for v in installed_voices(tmp_path)] == ["pt_BR-b-medium"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "pt_BR-b-medium.onnx",
        "pt_BR-b-medium.onnx.json",
    ]
    remove_voice("pt_BR-a-medium", tmp_path)  # already gone: fine
    remove_voice("pt_BR-nunca-medium", tmp_path / "nao-existe")


def test_fetch_catalog_survives_a_connection_closed_midway(tmp_path):
    import http.client
    import json

    class Dropped(FakeResponse):
        def read(self, size=-1):
            raise http.client.IncompleteRead(b"{")

    cache = tmp_path / "voices.json"
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_CATALOG)):
        fetch_catalog(cache, opener=lambda url: Dropped([]))
    fetch_catalog(cache, opener=catalog_opener(json.dumps(CATALOG).encode()))
    assert len(fetch_catalog(cache, opener=lambda url: Dropped([]))) == 4
