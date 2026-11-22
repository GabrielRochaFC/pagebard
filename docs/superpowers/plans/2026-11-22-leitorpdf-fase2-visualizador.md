# LeitorPDF Fase 2 (visualizador real e controles de leitura) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar as páginas reais do PDF, destacar nelas a frase lida, deixar o usuário clicar para escolher onde começar e arrastar para ler só um trecho, com parar, velocidade, intervalo de páginas, zoom, arrastar-e-soltar e uma interface refeita; corrigir o que a revisão do MVP achou.

**Architecture:** `core/pdf.py` passa a extrair palavras com posição; `core/reading.py` monta o texto do documento e liga cada trecho de texto aos retângulos na página. `ui/pdf_view.py` é um visualizador próprio: páginas renderizadas pelo MuPDF numa thread, rolagem contínua, zoom, realces e seleção por palavra. `Player` ganha a frase atual e a re-síntese das próximas frases. `ui/main_window.py` é refeita em volta do visualizador.

**Tech Stack:** igual ao MVP (Python 3.14, PySide6 6.12, PyMuPDF 2.1, piper-tts 1.8, pytest). Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-22-leitorpdf-design.md` (fase 2 + seção "Visualizador").

## Global Constraints

- Valem as restrições do plano do MVP: `core/` sem Qt, texto visível em pt-BR, identificadores em inglês, nada bloqueia a thread da interface (renderizar página é trabalho de thread).
- Coordenadas de página em pontos PDF (origem no canto superior esquerdo, como o PyMuPDF). Páginas numeradas a partir de 0 no código e a partir de 1 na interface.
- Velocidade de 0,5× a 2,0× em passos de 0,1×; padrão 1,0×; `length_scale = 1 / velocidade`. Números para o usuário com vírgula decimal.
- Cores dos realces: frase lida `#FFE08A` (modo multiplicar, o texto continua legível); seleção `rgba(56,132,255,90)`; ponto de início `#2563EB`.
- Rodar testes com `.venv/bin/python -m pytest`.

## Review Focus

1. Mudar a velocidade várias vezes seguidas durante a leitura → continua lendo, sem repetir nem pular frases; a nova velocidade vale na frase seguinte. (Tasks 4 e 7)
2. PDF de duas colunas, com palavras hifenizadas e intervalos numéricos quebrados na linha → ordem de leitura por coluna, palavra reunida, número intacto. (Task 2)
3. Soltar na janela algo que não é PDF (imagem, link, vários arquivos) ou abrir arquivo inválido → erro normal; o documento aberto continua. (Task 8)
4. Clicar, arrastar ou dar duplo clique no visualizador sem documento, em página sem texto, ou durante a leitura → nunca trava; clique durante a leitura pula para a frase clicada. (Tasks 5 e 7)
5. Documento grande (centenas de páginas, páginas com imagens pesadas) → rolagem e zoom continuam fluidos; só as páginas visíveis ficam em memória. (Task 5)

---

### Task 1: Correções da revisão no código que permanece

**Files:**
- Modify: `src/leitorpdf/core/voices.py`, `src/leitorpdf/ui/voice_download.py`, `src/leitorpdf/core/segmenter.py`, `src/leitorpdf/playback/player.py`
- Test: `tests/test_voices.py`, `tests/test_voice_download.py`, `tests/test_segmenter.py`, `tests/test_player.py`

**Interfaces:**
- Produces: `Player.shutdown(timeout: float = 3.0) -> None` — `stop()` e espera as threads de síntese ainda vivas terminarem (até `timeout` no total).

Comportamento:
- Download: cada tentativa usa arquivos temporários de nome único (`tempfile.mkstemp(dir=voices_dir, suffix=".part")`) para o `.json` e o `.onnx`; os dois só recebem o nome final no fim (`.json`, depois `.onnx`). Falha ou cancelamento apaga só os temporários daquela tentativa, nunca arquivos finais. Qualquer exceção que não seja `DownloadCancelled` vira `VoiceDownloadError(MSG_DOWNLOAD)`.
- `download_default_voice` não espera a thread de download ao fechar o diálogo.
- Segmentador: palavra de uma única letra (maiúscula ou minúscula) seguida de dígito não encerra frase (`p. 45`, `n. 9.394`).

