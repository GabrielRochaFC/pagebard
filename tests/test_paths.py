from pagebard.core import errors, paths


def test_data_dir_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / "pagebard"
    assert paths.data_dir().is_dir()


def test_data_dir_defaults_to_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / ".local/share/pagebard"


def test_voices_dir_is_created(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.voices_dir() == tmp_path / "pagebard/voices"
    assert paths.voices_dir().is_dir()


def test_user_message():
    assert errors.user_message(errors.PagebardError("Mensagem.")) == "Mensagem."
    assert (
        errors.user_message(ValueError("x"))
        == "Ocorreu um erro inesperado. Detalhe técnico: x"
    )
