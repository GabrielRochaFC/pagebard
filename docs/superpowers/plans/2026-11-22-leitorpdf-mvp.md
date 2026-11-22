# LeitorPDF MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App desktop que abre um PDF, deixa escolher uma voz Piper instalada (baixando a voz padrão no primeiro uso) e lê o texto em voz alta com play/pause.

**Architecture:** `core/` (sem Qt) extrai texto, divide em frases, gerencia vozes e sintetiza PCM. `playback/` tem uma thread que sintetiza frases à frente numa fila limitada e um `Player` que empurra o áudio para um `QAudioSink`. `ui/` é uma janela PySide6 que liga tudo; trabalho lento roda fora da thread da interface.

**Tech Stack:** Python 3.14 (mínimo 3.11), PySide6 6.12 (QtWidgets + QtMultimedia), PyMuPDF 2.1, piper-tts 1.8, pytest 9.

**Spec:** `docs/superpowers/specs/2026-11-22-leitorpdf-design.md` (este plano cobre as fases 0 e 1).

## Global Constraints

- Dependências de runtime: somente `PySide6`, `PyMuPDF`, `piper-tts`. Dev: `pytest`.
- `src/leitorpdf/core/` não importa PySide6.
- Todo texto visível ao usuário em pt-BR. Identificadores e comentários em inglês.
- Nada bloqueia a thread da interface: carregar PDF, baixar voz e sintetizar rodam em outra thread.
- Só CPU: `PiperVoice.load(..., use_cuda=False)`.
- Dados do usuário em `$XDG_DATA_HOME/leitorpdf/` (padrão `~/.local/share/leitorpdf/`); vozes em `voices/`.
- Voz padrão: `pt_BR-faber-medium`.
- Licença: AGPL-3.0-or-later.
- Áudio interno: PCM 16-bit little-endian mono, na taxa da voz (22050 Hz nas vozes medium).
- Rodar testes com `.venv/bin/python -m pytest`; os testes de UI usam `QT_QPA_PLATFORM=offscreen` (definido em `tests/conftest.py`).

## Review Focus

1. PDF escaneado / sem texto → aviso claro e Reproduzir desabilitado, sem travar. (Tasks 2 e 8)
2. Texto longo sem pontuação (tabelas, listas) → blocos de no máximo 300 caracteres, para o áudio começar logo. (Task 3)
3. Internet cai ou usuário cancela no meio do download → nenhuma voz "meio baixada" aparece como instalada; dá para tentar de novo. (Task 4)
4. Abrir outro PDF, trocar de voz ou apertar Reproduzir/Pausar em sequência durante a leitura → sem áudio sobreposto, sem travar. (Tasks 7 e 8)
5. Trecho sem nada pronunciável (só símbolos) ou áudio vazio → é pulado; a leitura não trava. (Tasks 3 e 6)

---

## Estrutura de arquivos

```
pyproject.toml  .gitignore  LICENSE  README.md
src/leitorpdf/
  __init__.py  __main__.py  app.py
  core/    __init__.py errors.py paths.py pdf.py segmenter.py voices.py tts.py
  playback/ __init__.py synth_worker.py audio_out.py player.py
  ui/      __init__.py tasks.py messages.py voice_download.py main_window.py
tests/
  conftest.py test_paths.py test_pdf.py test_segmenter.py test_voices.py
  test_tts.py test_synth_worker.py test_player.py test_main_window.py
```

---

### Task 1: Esqueleto do projeto, erros e caminhos

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md`, `src/leitorpdf/__init__.py`, `src/leitorpdf/core/__init__.py`, `src/leitorpdf/core/errors.py`, `src/leitorpdf/core/paths.py`, `tests/conftest.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces:
  - `errors.LeitorError(Exception)` — `str(e)` é a mensagem pt-BR para o usuário.
  - `errors.user_message(exc: BaseException) -> str` — `str(exc)` se `LeitorError`; senão `"Ocorreu um erro inesperado. Detalhe técnico: {exc}"`.
  - `paths.data_dir() -> Path`, `paths.voices_dir() -> Path` — criam o diretório se faltar.
  - `tests/conftest.py`: define `QT_QPA_PLATFORM=offscreen` antes de qualquer import de Qt; fixture `qapp` (QApplication única por sessão); fixture `make_pdf(pages: list[str], name="doc.pdf") -> Path` que gera um PDF em `tmp_path` com PyMuPDF (`insert_text` por página; página com `""` fica em branco).