- [ ] **Step 1: Write failing tests**

```python
# test_voices.py
def test_cancelled_attempt_that_wakes_up_late_does_not_touch_a_later_download(tmp_path):
    # attempt A: fake opener whose onnx read blocks on an Event; run in a thread with cancel event
    # set A's cancel; attempt B (file://) completes; release A → A raises DownloadCancelled
    # installed_voices(dest) == [KEY]; model bytes == ONNX; no *.part left

def test_unexpected_exception_is_cleaned_up_and_reported(tmp_path):
    # opener stream raises http.client.IncompleteRead → VoiceDownloadError(MSG_DOWNLOAD); dir empty

# test_voice_download.py
def test_cancel_returns_promptly_even_if_the_download_is_stuck(qapp, tmp_path):
    # fake download ignores cancel for 1.5 s; cancel after 50 ms → function returns in < 0.5 s

# test_segmenter.py
def test_single_letter_abbreviation_before_number():
    assert texts("Conforme (SILVA, 2010, p. 45). Fim.") == ["Conforme (SILVA, 2010, p. 45).", "Fim."]
    assert texts("A Lei n. 9.394 vale. Fim.") == ["A Lei n. 9.394 vale.", "Fim."]
    assert texts("Ela sabe quem ele é. Depois saiu.") == ["Ela sabe quem ele é.", "Depois saiu."]

# test_player.py
def test_shutdown_waits_for_synthesis_in_flight(player, out):
    # synth sleeps 0.3 s per sentence; play; wait for PLAYING; shutdown() → synth_threads() == [] immediately after
```

- [ ] **Step 2: Run** os quatro arquivos → os novos FALHAM.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` → tudo passa.
- [ ] **Step 5: Commit** `fix: review findings in download, segmentation and shutdown`

---

### Task 2: Extração de palavras com posição

**Files:**
- Modify: `src/leitorpdf/core/pdf.py`, `tests/conftest.py`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Produces:
  - `Rect = tuple[float, float, float, float]` — `(x0, y0, x1, y1)`.
  - `@dataclass(frozen=True) Word(start: int, end: int, rect: Rect, line: int)` — `start/end` são offsets no texto da própria página; `line` identifica a linha (palavras da mesma linha têm o mesmo valor, crescente na ordem de leitura).
  - `PdfText(path, pages: tuple[str, ...], words: tuple[tuple[Word, ...], ...], page_sizes: tuple[tuple[float, float], ...])` — `words[p]` na ordem de leitura; `pages[p][w.start:w.end]` é o texto da palavra (sem o hífen de quebra de linha).
  - `load_pdf` como antes (mesmas mensagens de erro).

Regras: palavras na ordem natural do arquivo (`page.get_text("words", sort=False)`, sem preservar ligaduras) — é o que mantém colunas em ordem. Blocos viram parágrafos unidos por `"\n\n"`; palavras de um bloco unidas por um espaço. Última palavra de uma linha terminando em hífen precedido de letra, seguida na mesma coluna por palavra começando com letra minúscula → as duas partes ficam coladas e o hífen some (cada parte continua sendo um `Word` com seu retângulo). Números (`1990-` / `1995`) e maiúsculas não são colados: o hífen fica e as partes ficam sem espaço entre elas.

- [ ] **Step 1: Write failing tests** (os testes atuais de `pages` e de erros continuam valendo; `test_hyphenated_line_end_is_rejoined` continua passando)

```python
def test_words_map_to_page_text(make_pdf):
    doc = load_pdf(make_pdf(["Olá mundo cruel."]))
    assert [doc.pages[0][w.start:w.end] for w in doc.words[0]] == ["Olá", "mundo", "cruel."]
    assert all(w.rect[0] < w.rect[2] and w.rect[1] < w.rect[3] for w in doc.words[0])
    assert doc.words[0][0].rect[0] < doc.words[0][1].rect[0]          # left to right
    assert len({w.line for w in doc.words[0]}) == 1

def test_page_sizes(make_pdf):
    assert load_pdf(make_pdf(["a", ""])).page_sizes == ((595.0, 842.0), (595.0, 842.0))

