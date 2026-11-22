# LeitorPDF Fases 3–7 (vozes, MP3, OCR, acessibilidade, Flatpak) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completar o LeitorPDF: gerenciador de vozes, exportação para MP3, OCR para PDFs escaneados, menus/atalhos/texto grande/preferências, e o pacote Flatpak com README de instalação em 3 passos.

**Architecture:** O que é lento roda fora da thread da interface e fala com ela por fila comum (`ui/progress.py` generaliza o diálogo de download). Trabalho pesado do PyMuPDF (desenhar, OCR) roda em processo filho (`core/worker_client.py` + `core/render_worker.py`). A janela ganha barra de menus com todas as ações; preferências em `QSettings`.

**Tech Stack:** igual (Python 3.14, PySide6 6.12, PyMuPDF 2.1, piper-tts 1.8, ffmpeg, pytest). Sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-11-22-leitorpdf-design.md` (fases 3 a 7).

## Global Constraints

- Valem as restrições dos planos anteriores: `core/` sem Qt; texto visível em pt-BR; nada bloqueia a thread da interface.
- Threads de trabalho nunca recebem objetos do Qt nem objetos vigiados por conexões de sinal; resultados voltam por `queue.SimpleQueue` + `QTimer`, ou pelo `run_async`.
- Chamadas demoradas ao PyMuPDF (desenho de página, OCR) rodam no processo filho, nunca no processo da interface.
- Downloads seguem o padrão de `download_voice`: arquivo temporário de nome único, renomeado só no fim; falha ou cancelamento não deixa restos.
- Testes não tocam nas preferências nem nos dados reais do usuário: `QSettings` e diretórios são injetados.
- Rodar testes com `.venv/bin/python -m pytest -q -p no:cacheprovider`.

## Review Focus

1. Cancelar ou perder a internet durante download de voz, de dados de OCR ou da lista de vozes → nada "meio instalado"; mensagem clara; dá para repetir. (Tasks 1, 2, 5)
2. Exportar um documento longo e cancelar no meio, disco cheio, ou ffmpeg ausente → nenhum MP3 parcial fica com o nome final; mensagem clara. (Tasks 3, 4)
3. OCR em documento grande: a janela continua respondendo, dá para cancelar, páginas que já tinham texto não mudam. (Tasks 5, 6)
4. Remover a voz em uso, trocar de voz/velocidade/intervalo durante exportação ou OCR → sem travar, sem estado preso. (Tasks 2, 4, 6)
5. Preferências corrompidas ou apontando para voz que não existe mais → o programa abre normalmente com os padrões. (Task 7)

---

### Task 1: Catálogo de vozes, rótulos em português, remover voz

**Files:** Modify `src/leitorpdf/core/voices.py`, `tests/test_voices.py`, `tests/test_main_window.py` (rótulos).

**Interfaces — Produces:**
- `voices.language_label(code: str) -> str` — `"Português (Brasil)"` para `pt_BR`; tabela pt-BR para os idiomas mais comuns (pt_BR, pt_PT, en_US, en_GB, es_ES, es_MX, es_AR, fr_FR, de_DE, it_IT); senão o próprio código.
- `voices.quality_label(quality: str) -> str` — `x_low` "muito baixa", `low` "baixa", `medium` "média", `high` "alta"; senão o próprio valor.
- `Voice.label` passa a ser `"Faber · Português (Brasil) · média"`.
- `@dataclass(frozen=True) CatalogVoice(key: str, language: str, name: str, quality: str, size_bytes: int)` com `label` igual ao de `Voice`.
- `voices.CATALOG_URL = HF_BASE + "/voices.json"`; `voices.MSG_CATALOG = "Não foi possível obter a lista de vozes. Verifique sua conexão com a internet."`
- `voices.parse_catalog(data: dict) -> list[CatalogVoice]` — ignora entradas malformadas; ordem: pt_BR primeiro, depois por rótulo do idioma, nome, qualidade.
- `voices.fetch_catalog(cache_file: Path, opener=None) -> list[CatalogVoice]` — baixa, grava em `cache_file` (temporário + rename) e devolve; se a rede falhar usa `cache_file` se existir; senão `VoiceDownloadError(MSG_CATALOG)`.
- `voices.remove_voice(key: str, voices_dir: Path) -> None` — apaga `.onnx` e `.onnx.json`; sem erro se já não existem.

- [ ] **Step 1: Tests** — `test_language_and_quality_labels`, `test_voice_label_in_portuguese`, `test_parse_catalog` (amostra com 3 vozes + 1 malformada; ordem e tamanhos), `test_fetch_catalog_writes_cache`, `test_fetch_catalog_falls_back_to_cache_when_offline`, `test_fetch_catalog_without_cache_reports_error`, `test_fetch_catalog_ignores_garbage_response` (JSON inválido → usa cache / erro), `test_remove_voice` (some dos instalados; repetir não falha). Atualizar rótulos esperados nos testes existentes.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run suite → PASS.**
- [ ] **Step 5: Commit** `feat: voice catalog, Portuguese labels, voice removal`

---

### Task 2: Diálogo de progresso genérico e gerenciador de vozes

**Files:** Create `src/leitorpdf/ui/progress.py`, `src/leitorpdf/ui/voice_manager.py`, `tests/test_progress.py`, `tests/test_voice_manager.py`. Modify `src/leitorpdf/ui/voice_download.py` (passa a usar `progress.py`), `src/leitorpdf/ui/main_window.py`, `tests/test_main_window.py`.

**Interfaces — Produces:**
- `progress.Cancelled(Exception)`; `progress.run_with_progress(parent, label: str, work: Callable[[report, cancel], T], notify=None, cancelled=(Cancelled,)) -> T | None` — diálogo modal com barra e "Cancelar"; `work` roda em thread e recebe `report(done: int, total: int, text: str | None = None)` e `cancel: threading.Event`; devolve o resultado, ou `None` se cancelado (exceção em `cancelled`) ou se falhou (mensagem via `notify`, padrão `show_error`). A thread recebe só fila e evento.
- `voice_download.download_default_voice` mantém assinatura e comportamento (seus testes continuam valendo).
- `voice_manager.VoiceManagerDialog(voices_dir: Path, cache_file: Path, parent=None, fetch=fetch_catalog, download=download_voice, notify=None)` com widgets públicos `language_combo`, `table` (colunas Voz, Idioma, Qualidade, Tamanho, Situação), `download_button`, `remove_button`, `status_label`; atributo `changed: bool`.
- `MainWindow.voices_button` ("Vozes…") abre o diálogo; ao fechar, recarrega `voice_combo` mantendo a voz escolhida se ainda existir.

Comportamento do gerenciador: ao abrir mostra as vozes instaladas e busca o catálogo em segundo plano ("Carregando lista de vozes…"); sem rede e sem cache mostra só as instaladas e `MSG_CATALOG` em `status_label`. `language_combo`: "Todos os idiomas" + idiomas do catálogo, começando em Português (Brasil) quando existir. Situação: "Instalada" ou "Disponível". `download_button` habilitado para voz disponível; `remove_button` para instalada. Baixar usa `run_with_progress` ("Baixando voz…", MB). Remover pede confirmação ("Remover a voz …?"). Tamanho em MB.

- [ ] **Step 1: Tests** — progress: resultado, falha → notify + None, cancelar → None e evento setado, retorno imediato com trabalho travado, regressão "thread não recebe nada vigiado pelo Qt". Gerenciador (catálogo falso, download falso): lista por idioma, filtro, pt_BR pré-selecionado, baixar marca "Instalada" e `changed`, remover (confirmação sim/não), sem rede com/sem cache, botões habilitados conforme a linha. Janela: botão abre o diálogo (injetado), combo recarrega e mantém a seleção; voz em uso removida → leitura para e combo segue válido.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run suite → PASS.**
- [ ] **Step 5: Commit** `feat: voice manager`

---

### Task 3: Exportar MP3 (núcleo)

**Files:** Create `src/leitorpdf/core/export.py`, `tests/test_export.py`.

**Interfaces — Produces:**
- `export.MSG_NO_FFMPEG = "Para exportar em MP3 é preciso o programa ffmpeg, que não foi encontrado neste computador."`
- `export.MSG_EXPORT = "Não foi possível gravar o arquivo MP3. Verifique se há espaço em disco e se a pasta permite gravação."`
- `export.ExportError(LeitorError)`, `export.ExportCancelled(Exception)`
- `export.export_mp3(texts: Sequence[str], synthesize: Callable[[str], bytes], sample_rate: int, dest: Path, progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None, title: str | None = None, ffmpeg: str = "ffmpeg") -> None`

Comportamento: `ffmpeg -f s16le -ar <rate> -ac 1 -i pipe:0 -codec:a libmp3lame -q:a 5 [-metadata title=…] -f mp3 <temporário na pasta de destino>`; cada frase sintetizada é escrita na entrada do ffmpeg; `progress(feitas, total)` a cada frase; áudio vazio é pulado. No fim, fecha a entrada, espera o ffmpeg e renomeia o temporário para `dest` (substitui arquivo existente). Cancelamento → mata o ffmpeg, apaga o temporário, `ExportCancelled`. ffmpeg inexistente → `ExportError(MSG_NO_FFMPEG)`. ffmpeg termina com erro, `OSError` ao escrever, ou nenhum áudio produzido → apaga o temporário, `ExportError(MSG_EXPORT)`. Exceção de `synthesize` → apaga o temporário e propaga.

- [ ] **Step 1: Tests** (ffmpeg real; `synthesize` falso gerando tom senoidal) — `test_writes_a_playable_mp3` (ffprobe: codec mp3, duração ≈ soma das frases ±0,3 s, título), `test_progress_per_sentence`, `test_empty_audio_is_skipped`, `test_cancel_leaves_nothing`, `test_existing_file_is_replaced_only_on_success` (falha no meio mantém o arquivo antigo), `test_missing_ffmpeg`, `test_ffmpeg_failure_is_reported` (pasta de destino inexistente), `test_synthesis_error_propagates_and_cleans_up`, `test_nothing_to_say_is_an_error`.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat: MP3 export`