- [ ] **Step 1: `pyproject.toml`** — backend `setuptools>=77`, layout `src/`, `name="leitorpdf"`, `version="0.1.0"`, `requires-python=">=3.11"`, `license="AGPL-3.0-or-later"`, dependencies `PySide6>=6.8`, `PyMuPDF>=1.26`, `piper-tts>=1.3`; extra `dev = ["pytest>=8"]`; `[project.gui-scripts] leitorpdf = "leitorpdf.app:main"`; `[tool.pytest.ini_options] testpaths = ["tests"]`.
- [ ] **Step 2: `.gitignore`** (`.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `build/`, `dist/`, `.flatpak-builder/`, `*.flatpak`), **`LICENSE`** (texto oficial AGPL-3.0 de `https://www.gnu.org/licenses/agpl-3.0.txt`), **`README.md`** (nome, uma frase, como rodar em desenvolvimento: criar venv, `pip install -e ".[dev]"`, `python -m leitorpdf`).
- [ ] **Step 3: Write failing tests** in `tests/test_paths.py`

```python
def test_data_dir_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / "leitorpdf"
    assert paths.data_dir().is_dir()

def test_data_dir_defaults_to_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / ".local/share/leitorpdf"

def test_voices_dir_is_created(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.voices_dir() == tmp_path / "leitorpdf/voices"
    assert paths.voices_dir().is_dir()

def test_user_message():
    assert errors.user_message(errors.LeitorError("Mensagem.")) == "Mensagem."
    assert errors.user_message(ValueError("x")) == "Ocorreu um erro inesperado. Detalhe técnico: x"
```

- [ ] **Step 4: Run** `.venv/bin/python -m pip install -e ".[dev]" && .venv/bin/python -m pytest tests/test_paths.py -v` → FAIL (módulos não existem).
- [ ] **Step 5: Implement** `errors.py`, `paths.py`, `conftest.py`.
- [ ] **Step 6: Run** the same pytest command → 4 passed.
- [ ] **Step 7: Commit** `chore: project skeleton, errors and data paths`

---

### Task 2: Extração de texto do PDF

**Files:**
- Create: `src/leitorpdf/core/pdf.py`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Consumes: `errors.LeitorError`; fixture `make_pdf`.
- Produces:
  - `pdf.PdfError(LeitorError)`
  - `pdf.MSG_NOT_FOUND = "Não foi possível abrir o arquivo. Verifique se ele ainda existe e se você tem permissão para lê-lo."`
  - `pdf.MSG_INVALID = "Este arquivo não é um PDF válido ou está danificado."`
  - `pdf.MSG_PASSWORD = "Este PDF é protegido por senha. Ainda não é possível abrir PDFs com senha."`
  - `@dataclass(frozen=True) PdfText(path: Path, pages: tuple[str, ...])` com `has_text: bool` (alguma página não vazia).
  - `pdf.load_pdf(path: str | Path) -> PdfText`

Regras do texto de cada página: blocos de texto na ordem de leitura (`page.get_text("blocks", sort=True)`, ignorar blocos de imagem); em cada bloco, juntar palavra hifenizada no fim da linha (`(?<=\w)-\n(?=\w)` → vazio) e reduzir todo espaço em branco a um espaço; blocos unidos por `"\n\n"`; ligaduras (`ﬁ`, `ﬂ`) expandidas. Página sem texto → `""`.

- [ ] **Step 1: Write failing tests**

```python
def test_pages_in_order(make_pdf):
    doc = load_pdf(make_pdf(["Primeira página.", "Segunda página."]))
    assert doc.pages == ("Primeira página.", "Segunda página.")
    assert doc.has_text

def test_line_breaks_inside_paragraph_become_spaces(make_pdf):
    doc = load_pdf(make_pdf(["Uma frase que\ncontinua na linha de baixo."]))
    assert doc.pages[0] == "Uma frase que continua na linha de baixo."

def test_hyphenated_line_end_is_rejoined(make_pdf):
    doc = load_pdf(make_pdf(["Este é um exem-\nplo simples."]))
    assert doc.pages[0] == "Este é um exemplo simples."

def test_separate_blocks_become_paragraphs(tmp_path):
    # two insert_text calls far apart vertically (y=100 and y=400) on one page
    assert load_pdf(path).pages[0] == "Título\n\nCorpo do texto."

def test_blank_pdf_has_no_text(make_pdf):
    doc = load_pdf(make_pdf(["", ""]))
    assert doc.pages == ("", "") and not doc.has_text

def test_missing_file(tmp_path):
    with pytest.raises(PdfError, match=re.escape(MSG_NOT_FOUND)): load_pdf(tmp_path / "nao-existe.pdf")

def test_garbage_with_pdf_extension(tmp_path):   # bytes b"isto nao e um pdf"
    with pytest.raises(PdfError, match=re.escape(MSG_INVALID)): load_pdf(p)

def test_non_pdf_document_is_rejected(tmp_path):  # "nota.txt" with plain text
    with pytest.raises(PdfError, match=re.escape(MSG_INVALID)): load_pdf(p)

def test_password_protected(tmp_path):  # saved with encryption=PDF_ENCRYPT_AES_256, user_pw="x"
    with pytest.raises(PdfError, match=re.escape(MSG_PASSWORD)): load_pdf(p)
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_pdf.py -v` → FAIL.
- [ ] **Step 3: Implement** `load_pdf`. Arquivo inexistente/ilegível → `MSG_NOT_FOUND` (checar antes de abrir); exceção do PyMuPDF ao abrir ou `not doc.is_pdf` → `MSG_INVALID`; `doc.needs_pass` → `MSG_PASSWORD`. Fechar o documento sempre.
- [ ] **Step 4: Run** → 9 passed.
- [ ] **Step 5: Commit** `feat: extract normalized text from PDF pages`

---

### Task 3: Divisão em frases

**Files:**
- Create: `src/leitorpdf/core/segmenter.py`
- Test: `tests/test_segmenter.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Sentence(text: str, start: int, end: int)` — `source[start:end] == text`.
  - `segmenter.MAX_SENTENCE_CHARS = 300`
  - `segmenter.split_sentences(text: str) -> list[Sentence]`

Regras:
1. Quebra de parágrafo (`\n\n+`) sempre encerra a frase.
2. Dentro do parágrafo, a frase termina depois de `[.!?…]+` seguido de fechamentos opcionais (`"'”’)]»`), quando depois vem espaço e então letra maiúscula, dígito ou abertura (`"'“‘([«—`), ou o fim do parágrafo.
3. Não quebra se a palavra antes do ponto for abreviação (sem diferenciar maiúsculas): `sr sra srta dr dra prof profa av art cap ed etc ex fig nº núm pág pp tel vol vs exmo ltda cia` ou uma única letra (iniciais como "J. K.").
4. Pedaço maior que `MAX_SENTENCE_CHARS`: cortar no último `,` `;` ou `:` seguido de espaço antes do limite; se não houver, no último espaço; se não houver, no limite. Repetir.
5. Aparar espaços; descartar pedaços sem nenhum caractere alfanumérico.

- [ ] **Step 1: Write failing tests**

```python
def texts(s): return [x.text for x in split_sentences(s)]

def test_basic():            assert texts("Olá mundo. Tudo bem? Sim!") == ["Olá mundo.", "Tudo bem?", "Sim!"]
def test_abbreviation():     assert texts("O Sr. Silva chegou. Ele sorriu.") == ["O Sr. Silva chegou.", "Ele sorriu."]
def test_initials():         assert texts("J. K. Rowling escreveu. Fim.") == ["J. K. Rowling escreveu.", "Fim."]
def test_decimal():          assert texts("O valor é 3.14 metros. Certo.") == ["O valor é 3.14 metros.", "Certo."]
def test_closing_quote():    assert texts('Ele disse: "Vamos." Depois saiu.') == ['Ele disse: "Vamos."', "Depois saiu."]
def test_lowercase_after_period_does_not_split():
    assert texts("Veja a pág. 3 do livro. Fim.") == ["Veja a pág. 3 do livro.", "Fim."]
def test_paragraphs_split_without_punctuation():
    assert texts("Título\n\nPrimeiro parágrafo sem ponto\n\nSegundo.") == ["Título", "Primeiro parágrafo sem ponto", "Segundo."]
def test_offsets_match_source():
    src = "  Olá mundo.  Tudo bem?\n\nSim!  "
    out = split_sentences(src)
    assert all(src[s.start:s.end] == s.text for s in out)
    assert [s.start for s in out] == sorted({s.start for s in out})
def test_long_text_with_commas_is_capped():
    src = "palavra, " * 100
    out = split_sentences(src)
    assert len(out) > 1 and all(len(s.text) <= 300 for s in out)
    assert "".join("".join(s.text.split()) for s in out) == "".join(src.split())
def test_long_text_without_spaces_is_capped():
    out = split_sentences("a" * 1000)
    assert all(len(s.text) <= 300 for s in out) and sum(len(s.text) for s in out) == 1000
def test_empty():            assert texts("") == [] and texts("   \n\n ") == []
def test_symbol_only_pieces_are_dropped():
    assert texts("*** --- ...\n\nTexto.") == ["Texto."]
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_segmenter.py -v` → FAIL.
- [ ] **Step 3: Implement** `split_sentences`.
- [ ] **Step 4: Run** → 12 passed.
- [ ] **Step 5: Commit** `feat: sentence segmentation with offsets`

---

### Task 4: Vozes instaladas e download da voz

**Files:**
- Create: `src/leitorpdf/core/voices.py`
- Test: `tests/test_voices.py`

**Interfaces:**
- Consumes: `errors.LeitorError`.
- Produces:
  - `voices.HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"`
  - `voices.DEFAULT_VOICE_KEY = "pt_BR-faber-medium"`
  - `voices.MSG_DOWNLOAD = "Não foi possível baixar a voz. Verifique sua conexão com a internet e tente novamente."`
  - `voices.VoiceDownloadError(LeitorError)`, `voices.DownloadCancelled(Exception)`
  - `voices.parse_key(key: str) -> tuple[str, str, str]` — `(language, name, quality)`; `ValueError` se malformada.
  - `@dataclass(frozen=True) Voice(key: str, path: Path)` — `path` é o `.onnx`; propriedades `language`, `name`, `quality`, `label` (`"Faber · pt_BR · medium"`: nome com inicial maiúscula e `_` → espaço).
  - `voices.voice_urls(key: str, base_url: str = HF_BASE) -> tuple[str, str]` — `(.onnx, .onnx.json)`; caminho `{lang[:2]}/{language}/{name}/{quality}/{key}.onnx`, percent-encoded.
  - `voices.installed_voices(voices_dir: Path) -> list[Voice]` — ordenado por `key`; só conta se `.onnx` e `.onnx.json` existem e não estão vazios e a chave é válida.
  - `voices.download_voice(key, voices_dir, progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None, opener: Callable[[str], Any] = urllib.request.urlopen, base_url: str = HF_BASE) -> Voice`

Regras do download: baixa o `.json` e depois o `.onnx`, cada um para `<arquivo>.part`, em blocos de 64 KiB, renomeando ao terminar (o `.onnx` por último). `progress(done, total)` reporta os bytes do `.onnx` (`total` vem do `Content-Length`, 0 se ausente) e é chamado ao final com `done == total`. `cancel` setado → apaga os `.part` e o `.json` recém-baixado, levanta `DownloadCancelled`. `OSError` (inclui `URLError`/`HTTPError`) ou menos bytes que o `Content-Length` → mesma limpeza, levanta `VoiceDownloadError(MSG_DOWNLOAD)`.

- [ ] **Step 1: Write failing tests**

```python
def test_parse_key():
    assert parse_key("pt_BR-faber-medium") == ("pt_BR", "faber", "medium")
    assert parse_key("en_GB-northern_english_male-medium") == ("en_GB", "northern_english_male", "medium")
    for bad in ("", "faber", "pt_BR-faber", "ptBR-faber-medium"):
        with pytest.raises(ValueError): parse_key(bad)

def test_voice_label():
    assert Voice("pt_BR-faber-medium", Path("x.onnx")).label == "Faber · pt_BR · medium"
    assert Voice("en_US-hfc_female-medium", Path("x.onnx")).label == "Hfc female · en_US · medium"

def test_voice_urls():
    assert voice_urls("pt_BR-faber-medium") == (
        HF_BASE + "/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        HF_BASE + "/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json")
    assert "tug%C3%A3o" in voice_urls("pt_PT-tugão-medium")[0]

def test_installed_voices_requires_both_files(tmp_path):
    # a: onnx+json ok | b: onnx only | c: onnx.part+json | d: empty onnx + json | "lixo.onnx"+json (bad key)
    assert [v.key for v in installed_voices(tmp_path)] == ["pt_BR-a-medium"]

def test_installed_voices_sorted(tmp_path): ...   # two valid voices → keys sorted

def test_download_from_file_url(tmp_path):
    # src tree under tmp_path/"remote" mirroring the HF layout; base_url = (tmp_path/"remote").as_uri()
    calls = []
    v = download_voice(KEY, dest, progress=lambda d, t: calls.append((d, t)), base_url=base)
    assert v.path.read_bytes() == onnx_bytes and (dest / f"{KEY}.onnx.json").exists()
    assert calls[-1] == (len(onnx_bytes), len(onnx_bytes))
    assert [x.key for x in installed_voices(dest)] == [KEY]

def test_network_error_mid_download_leaves_nothing(tmp_path):
    # fake opener: json ok; onnx stream yields one chunk then raises OSError
    with pytest.raises(VoiceDownloadError, match=re.escape(MSG_DOWNLOAD)): download_voice(KEY, dest, opener=fake)
    assert list(dest.iterdir()) == [] and installed_voices(dest) == []

def test_truncated_download_is_an_error(tmp_path):
    # fake opener: Content-Length 100, stream ends after 10 bytes
    with pytest.raises(VoiceDownloadError): download_voice(KEY, dest, opener=fake)
    assert list(dest.iterdir()) == []

def test_cancel_leaves_nothing(tmp_path):
    ev = threading.Event(); ev.set()
    with pytest.raises(DownloadCancelled): download_voice(KEY, dest, cancel=ev, base_url=base)
    assert list(dest.iterdir()) == []

def test_retry_after_failure_succeeds(tmp_path): ...   # failing opener, then real file:// download → installed
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_voices.py -v` → FAIL.
- [ ] **Step 3: Implement** `voices.py`. O objeto devolvido por `opener(url)` é usado como context manager com `.read(n)` e `.headers.get("Content-Length")`.
- [ ] **Step 4: Run** → 10 passed.
- [ ] **Step 5: Commit** `feat: installed voices and voice download`

---

### Task 5: Síntese com Piper

**Files:**
- Create: `src/leitorpdf/core/tts.py`
- Test: `tests/test_tts.py`

**Interfaces:**
- Consumes: `errors.LeitorError`, `paths.voices_dir`, `voices.DEFAULT_VOICE_KEY`.
- Produces:
  - `tts.MSG_TTS = "Não foi possível gerar a fala com esta voz. Tente baixar a voz novamente."`
  - `tts.TtsError(LeitorError)`
  - `tts.Synthesizer(model_path: Path)` com:
    - `sample_rate: int` — lido de `<model>.json` → `["audio"]["sample_rate"]`, sem carregar o modelo; JSON ausente/inválido → `TtsError(MSG_TTS)`.
    - `synthesize(text: str, length_scale: float = 1.0) -> bytes` — PCM s16le mono; `b""` se o Piper não produzir áudio. Carrega o modelo na primeira chamada (`PiperVoice.load(model_path, use_cuda=False)`), usa `SynthesisConfig(length_scale=...)` e concatena `chunk.audio_int16_bytes`. Qualquer exceção de carga ou síntese → `TtsError(MSG_TTS)` encadeada.

- [ ] **Step 1: Write failing tests**

```python
REAL = paths.voices_dir() / f"{DEFAULT_VOICE_KEY}.onnx"   # resolved before any monkeypatch
needs_voice = pytest.mark.skipif(not REAL.exists(), reason="default voice not installed")

def test_sample_rate_read_without_loading_model(tmp_path):
    # x.onnx = b"lixo", x.onnx.json = {"audio": {"sample_rate": 22050}}
    assert Synthesizer(model).sample_rate == 22050

def test_missing_config_is_tts_error(tmp_path):
    with pytest.raises(TtsError, match=re.escape(MSG_TTS)): Synthesizer(tmp_path / "x.onnx").sample_rate

def test_corrupt_model_is_tts_error(tmp_path):
    with pytest.raises(TtsError, match=re.escape(MSG_TTS)): Synthesizer(model).synthesize("Olá.")

@needs_voice
def test_synthesizes_speech():
    s = Synthesizer(REAL); pcm = s.synthesize("Olá, mundo.")
    assert len(pcm) % 2 == 0 and len(pcm) > s.sample_rate          # > 0.5 s

@needs_voice
def test_length_scale_changes_duration():
    s = Synthesizer(REAL); t = "Esta frase serve para medir a duração."
    assert len(s.synthesize(t, length_scale=0.6)) < len(s.synthesize(t, length_scale=1.0))

@needs_voice
def test_unpronounceable_text_does_not_raise():
    assert isinstance(Synthesizer(REAL).synthesize("***"), bytes)
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_tts.py -v` → FAIL.
- [ ] **Step 3: Implement** `tts.py`.
- [ ] **Step 4: Run** → 6 passed (nenhum skip nesta máquina: a voz padrão já está em `~/.local/share/leitorpdf/voices/`).
- [ ] **Step 5: Commit** `feat: Piper synthesizer wrapper`

---

### Task 6: Thread de síntese à frente

**Files:**
- Create: `src/leitorpdf/playback/__init__.py`, `src/leitorpdf/playback/synth_worker.py`
- Test: `tests/test_synth_worker.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) SynthItem(index: int, audio: bytes)`
  - `@dataclass(frozen=True) SynthFailed(index: int, error: Exception)`
  - `@dataclass(frozen=True) SynthEnd()`
  - `SynthWorker(synthesize: Callable[[str], bytes], sentences: Sequence[str], start: int = 0, lookahead: int = 3)` com:
    - `start() -> None` — inicia thread daemon.
    - `poll() -> SynthItem | SynthFailed | SynthEnd | None` — não bloqueia; `None` = nada pronto ainda. Depois de `SynthEnd` ou de `stop()`, sempre devolve `SynthEnd()`.
    - `stop() -> None` — encerra mesmo se a thread estiver bloqueada na fila cheia; retorna em até 1 s após a síntese em curso terminar.
    - `is_alive() -> bool`

Comportamento: sintetiza `sentences[start:]` em ordem para uma `queue.Queue(maxsize=lookahead)`; áudio `b""` é pulado; exceção em `synthesize` → enfileira `SynthFailed` e encerra; ao acabar, enfileira `SynthEnd`.

- [ ] **Step 1: Write failing tests** (helper `drain(worker, timeout=2.0) -> list` faz `poll()` até `SynthEnd`, incluindo-o)

```python
def test_delivers_in_order_then_end():
    w = SynthWorker(lambda t: t.encode(), ["a", "b", "c"]); w.start()
    assert drain(w) == [SynthItem(0, b"a"), SynthItem(1, b"b"), SynthItem(2, b"c"), SynthEnd()]

def test_start_index():      # start=1 → items 1, 2, end
def test_poll_before_anything_is_ready_returns_none():   # synth blocked on an Event → poll() is None

def test_backpressure():
    calls = []; w = SynthWorker(lambda t: calls.append(t) or b"x", ["s"] * 20, lookahead=2); w.start()
    time.sleep(0.2); assert len(calls) <= 3      # 2 queued + 1 waiting to enqueue
    w.stop()

def test_stop_while_queue_is_full():
    # as above; w.stop(); wait ≤ 1 s → not w.is_alive(); w.poll() == SynthEnd()

def test_failure_is_delivered_and_ends():
    # synth raises RuntimeError("boom") for "b" → [SynthItem(0, b"a"), SynthFailed(1, <that error>), SynthEnd()]; thread dead

def test_empty_audio_is_skipped():
    # synth returns b"" for "b" → [SynthItem(0, b"a"), SynthItem(2, b"c"), SynthEnd()]

def test_empty_sentence_list():   # → [SynthEnd()]
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_synth_worker.py -v` → FAIL.
- [ ] **Step 3: Implement** `synth_worker.py` (`put` com timeout curto em loop, checando o evento de parada).
- [ ] **Step 4: Run** → 8 passed.
- [ ] **Step 5: Commit** `feat: look-ahead synthesis worker`

---

### Task 7: Player

**Files:**
- Create: `src/leitorpdf/playback/audio_out.py`, `src/leitorpdf/playback/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: `SynthWorker`, `SynthItem`, `SynthFailed`, `SynthEnd`, `errors.LeitorError`, `errors.user_message`.
- Produces:
  - `audio_out.MSG_NO_AUDIO = "Nenhuma saída de áudio foi encontrada. Conecte alto-falantes ou fones de ouvido e tente novamente."`
  - `audio_out.AudioError(LeitorError)`
  - `audio_out.AudioOut` (Protocol): `start(sample_rate: int) -> None`, `bytes_free() -> int`, `write(data: bytes) -> int`, `suspend() -> None`, `resume() -> None`, `stop() -> None`, `is_idle() -> bool` (tudo que foi escrito já tocou).
  - `audio_out.QtAudioOut` — implementa com `QAudioSink` em modo push: formato Int16/mono/`sample_rate`, buffer de ~200 ms; sem dispositivo padrão → `AudioError(MSG_NO_AUDIO)`.
  - `player.PlayerState(Enum)`: `STOPPED`, `LOADING`, `PLAYING`, `PAUSED`
  - `player.Player(audio_out: AudioOut | None = None, parent: QObject | None = None)` (QObject) com:
    - sinais `state_changed(object)`, `sentence_started(int)`, `finished()`, `error(str)`
    - `state: PlayerState`
    - `play(synthesize: Callable[[str], bytes], sample_rate: int, sentences: Sequence[str], start: int = 0) -> None`
    - `pause()`, `resume()`, `stop()`, `tick()`

Comportamento:
- `play`: para o que estiver tocando, cria e inicia um `SynthWorker`, chama `audio_out.start(sample_rate)`, estado `LOADING`, liga um `QTimer` de 20 ms em `tick`. `LeitorError` em `start` → `stop()` + `error(str(e))`.
- `tick` (ignora se `STOPPED`/`PAUSED`): se não há áudio pendente, `worker.poll()` — `SynthItem` → vira o pendente, emite `sentence_started(index)`, estado `PLAYING`; `SynthFailed` → `stop()` + `error(user_message(e))`; `SynthEnd` → quando `audio_out.is_idle()`, `stop()` + `finished()`. Depois escreve do pendente no máximo `bytes_free()` bytes.
- `pause`: só de `PLAYING`/`LOADING` → `audio_out.suspend()`, `PAUSED`. `resume`: só de `PAUSED` → `audio_out.resume()`, volta para `PLAYING` (ou `LOADING` se nada tocou ainda).
- `stop`: para timer, worker e `audio_out`, descarta pendente, `STOPPED`. Sem efeito se já `STOPPED`.
- `state_changed` só é emitido quando o estado muda.

- [ ] **Step 1: Write failing tests** — `FakeAudioOut` (registra `written: bytearray`, `started_rates: list[int]`, flags `suspended`/`stopped`, `free: int` configurável, `idle: bool` configurável); helper `run(player, until, timeout=2.0)` chama `player.tick()` + `time.sleep(0.002)` até `until()`.

```python
def test_plays_all_sentences_in_order(qapp):
    # synth = lambda t: t.encode()*4 ; sentences ["aa","bb","cc"]; record signals
    # after run(until finished): started == [0, 1, 2]; out.written == b"aaaaaaaa"+b"bbbbbbbb"+b"cccccccc"
    # states == [LOADING, PLAYING, STOPPED]; finished emitted exactly once; out.stopped; out.started_rates == [22050]

def test_respects_bytes_free(qapp):
    # out.free = 10; one 25-byte sentence → after first data tick len(out.written) == 10; needs ≥ 3 ticks to reach 25

def test_pause_and_resume(qapp):
    # run until PLAYING; pause() → state PAUSED, out.suspended; n = len(out.written); 10 ticks → len unchanged
    # resume() → not out.suspended, state PLAYING; run until finished → all bytes written

def test_does_not_finish_while_audio_still_playing(qapp):
    # out.idle = False; run 50 ticks after all written → finished not emitted, state PLAYING; out.idle = True; tick → finished

def test_synthesis_failure_reports_error(qapp):
    # synth raises LeitorError("Falhou.") → error emitted == ["Falhou."]; state STOPPED; finished not emitted

def test_audio_device_error_reports_error(qapp):
    # out.start raises AudioError(MSG_NO_AUDIO) → error == [MSG_NO_AUDIO]; state STOPPED

def test_play_while_playing_restarts_cleanly(qapp):
    # play(["x"*8]*50, slow consumption: out.free=2); run until PLAYING; grab old = player._worker
    # play(synth, 22050, ["yy"], start=0); out.written.clear() happens in FakeAudioOut.start
    # run until finished → not old.is_alive(); out.written == b"yy"*4; no b"x" in out.written

def test_start_index_is_forwarded(qapp):     # start=2 → sentence_started first emits 2
def test_stop_and_pause_when_stopped_are_noops(qapp):   # no signals, no exceptions
def test_rapid_toggle(qapp):
    # 100× alternating pause()/resume() with a tick between → no exception; then run until finished → all bytes written once
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_player.py -v` → FAIL.
- [ ] **Step 3: Implement** `audio_out.py` and `player.py`.
- [ ] **Step 4: Run** → 10 passed.
- [ ] **Step 5: Real-device check (volume 0).** Script descartável no scratchpad: `QtAudioOut` + `Player` + `Synthesizer` real, volume do sink em 0, duas frases, `QCoreApplication.exec()` até `finished`. Esperado: `sentence_started` 0 e 1, `finished` em tempo próximo à duração do áudio (± 1 s), sem avisos do Qt.
- [ ] **Step 6: Commit** `feat: audio player with pause/resume`

---

### Task 8: Janela principal e ponto de entrada

**Files:**
- Create: `src/leitorpdf/ui/__init__.py`, `src/leitorpdf/ui/tasks.py`, `src/leitorpdf/ui/messages.py`, `src/leitorpdf/ui/voice_download.py`, `src/leitorpdf/ui/main_window.py`, `src/leitorpdf/app.py`, `src/leitorpdf/__main__.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: tudo das Tasks 1–7.
- Produces:
  - `tasks.run_async(fn: Callable[[], T], on_done: Callable[[T], None], on_error: Callable[[Exception], None]) -> None` — roda `fn` no `QThreadPool` global; callbacks na thread da interface.
  - `messages.show_error(parent: QWidget | None, text: str) -> None` — `QMessageBox.warning`, título `"LeitorPDF"`.
  - `messages.MSG_NO_TEXT = "Este PDF não tem texto para ler — parece ser um documento escaneado. O reconhecimento de texto (OCR) ainda não está disponível."`
  - `messages.MSG_NEED_VOICE = "Para ler em voz alta é preciso baixar uma voz (63 MB, só na primeira vez). Baixar agora?"`
  - `voice_download.download_default_voice(parent: QWidget, voices_dir: Path) -> Voice | None` — `QProgressDialog` modal ("Baixando voz…", botão "Cancelar") com `download_voice` em thread; devolve a `Voice`, ou `None` se cancelado ou com erro (erro já exibido com `show_error`).
  - `main_window.MainWindow(player: Player | None = None, voices_dir: Path | None = None, notify: Callable[[str], None] | None = None, synth_factory: Callable[[Voice], Any] | None = None, offer_download: bool = True)`
    - widgets públicos: `open_button`, `voice_combo`, `play_button`, `text_view`
    - `open_path(path: str | Path) -> None` — carrega em segundo plano.
    - `notify` padrão = `show_error(self, text)`; `synth_factory` padrão = `lambda v: Synthesizer(v.path)` (objeto com `.sample_rate` e `.synthesize(text)`), reutilizado enquanto a voz não mudar.
  - `app.main() -> int`; `python -m leitorpdf` chama `app.main()`.

Comportamento da janela:
- Título `"LeitorPDF"`, tamanho inicial 900×650. Linha superior: `open_button` "Abrir PDF…" (Ctrl+O), rótulo "Voz:", `voice_combo` (um item por voz instalada, texto `Voice.label`), `play_button` (Espaço). Centro: `text_view` (`QPlainTextEdit` somente leitura, fonte 13 pt, placeholder "Abra um PDF para começar (Ctrl+O)."). Barra de status embaixo.
- `open_path`: para a leitura; status "Abrindo PDF…"; `load_pdf` via `run_async`. Sucesso com texto → `text_view` recebe as páginas não vazias unidas por `"\n\n"`, frases = `split_sentences` desse texto, status `"{nome do arquivo} — {n} páginas"`. Sucesso sem texto → `text_view` vazio, `notify(MSG_NO_TEXT)`, status igual. Erro → `notify(user_message(e))`, documento anterior permanece.
- `play_button`: habilitado só com frases carregadas. Texto por estado: `STOPPED` "▶ Reproduzir", `LOADING`/`PLAYING` "⏸ Pausar", `PAUSED` "▶ Continuar". Clique: `STOPPED` → `player.play(...)` do início; `LOADING`/`PLAYING` → `pause()`; `PAUSED` → `resume()`.
- Sem voz instalada ao apertar Reproduzir (ou ao iniciar, se `offer_download`): pergunta `MSG_NEED_VOICE` (Sim/Não); Sim → `download_default_voice`; com sucesso, recarrega `voice_combo` e segue.
- Trocar a voz no `voice_combo` ou abrir outro PDF durante a leitura → `player.stop()`.
- Status: `LOADING` "Preparando a voz…", `PLAYING` "Lendo…", `PAUSED` "Pausado", fim "Leitura concluída."; sinal `error` do player → `notify(text)`.
- `closeEvent`: `player.stop()`.

- [ ] **Step 1: Write failing tests** — helper `wait_until(qapp, cond, timeout=3.0)` com `qapp.processEvents()`; fixture `window` cria `MainWindow(player=Player(FakeAudioOut()), voices_dir=<tmp com voz falsa "pt_BR-fake-medium">, notify=notes.append, synth_factory=lambda v: FakeSynth(), offer_download=False)`; `FakeSynth.sample_rate = 22050`, `.synthesize = lambda t: b"\x00\x00" * 10`.

```python
def test_starts_empty(window):
    assert not window.play_button.isEnabled()
    assert window.play_button.text() == "▶ Reproduzir"
    assert window.voice_combo.count() == 1 and window.voice_combo.itemText(0) == "Fake · pt_BR · medium"

def test_open_pdf_shows_text_and_enables_play(window, qapp, make_pdf):
    window.open_path(make_pdf(["Olá mundo. Tudo bem?", "Segunda página."]))
    wait_until(qapp, lambda: window.play_button.isEnabled())
    assert window.text_view.toPlainText() == "Olá mundo. Tudo bem?\n\nSegunda página."
    assert "2 páginas" in window.statusBar().currentMessage()

def test_scanned_pdf_shows_notice(window, qapp, make_pdf, notes):
    window.open_path(make_pdf(["", ""])); wait_until(qapp, lambda: notes)
    assert notes == [MSG_NO_TEXT] and not window.play_button.isEnabled()

def test_invalid_file_keeps_previous_document(window, qapp, make_pdf, notes, tmp_path):
    # open good pdf; then open garbage.pdf → notes == [MSG_INVALID]; text unchanged; play still enabled

def test_play_pause_continue_cycle(window, qapp, make_pdf):
    # FakeAudioOut.free = 4 so playback lasts; click → wait text "⏸ Pausar"; click → "▶ Continuar"; click → "⏸ Pausar"

def test_playback_finishes_and_button_resets(window, qapp, make_pdf):
    # click; wait_until button text == "▶ Reproduzir"; status == "Leitura concluída."

def test_opening_another_pdf_stops_playback(window, qapp, make_pdf):
    # start playing (free=2); open_path(other) → wait until loaded → player.state is STOPPED; button "▶ Reproduzir"

def test_changing_voice_stops_playback(...):   # two fake voices in dir; change combo index while PLAYING → STOPPED

def test_no_voice_and_download_declined(qapp, make_pdf, tmp_path, monkeypatch):
    # empty voices_dir; QMessageBox.question patched to return No → click play → player stays STOPPED, no exception
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_main_window.py -v` → FAIL.
- [ ] **Step 3: Implement** `tasks.py`, `messages.py`, `voice_download.py`, `main_window.py`, `app.py`, `__main__.py`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -v` → suíte inteira passa.
- [ ] **Step 5: Verificação real.** (a) Offscreen: abrir um PDF de exemplo, salvar captura com `window.grab().save(...)` no scratchpad e conferir o layout. (b) Com áudio real em volume 0: tocar um PDF de 2 páginas até "Leitura concluída."; conferir pausa/continuar. (c) `.venv/bin/python -m leitorpdf` inicia sem erro no terminal.
- [ ] **Step 6: Commit** `feat: main window with open, voice selection and play/pause`