def test_blank_page_has_no_words(make_pdf):
    assert load_pdf(make_pdf([""])).words == ((),)

def test_lines_get_increasing_ids(make_pdf):
    doc = load_pdf(make_pdf(["Primeira linha\nsegunda linha"]))
    lines = [w.line for w in doc.words[0]]
    assert lines == sorted(lines) and len(set(lines)) == 2

def test_hyphenated_word_keeps_both_rectangles(make_pdf):
    doc = load_pdf(make_pdf(["Este é um exem-\nplo simples."]))
    assert doc.pages[0] == "Este é um exemplo simples."
    parts = [doc.pages[0][w.start:w.end] for w in doc.words[0]]
    assert parts == ["Este", "é", "um", "exem", "plo", "simples."]

def test_numeric_range_broken_across_lines_keeps_its_hyphen(make_pdf):
    assert load_pdf(make_pdf(["De 1990-\n1995 foi assim."])).pages[0] == "De 1990-1995 foi assim."

def test_two_columns_are_read_column_by_column(tmp_path):
    # left column lines L1..L3 at x=72, right column R1..R3 at x=320, same y positions,
    # inserted in the file column by column
    assert load_pdf(path).pages[0].split() == ["L1", "L2", "L3", "R1", "R2", "R3"]
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_pdf.py -v` → os novos FALHAM.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → todos passam.
- [ ] **Step 5: Commit** `feat: extract words with positions, in natural reading order`

---

### Task 3: Modelo de leitura

**Files:**
- Create: `src/leitorpdf/core/reading.py`
- Test: `tests/test_reading.py`

**Interfaces:**
- Consumes: `pdf.PdfText`, `pdf.Word`, `pdf.Rect`, `segmenter.Sentence`, `segmenter.split_sentences`.
- Produces:
  - `@dataclass(frozen=True) PlacedWord(start: int, end: int, page: int, rect: Rect, line: int)` — offsets no texto do documento; `page` a partir de 0; `line` único no documento.
  - `Reading` (imutável) com: `text: str` (páginas não vazias unidas por `"\n\n"`), `words: tuple[PlacedWord, ...]` (ordem de leitura), `sentences: tuple[Sentence, ...]`, `page_count: int`, `page_sizes`.
  - `reading.build_reading(doc: PdfText) -> Reading`
  - `Reading.rects(start: int, end: int) -> list[tuple[int, Rect]]` — `(página, retângulo)` cobrindo as palavras que tocam `[start, end)`, um retângulo por linha (união das palavras da linha).
  - `Reading.page_of(offset: int) -> int` — página (a partir de 0) da primeira palavra em ou depois de `offset`; da última palavra se não houver.
  - `Reading.word_at(page: int, x: float, y: float, tolerance: float = 2.0) -> int | None` — índice da palavra cujo retângulo (aumentado de `tolerance`) contém o ponto.
  - `Reading.nearest_word(page: int, x: float, y: float) -> int | None` — palavra mais próxima naquela página; `None` se a página não tem palavras.
  - `Reading.sentence_index_at(offset: int) -> int | None` — frase que contém `offset`, ou a primeira que começa depois; `None` sem frases ou depois da última.
  - `Reading.sentences_between(start: int, end: int) -> list[Sentence]` — frases do trecho `text[start:end]`, com offsets do documento (as das pontas podem ser parciais).
  - `Reading.slice_for_pages(first: int, last: int) -> tuple[int, int]` — páginas a partir de 1, inclusive; `sentences[i:j]` são as frases que começam nessas páginas; `(0, 0)` se nenhuma.

- [ ] **Step 1: Write failing tests** (fixture `reading` = `build_reading(load_pdf(make_pdf(["Um dois. Três quatro.", "", "Cinco seis."])))`)

```python
def test_text_and_sentences(reading):
    assert reading.text == "Um dois. Três quatro.\n\nCinco seis."
    assert [s.text for s in reading.sentences] == ["Um dois.", "Três quatro.", "Cinco seis."]
    assert reading.page_count == 3