---

### Task 4: Exportar MP3 (interface)

**Files:** Modify `src/leitorpdf/ui/main_window.py`, `src/leitorpdf/ui/messages.py`, `tests/test_main_window.py`.

**Interfaces — Produces:** `MainWindow.export_button` ("Exportar MP3…"); parâmetro de construção `exporter=export_mp3` (para testes).

Comportamento: habilitado com documento com texto. Clique → para a leitura; escopo = páginas do intervalo (inteiras; seleção e ponto de início não contam); sem frases → `MSG_EMPTY_RANGE`. Pede o arquivo (`QFileDialog.getSaveFileName`, sugestão `<nome do pdf>.mp3` na pasta do PDF, filtro "Áudio MP3 (*.mp3)"; acrescenta `.mp3` se faltar). Exporta com `run_with_progress` ("Exportando para MP3… frase N de M") usando a voz e a velocidade atuais. Sucesso → status "MP3 gravado em <arquivo>". Cancelado → status "Exportação cancelada.". Erro → `notify`.

- [ ] **Step 1: Tests** — `test_export_button_needs_text`, `test_export_writes_the_chosen_pages` (exporter falso recebe os textos das páginas 2..3, taxa, destino com `.mp3`, título), `test_export_uses_current_speed`, `test_export_stops_playback`, `test_export_cancelled_dialog_does_nothing`, `test_export_cancel_during_progress`, `test_export_error_is_shown`, `test_export_without_voice_offers_download`.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run suite → PASS.**
- [ ] **Step 5: Commit** `feat: export to MP3 from the window`