def test_words_carry_document_offsets_and_pages(reading):
    assert [reading.text[w.start:w.end] for w in reading.words] == ["Um", "dois.", "Três", "quatro.", "Cinco", "seis."]
    assert [w.page for w in reading.words] == [0, 0, 0, 0, 2, 2]

def test_rects_cover_the_words_of_a_range(reading):
    first = reading.sentences[0]
    [(page, rect)] = reading.rects(first.start, first.end)
    assert page == 0
    assert rect[0] == reading.words[0].rect[0] and rect[2] == reading.words[1].rect[2]

def test_rects_one_per_line(make_pdf):   # "Linha um\nlinha dois" → two rects for the whole text; none for an empty range
def test_page_of(reading):               # offset in "Cinco" → 2; offset 0 → 0; offset past the end → 2
def test_word_at_and_nearest(reading):
    w = reading.words[2]; cx, cy = (w.rect[0] + w.rect[2]) / 2, (w.rect[1] + w.rect[3]) / 2
    assert reading.word_at(0, cx, cy) == 2
    assert reading.word_at(0, 500, 700) is None and reading.nearest_word(0, 500, 700) == 3
    assert reading.word_at(1, cx, cy) is None and reading.nearest_word(1, cx, cy) is None
def test_sentence_index_at(reading):     # offset inside "Três" → 1; in the "\n\n" gap → 2; len(text) → None
def test_sentences_between_can_be_partial(reading):
    a, b = reading.words[1].start, reading.words[2].end        # "dois. Três"
    assert [s.text for s in reading.sentences_between(a, b)] == ["dois.", "Três"]
    assert all(reading.text[s.start:s.end] == s.text for s in reading.sentences_between(a, b))
def test_slice_for_pages(reading):       # (1,3)→(0,3); (1,1)→(0,2); (2,2)→(0,0); (2,3)→(2,3); (3,3)→(2,3)
def test_document_without_text(make_pdf):  # text "", no words, no sentences; every query returns None / [] / (0, 0)
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_reading.py -v` → FAIL.
- [ ] **Step 3: Implement** (buscas por `bisect` sobre offsets; índice de palavras por página).
- [ ] **Step 4: Run** → todos passam.
- [ ] **Step 5: Commit** `feat: reading model linking text to page geometry`

---

### Task 4: Player — frase atual e re-síntese das próximas

**Files:**
- Modify: `src/leitorpdf/playback/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Produces: `Player.current_index: int | None` (frase sendo enviada ao dispositivo; `None` parado ou antes da primeira); `Player.resynthesize_upcoming() -> None` — descarta o que foi sintetizado à frente e recomeça na frase seguinte à atual (ou na inicial, se nenhuma tocou). A frase atual termina como está. Sem efeito se `STOPPED`; mantém a pausa.

- [ ] **Step 1: Write failing tests**

```python
def test_current_index_follows_playback(player, out, rec)       # None → rec.started[-1] while playing → None after finished
def test_resynthesize_applies_to_following_sentences(player, out, rec):
    # mode = {"v": b"a"}; synth = lambda t: mode["v"] * 4; out.free = 2; sentences ["s"] * 4
    # run until rec.started == [0]; mode["v"] = b"b"; resynthesize_upcoming(); run until finished
    # bytes(out.written) == b"aaaa" + b"bbbb" * 3; rec.started == [0, 1, 2, 3]
def test_resynthesize_before_first_audio_restarts_from_start_index(player, out, rec)   # start=1 → rec.started == [1, 2]
def test_resynthesize_many_times_in_a_row(player, out, rec)     # 50 calls → rec.started == [0, 1, 2, 3]; no leftover threads
def test_resynthesize_when_stopped_is_a_noop(player, rec)
def test_resynthesize_while_paused_stays_paused(player, out, rec)
```

- [ ] **Step 2: Run** → os novos FALHAM.  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` → passa.
- [ ] **Step 5: Commit** `feat: player current sentence and re-synthesis of upcoming audio`

---

### Task 5: Visualizador de PDF

**Files:**
- Create: `src/leitorpdf/ui/page_renderer.py`, `src/leitorpdf/ui/pdf_view.py`
- Test: `tests/test_pdf_view.py`

**Interfaces:**
- Consumes: `Reading` (Task 3).
- Produces:
  - `page_renderer.PageRenderer(QObject)`: sinal `rendered(int generation, int page, float scale, QImage image)`; `open(path: Path | None) -> int` (nova geração); `request(page: int, scale: float) -> None`; `set_wanted(keys: set[tuple[int, float]]) -> None` (pedidos fora do conjunto são descartados); `close() -> None`. Uma thread própria é a única que toca no documento PyMuPDF.
  - `pdf_view.PdfView(QAbstractScrollArea)`:
    - sinais: `word_clicked(int)`, `word_double_clicked(int)`, `background_clicked()`, `selection_changed(int, int)` (offsets no texto; `(-1, -1)` ao limpar), `context_requested(int, QPoint)` (índice da palavra ou -1, posição global), `page_changed(int)` (a partir de 1), `zoom_changed(float)`
    - `set_document(path: Path | None, reading: Reading | None) -> None`
    - `set_reading_highlight(start: int, end: int)`, `clear_reading_highlight()`, `reading_highlight() -> tuple[int, int] | None`
    - `set_start_marker(start: int, end: int)`, `clear_start_marker()`, `start_marker() -> tuple[int, int] | None`
    - `selection() -> tuple[int, int] | None`, `clear_selection()`, `selected_text() -> str`
    - `scroll_to(offset: int) -> None` — se os retângulos do trecho que começa em `offset` não estão inteiros na área visível, rola para deixá-los a 1/3 do topo.
    - `zoom() -> float` (pixels por ponto), `zoom_in()`, `zoom_out()`, `fit_width()`, `is_fit_width() -> bool`; limites 0,5..4,0; passo ×1,25.
    - `current_page() -> int` (a partir de 1; 0 sem documento), `go_to_page(page: int)`
    - `page_rect(page: int) -> QRect` (posição da página no conteúdo, pixels), `to_view(page: int, x: float, y: float) -> QPoint` (ponto da página → posição no viewport), `to_page(pos: QPoint) -> tuple[int, float, float] | None`
    - `rendered_pages() -> set[int]` (páginas com imagem pronta no zoom atual)

Comportamento:
- Páginas empilhadas na vertical, centralizadas, 12 px entre elas e nas bordas; fundo cinza neutro; página branca até a imagem chegar. Zoom inicial "ajustar à largura" (refeito ao redimensionar enquanto estiver nesse modo; limitado a 2,5).
- Só páginas visíveis (mais uma acima e uma abaixo) são pedidas e mantidas em memória; imagens renderizadas em `zoom × devicePixelRatio`.
- Realces desenhados sobre a página: seleção (azul translúcido), frase lida (`#FFE08A`, multiplicar), ponto de início (sublinhado de 2 px `#2563EB` nas linhas do trecho).
- Mouse: clique sem arrastar sobre palavra → limpa a seleção, `word_clicked`; fora de palavra → limpa a seleção, `background_clicked`. Arrastar (além de `QApplication.startDragDistance()`) → seleção da palavra mais próxima do início até a mais próxima do ponto atual, em ordem de leitura; `selection_changed` a cada mudança. Duplo clique sobre palavra → `word_double_clicked`. Botão direito → `context_requested`. Cursor em I sobre palavras.
- Teclado: setas, PageUp/PageDown, Home/End rolam. Ctrl+roda do mouse dá zoom.
- Sem documento: texto central "Abra um PDF (Ctrl+O) ou arraste o arquivo para cá".
- Não aceita soltar arquivos (o evento sobe para a janela).

- [ ] **Step 1: Write failing tests** (fixture `view`: `PdfView` 800×600 exibido offscreen com um PDF de 3 páginas de texto; helper `center(view, word_index) -> QPoint`)