---

### Task 5: OCR (núcleo)

**Files:** Create `src/leitorpdf/core/worker_client.py`, `src/leitorpdf/core/ocr.py`, `tests/test_ocr.py`. Modify `src/leitorpdf/core/render_worker.py` (operação `ocr`), `src/leitorpdf/core/pdf.py` (`scanned_pages`, `with_ocr`), `src/leitorpdf/core/paths.py` (`tessdata_dir`), `src/leitorpdf/ui/page_renderer.py` (usa `worker_client`).

**Interfaces — Produces:**
- `worker_client.WorkerProcess()` — `exchange(request: dict) -> tuple[dict, bytes] | None` (inicia o processo filho quando preciso; `None` se ele falhou), `pid() -> int | None`, `stop()`. Sem Qt.
- `PdfText.scanned_pages: tuple[int, ...]` — páginas (a partir de 0) sem palavras e com ao menos uma imagem.
- `pdf.with_ocr(doc: PdfText, recognized: Mapping[int, list]) -> PdfText` — novo `PdfText` em que as páginas de `recognized` ganham texto e palavras (mesmas regras de parágrafo e hífen); as demais ficam iguais; `scanned_pages` perde as reconhecidas com texto.
- `paths.tessdata_dir() -> Path`
- `ocr.TESSDATA_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"`
- `ocr.MSG_OCR_DATA = "Não foi possível baixar os dados de reconhecimento de texto. Verifique sua conexão com a internet e tente novamente."`
- `ocr.MSG_OCR = "Não foi possível reconhecer o texto deste PDF."`
- `ocr.OcrError(LeitorError)`, `ocr.OcrCancelled(Exception)`
- `ocr.language_for(voice_language: str) -> str` — `pt_*` → `por`, `en_*` → `eng`, `es_*` → `spa`, `fr_*` → `fra`, `de_*` → `deu`, `it_*` → `ita`; senão `por`.
- `ocr.has_language(language: str, tessdata: Path) -> bool`
- `ocr.download_language(language, tessdata, progress=None, cancel=None, opener=None, base_url=TESSDATA_BASE) -> None`
- `ocr.recognize(path: Path, pages: Sequence[int], language: str, tessdata: Path, progress=None, cancel=None) -> dict[int, list]` — OCR de cada página no processo filho (300 dpi, página inteira); `progress(feitas, total)`; cancelamento → `OcrCancelled`; falha do processo → `OcrError(MSG_OCR)`. Devolve, por página, as palavras cruas `(x0, y0, x1, y1, texto, bloco, linha, n)`.