```python
def test_empty_view_has_no_pages(qapp)                    # current_page() == 0; to_page(any) is None; clicks emit nothing
def test_fits_page_width(view)                            # is_fit_width(); page_rect(0).width() ≈ viewport width − 24 (±2), limitado por 2,5 × largura
def test_pages_are_stacked(view)                          # page_rect(1).top() == page_rect(0).bottom() + 12 (±1)
def test_coordinate_round_trip(view)                      # to_page(to_view(1, 100, 200)) ≈ (1, 100, 200) depois de go_to_page(2)
def test_visible_pages_get_rendered(view, qapp)           # wait_until 0 in rendered_pages(); grab: page area has dark pixels (text) and white ones
def test_only_nearby_pages_stay_in_memory(qapp)           # 30-page doc: after scrolling to the end, rendered_pages() ⊆ last 3 pages
def test_click_on_word_emits_its_index(view)              # QTest.mouseClick at center(view, 3) → word_clicked == [3]; selection() is None
def test_click_on_background(view)                        # background_clicked emitted once; nothing else
def test_drag_selects_words_in_reading_order(view)        # press at word 1, move, release at word 4 → selection() == (words[1].start, words[4].end); selected_text(); dragging backwards gives the same range
def test_click_clears_selection(view)                     # after a drag, click → selection() is None; selection_changed last == (-1, -1)
def test_double_click_emits(view)                         # word_double_clicked == [3]
def test_right_click_requests_context(view)               # context_requested == [(3, <global pos>)]; on background → (-1, …)
def test_reading_highlight_is_painted(view, qapp)         # set_reading_highlight(sentence 0) → grabbed pixel just inside the first rect's top-left corner is amber (r > 200, b < 200); clear → white
def test_start_marker_and_selection_state(view)           # setters/getters/clear
def test_scroll_to_brings_a_later_page_into_view(view)    # scroll_to(offset on page 3) → current_page() == 3; page_changed emitted with 3; its rect inside the viewport
def test_zoom(view)                                       # zoom_in → zoom ×1.25, not fit width, zoom_changed emitted, page_rect larger; clamps at 4.0 / 0.5; fit_width() restores
def test_resize_keeps_fit_width(view)                     # resize to 500 px wide → page width follows
def test_new_document_resets_state(view)                  # highlight, marker, selection gone; scroll at top
def test_keyboard_scrolls(view)                           # PageDown moves the scrollbar by about a viewport
def test_does_not_accept_drops(view)                      # not view.acceptDrops() and not view.viewport().acceptDrops()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_pdf_view.py -v` → FAIL.
- [ ] **Step 3: Implement** `page_renderer.py` e `pdf_view.py`.
- [ ] **Step 4: Run** → todos passam; `.venv/bin/python -m pytest -q` passa.
- [ ] **Step 5: Commit** `feat: PDF view with rendered pages, highlights and word selection`

---

### Task 6: Janela nova em volta do visualizador

**Files:**
- Rewrite: `src/leitorpdf/ui/main_window.py`, `tests/test_main_window.py`
- Modify: `src/leitorpdf/ui/messages.py`, `src/leitorpdf/app.py`, `tests/test_app.py`, `tests/fakes.py`

**Interfaces:**
- Consumes: `PdfView`, `Reading`, `Player` (Tasks 3–5), `Player.shutdown` (Task 1).
- Produces: `MainWindow` com os mesmos parâmetros de construção do MVP e widgets públicos `open_button`, `play_button`, `stop_button`, `voice_combo`, `pdf_view`, `page_label`; propriedade `reading: Reading | None`; `app.quiet_qt_logging() -> None`.

Comportamento:
- Janela 1100×800, estilo Fusion (segue tema claro/escuro do sistema), folha de estilo com botão Reproduzir em destaque. Linha 1: `open_button` "Abrir PDF…" (Ctrl+O), `play_button`, `stop_button` "⏹ Parar" (Esc), espaço, "Voz:" + `voice_combo`. Linha 2 é preenchida nas Tasks 7 e 8. Centro: `pdf_view`. Barra de status: mensagem à esquerda, `page_label` "Página 3 de 20" à direita.
- Abrir PDF: como no MVP (em segundo plano, o último pedido vence, erro mantém o documento anterior), agora com `build_reading` e `pdf_view.set_document`. PDF sem frases (escaneado ou só símbolos) → páginas exibidas, `notify(MSG_NO_TEXT)`, Reproduzir desabilitado.
- Reproduzir/Pausar/Continuar como no MVP. Espaço: atalho da janela (`QShortcut`, sem repetição automática) que age como um clique em `play_button` quando habilitado — uma pressão alterna uma vez, com o foco em qualquer lugar.
- `stop_button` habilitado só fora de `STOPPED`; Esc para a leitura.
- A cada frase: `pdf_view.set_reading_highlight` + `scroll_to`; status "Lendo — página N de M". O realce some ao parar, ao terminar e ao abrir outro documento; continua na pausa.
- Fechar a janela: `player.shutdown()` e fecha o renderizador.
- `app.main()`: `quiet_qt_logging()` desliga `qt.qpa.wayland.textinput` (aviso), `qt.qpa.services` (aviso) e `qt.multimedia.ffmpeg` (info); estilo Fusion.

- [ ] **Step 1: Write failing tests** — reescrever `tests/test_main_window.py` mantendo os casos do MVP (abrir, erro, PDF sem texto, último arquivo vence, diálogo, ciclo reproduzir/pausar/continuar, troca de voz, sem voz, fechar) com `window.reading.text` no lugar do `text_view`, e acrescentar:

```python
def test_space_toggles_exactly_once_with_focus_on_the_play_button(...)   # show window, click play (mouse), QTest.keyClick(Key_Space) → PAUSED; again → PLAYING
def test_space_does_nothing_without_a_document(...)
def test_stop_button_follows_player_state(...)            # disabled → enabled while playing/paused → click → STOPPED, disabled
def test_escape_stops_reading(...)
def test_sentence_being_read_is_highlighted_on_the_page(...)   # pdf_view.reading_highlight() == (s.start, s.end) of the current sentence
def test_highlight_clears_on_stop_finish_and_new_document(...)
def test_status_shows_the_page_being_read(...)            # "Lendo — página 2 de 2"
def test_page_label_follows_the_view(...)                 # "Página 1 de 3"; after pdf_view.go_to_page(3) → "Página 3 de 3"; "" sem documento
def test_symbols_only_pdf_shows_notice(...)               # notes == [MSG_NO_TEXT]
def test_quiet_qt_logging(qapp)                           # QLoggingCategory("qt.qpa.wayland.textinput").isWarningEnabled() is False afterwards
```

- [ ] **Step 2: Run** → FALHAM.  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` → passa.
- [ ] **Step 5: Commit** `feat: main window built around the PDF view`

---

### Task 7: Onde começar, ler um trecho, velocidade

**Files:**
- Modify: `src/leitorpdf/ui/main_window.py`, `tests/test_main_window.py`, `tests/fakes.py`

**Interfaces:**
- Produces: widgets `speed_slider`, `speed_label`.

Comportamento:
- Clique numa palavra: a frase dela vira o ponto de início (`pdf_view.set_start_marker`). Parado/pausado: Reproduzir começa dali. Lendo: a leitura pula para essa frase na hora.
- Duplo clique numa palavra: começa a ler dessa frase imediatamente.
- Arrastar seleciona um trecho; com seleção, Reproduzir lê só o trecho (`Reading.sentences_between`), e o ponto de início é ignorado. Clicar fora do texto limpa seleção e ponto de início. Esc com a leitura parada limpa a seleção; se não há seleção, limpa o ponto de início.
- Texto de `play_button` parado: "▶ Ler seleção" com seleção; "▶ Ler daqui" com ponto de início; senão "▶ Reproduzir".
- Menu do botão direito no visualizador: "Ler a partir daqui" (sobre palavra), "Ler seleção" e "Copiar" (com seleção). Ctrl+C copia a seleção.
- Depois de abrir um documento com texto, o status mostra o nome, as páginas e a dica "clique no texto para escolher onde começar; arraste para ler só um trecho".
- Linha 2: "Velocidade:" + `speed_slider` (5..20, padrão 10) + `speed_label` ("1,0×"). Atalhos `+`/`=` e `-`. A síntese lê `length_scale = 10 / valor` a cada frase; mudança durante a leitura chama `player.resynthesize_upcoming()` 250 ms depois da última mudança.

- [ ] **Step 1: Write failing tests**

```python
def test_click_sets_the_start_point(...)                  # marker == sentence of the word; play text "▶ Ler daqui"; play → synth.spoken starts at that sentence
def test_click_while_reading_jumps_there(...)             # long playback; click a word in a later sentence → next spoken sentence is that one; still PLAYING
def test_double_click_starts_reading_from_there(...)
def test_selection_is_read_alone(...)                     # drag over part of the text → "▶ Ler seleção"; spoken == pieces of the selection only
def test_background_click_clears_selection_and_marker(...)
def test_escape_clears_selection_then_marker_when_stopped(...)
def test_copy_puts_selection_on_the_clipboard(...)
def test_context_menu_actions(...)                        # actions offered per situation (word / selection / background)
def test_status_has_the_hint_after_opening(...)
def test_speed_label_and_range(...)                       # "1,0×" → 15 → "1,5×"; limits (5, 20)
def test_speed_is_passed_to_the_synthesizer(...)          # slider 20 → scales all 0.5
def test_changing_speed_while_reading_applies_to_following_sentences(...)
def test_speed_shortcuts(...)                             # + / = raise, - lowers, clamped
```

- [ ] **Step 2: Run** → FALHAM.  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` → passa.
- [ ] **Step 5: Commit** `feat: start point, read selection and speed control`