- [ ] **Step 1: Tests** (PDF "escaneado" gerado nos testes: texto renderizado como imagem; `por.traineddata` real baixado uma vez para um cache de testes — testes que precisam dele são pulados sem rede) — `test_scanned_pages_are_detected` (página-imagem sim; página em branco não; página com texto não), `test_language_for`, `test_download_language` (file://, progresso, cancelar, erro de rede, sem restos), `test_recognize_reads_the_page` (palavras esperadas com posição dentro da página), `test_recognize_reports_progress_and_can_be_cancelled`, `test_recognize_with_missing_language_data_is_an_error`, `test_with_ocr_builds_text_and_keeps_other_pages`, `test_ocr_runs_in_another_process` (maior intervalo sem a thread principal rodar < 0,05 s), `test_page_renderer_still_works` (suíte do renderizador continua passando com `worker_client`).
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run suite → PASS.**
- [ ] **Step 5: Commit** `feat: OCR for scanned pages`

---

### Task 6: OCR (interface)

**Files:** Modify `src/leitorpdf/ui/main_window.py`, `src/leitorpdf/ui/messages.py`, `tests/test_main_window.py`.

**Interfaces — Produces:** `messages.MSG_OFFER_OCR` (formatável: `"{n} de {total} páginas deste PDF não têm texto (parecem escaneadas). Reconhecer o texto delas agora? Pode levar alguns minutos."`); `MainWindow.ocr_action` (menu, habilitada quando há páginas escaneadas); parâmetros de construção `tessdata_dir`, `recognizer=ocr.recognize`, `ocr_downloader=ocr.download_language`.

Comportamento: ao abrir um PDF com páginas escaneadas, pergunta `MSG_OFFER_OCR` (Sim/Não) — no lugar de `MSG_NO_TEXT`, que fica para PDFs sem texto e sem imagens. Sim (ou a ação do menu): idioma = `language_for` da voz escolhida; se faltarem os dados, baixa com `run_with_progress` ("Baixando dados de reconhecimento…"); reconhece com `run_with_progress` ("Reconhecendo texto… página N de M"); ao terminar, o documento passa a usar o texto reconhecido (mesma posição de rolagem, intervalo de páginas mantido) e Reproduzir fica habilitado; status "Texto reconhecido em N páginas.". Cancelar em qualquer etapa mantém o documento como estava. Erro → `notify`. Nenhuma palavra reconhecida → `notify(MSG_NO_TEXT)`.

- [ ] **Step 1: Tests** (reconhecedor e baixador falsos) — `test_offers_ocr_for_scanned_pdf` (texto da pergunta com contagem), `test_declining_ocr_keeps_document`, `test_ocr_makes_the_document_readable`, `test_ocr_downloads_language_data_first`, `test_ocr_cancel_keeps_document`, `test_ocr_error_is_shown`, `test_ocr_action_enabled_only_with_scanned_pages`, `test_ocr_language_follows_the_voice`, `test_blank_pdf_still_gets_no_text_notice`, `test_mixed_document_keeps_existing_text`.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run suite → PASS.**
- [ ] **Step 5: Commit** `feat: OCR offer and progress in the window`

---

### Task 7: Menus, preferências, texto grande, ajuda, abrir pela linha de comando

**Files:** Create `src/leitorpdf/ui/shortcuts_dialog.py`. Modify `src/leitorpdf/ui/main_window.py`, `src/leitorpdf/app.py`, `tests/test_main_window.py`, `tests/test_app.py`.

**Interfaces — Produces:** parâmetro de construção `settings: QSettings | None = None` (sem persistência quando `None`); `MainWindow.text_scale` (1.0, 1.25 ou 1.5) e `set_text_scale(scale)`; `app.main(argv=None)` abre o primeiro argumento que não começa com `-`.

Comportamento:
- Barra de menus: **Arquivo** (Abrir PDF… Ctrl+O; Exportar MP3… Ctrl+E; Reconhecer texto (OCR)…; Sair Ctrl+Q), **Leitura** (Reproduzir/Pausar Espaço; Parar Esc; Mais rápido +; Mais devagar -; Vozes…), **Exibir** (Aumentar página Ctrl++; Diminuir página Ctrl+-; Ajustar à largura Ctrl+0; Texto da interface → Normal / Grande / Muito grande), **Ajuda** (Atalhos de teclado F1; Sobre o LeitorPDF). Os atalhos passam a pertencer às ações do menu (sem duplicar `QShortcut`); os comportamentos já testados continuam iguais.
- Texto da interface: Normal 1,0×, Grande 1,25×, Muito grande 1,5× do tamanho de fonte padrão, aplicado à janela inteira (menus, botões, barra de status, diálogos).
- Preferências gravadas ao mudar e lidas ao iniciar: voz, velocidade, tamanho do texto, última pasta, geometria da janela. Valor inválido ou voz inexistente → padrão.
- "Atalhos de teclado" lista todos os atalhos; "Sobre" mostra versão, licença (AGPL-3.0-or-later) e os componentes (Piper, PyMuPDF, Qt).

- [ ] **Step 1: Tests** — `test_menu_bar_has_every_action` (títulos e atalhos), `test_actions_follow_state` (exportar/OCR/parar habilitados conforme o estado), todos os testes de teclado existentes continuam passando, `test_text_scale_changes_fonts` (botão e barra de status maiores; opção marcada no menu), `test_settings_are_restored` (voz, velocidade, texto, pasta), `test_bad_settings_fall_back_to_defaults`, `test_no_settings_object_means_no_persistence`, `test_shortcuts_dialog_lists_shortcuts`, `test_main_opens_file_from_command_line`.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run suite → PASS.**
- [ ] **Step 5: Commit** `feat: menus, preferences, large text, shortcuts help`

---

### Task 8: Flatpak e README

**Files:** Create `packaging/flatpak/io.github.leitorpdf.LeitorPDF.yml`, `packaging/flatpak/io.github.leitorpdf.LeitorPDF.desktop`, `packaging/flatpak/io.github.leitorpdf.LeitorPDF.metainfo.xml`, `packaging/flatpak/io.github.leitorpdf.LeitorPDF.svg`, `packaging/flatpak/requirements.txt`, `packaging/flatpak/build.sh`, `tests/test_packaging.py`. Modify `README.md`, `src/leitorpdf/app.py` (ícone da janela).

Comportamento: `packaging/flatpak/build.sh` gera `LeitorPDF.flatpak` (bundle de arquivo único que busca o runtime no Flathub ao instalar). O app instalado abre PDFs pelo menu "Abrir com", lê em voz alta, baixa vozes, exporta MP3 (ffmpeg do runtime) e faz OCR. Permissões: Wayland/X11, áudio, rede (downloads), pasta pessoal (abrir PDFs e gravar MP3). README: instalação em 3 passos para quem não usa terminal + como gerar o pacote.

- [ ] **Step 1: Tests** — `test_desktop_file_is_valid` (`desktop-file-validate` se existir; Exec com `%f`, MimeType application/pdf, nome e comentário em pt-BR), `test_metainfo_is_valid` (`appstreamcli validate --no-net` se existir; id igual ao do manifesto), `test_manifest_matches_app_id_and_command`, `test_icon_is_svg`.
- [ ] **Step 2: Run → FAIL.**  - [ ] **Step 3: Implement os arquivos.**  - [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Build real.** `packaging/flatpak/build.sh`; instalar o bundle (`flatpak install --user`); `flatpak run` com `QT_QPA_PLATFORM=offscreen` num teste de fumaça que abre um PDF, sintetiza uma frase com a voz instalada no sandbox (áudio mudo) e sai com código 0; conferir ffmpeg e OCR dentro do sandbox.
- [ ] **Step 6: Commit** `feat: Flatpak packaging and install guide`