---

### Task 8: Intervalo de páginas, zoom e arrastar-e-soltar

**Files:**
- Modify: `src/leitorpdf/ui/main_window.py`, `src/leitorpdf/ui/messages.py`, `tests/test_main_window.py`

**Interfaces:**
- Produces: widgets `first_page_spin`, `last_page_spin`, `zoom_out_button`, `zoom_in_button`, `fit_button`, `zoom_label`; `messages.MSG_EMPTY_RANGE = "Não há texto para ler nas páginas escolhidas."`

Comportamento:
- Linha 2 (continuação): "Páginas:" `first_page_spin` "a" `last_page_spin`; à direita `zoom_out_button` "−", `zoom_label` ("125%" = zoom relativo a 96 dpi), `zoom_in_button` "+", `fit_button` "Ajustar à largura". Atalhos Ctrl+`-`, Ctrl+`+`/`=`, Ctrl+0 (ajustar).
- Intervalo: desabilitado sem documento com texto; ao abrir, 1..N. `first > last` nunca acontece (mexer em um ajusta o outro). Sem seleção, Reproduzir lê as frases das páginas escolhidas, começando no ponto de início se ele estiver dentro do intervalo. Clicar numa palavra fora do intervalo ajusta o intervalo para incluir a página dela (primeira página = página clicada; última volta a N se ficou antes). Mudar o intervalo à mão limpa o ponto de início e para a leitura. Intervalo sem frases → `notify(MSG_EMPTY_RANGE)`.
- Arrastar-e-soltar: a janela aceita URLs de arquivo local; solta → `open_path` do primeiro arquivo local; o resto é ignorado.

- [ ] **Step 1: Write failing tests**

```python
def test_page_range_defaults_and_limits(...)              # disabled before; 3 pages → (1, 3), enabled
def test_reads_only_the_selected_pages(...)
def test_first_page_never_exceeds_last(...)
def test_changing_the_range_stops_playback_and_clears_the_marker(...)
def test_range_without_text_shows_notice(...)
def test_start_point_inside_the_range_is_used(...)
def test_click_outside_the_range_moves_the_range(...)
def test_new_document_resets_the_range(...)
def test_zoom_buttons_and_label(...)                      # label follows pdf_view zoom; fit button restores fit width
def test_dropping_a_pdf_opens_it(...) / test_dropping_several_files_opens_the_first(...)
def test_dropping_a_web_link_or_text_is_ignored(...)
def test_dropping_a_non_pdf_reports_and_keeps_document(...)
```

- [ ] **Step 2: Run** → FALHAM.  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` → passa.
- [ ] **Step 5: Verificação real.** Script descartável (voz real, áudio real mudo, janela offscreen): abrir um PDF de várias páginas com duas colunas; capturas de tela da janela vazia, com documento, lendo (realce), com seleção e com ponto de início; ler um trecho selecionado até o fim; mudar a velocidade no meio; conferir log e imagens. `.venv/bin/python -m leitorpdf` inicia sem mensagens no terminal.
- [ ] **Step 6: Commit** `feat: page range, zoom controls and drag and drop`
