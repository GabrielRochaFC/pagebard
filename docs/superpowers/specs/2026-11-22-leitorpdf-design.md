# LeitorPDF — design

Data: 2026-11-22

## Intenção

App desktop Linux, com interface gráfica, que lê PDFs em voz alta usando TTS
offline (Piper, só CPU). Público: usuários comuns, que não usam terminal.

## Objetivos

- Abrir PDF (botão e arrastar-e-soltar) e escolher intervalo de páginas.
- Escolher voz; baixar vozes (pt_BR e outros idiomas) sob demanda de
  `rhasspy/piper-voices`, com barra de progresso.
- Play / pause / parar, controle de velocidade, destaque da frase atual.
- Síntese por frases em thread separada: a reprodução começa em segundos.
- Exportar o PDF inteiro ou o intervalo para MP3.
- PDF sem texto (escaneado): avisar e oferecer OCR opcional.
- UI simples e acessível: atalhos de teclado, fontes grandes opcionais,
  mensagens de erro claras em português.
- Empacotar como Flatpak, com README de instalação em 3 passos.

## Fora de escopo

- GPU, TTS em nuvem, qualquer recurso que exija internet além dos downloads
  de vozes e dados de OCR.
- Publicação no Flathub (a entrega é um arquivo `.flatpak`).
- Outros formatos (EPUB, DOCX), edição de PDF, marcadores/anotações.
- Windows e macOS.

## Anti-objetivos

- Exigir terminal para instalar ou usar.
- Travar a interface durante síntese, download, exportação ou OCR.
- Mensagens de erro técnicas ou em inglês para o usuário final.

## Restrições

- Stack definida pelo dono do projeto: Python 3 + PySide6, PyMuPDF,
  piper-tts, ffmpeg.
- Licenças: piper-tts é GPL-3.0-or-later e PyMuPDF é AGPL-3.0, logo o app é
  distribuído como AGPL-3.0-or-later.
- Runtime Flatpak freedesktop 26.08: Python 3.14, ffmpeg com libmp3lame.
  Não traz tesseract.

## Abordagens consideradas

**Empacotamento**

- Flatpak (escolhido): o runtime freedesktop 26.08 já traz Python 3.14 e
  ffmpeg com MP3; sandbox; um único arquivo `.flatpak` instalável pela loja
  de aplicativos. Como foi feito: as bibliotecas Python vêm do PyPI, nas
  mesmas versões usadas no desenvolvimento (PySide6 6.12), em vez do
  `io.qt.PySide.BaseApp` previsto no início — assim o pacote tem exatamente
  o Qt que foi testado. Consequências: a construção precisa de rede (não
  serve para o Flathub como está) e a biblioteca Kerberos, que o Qt carrega
  e o runtime não traz, é compilada junto.
- AppImage: um arquivo executável, mas exigiria embutir Python, Qt e ffmpeg,
  e não integra com a loja nem com o menu sem ferramenta extra.

**Saída de áudio**

- QtMultimedia `QAudioSink` (escolhido): já vem no PySide6, funciona no
  sandbox via PipeWire/PulseAudio, pause/retomar nativos.
- `sounddevice` (PortAudio): dependência nativa extra para empacotar.

**Velocidade**

- `length_scale` do Piper (escolhido): muda o ritmo na síntese, sem alterar
  o tom. Vale a partir da próxima frase ainda não sintetizada.
- Alterar a taxa de reprodução: instantâneo, mas distorce o tom.

**OCR**

- Motor Tesseract embutido no PyMuPDF + `por.traineddata` baixado sob
  demanda (escolhido e confirmado): nenhum binário extra no Flatpak. O
  reconhecimento é feito sobre a imagem da página como ela é exibida, para
  funcionar em páginas armazenadas giradas, e roda no processo filho.
- Binário `tesseract` compilado como módulo do Flatpak: plano B.

**Visualização do documento** (decidido depois do MVP, a pedido do dono:
"não visualiza o PDF de verdade")

- Visualizador próprio com páginas renderizadas pelo MuPDF via PyMuPDF
  (escolhido): já é dependência; dá a posição de cada palavra, o que permite
  destacar a frase lida na própria página, clicar para escolher onde começar
  e arrastar para ler só um trecho.
- QtPdf (`QPdfView`): pronto, mas sem seleção de texto no widget e sem ligação
  entre o texto extraído e a posição na página.
- pdf.js dentro do QtWebEngine: visual completo, porém +200 MB no pacote.
- Caixa de texto com o texto extraído (MVP): descartada, não parece o PDF.

## Arquitetura

```
src/leitorpdf/
├── core/        sem Qt, coberto por pytest
│   ├── pdf.py        texto e palavras (com posição) por página
│   ├── segmenter.py  texto → frases com offsets
│   ├── reading.py    texto do documento ↔ retângulos nas páginas
│   ├── voices.py     catálogo voices.json, download, vozes instaladas
│   ├── tts.py        wrapper do Piper → PCM 16-bit mono
│   ├── export.py     PCM → MP3 via ffmpeg
│   ├── ocr.py        OCR via PyMuPDF + tessdata
│   └── paths.py      diretórios XDG
├── playback/
│   ├── synth_worker.py  thread: fila de frases → áudio, alguns blocos à frente
│   └── player.py        QAudioSink, play/pause/parar, sinal "frase atual"
└── ui/          janelas e diálogos; todo texto visível em pt-BR
    ├── pdf_view.py       páginas reais, realces, seleção por palavra, zoom
    └── page_renderer.py  renderização das páginas em thread própria
```

Fluxo de leitura: `pdf` extrai texto e palavras → `reading` divide em frases
e sabe onde cada trecho fica na página → `synth_worker` sintetiza à frente em
thread própria → `player` toca cada bloco e emite a frase atual → `pdf_view`
destaca a frase na página e rola até ela.

Escolha do que ler: clique numa palavra marca o ponto de início (durante a
leitura, pula para lá); duplo clique começa a ler dali; arrastar seleciona um
trecho, que é lido sozinho; o intervalo de páginas limita o resto.

Áudio: a voz é mono, mas o dispositivo recebe dois canais iguais (um stream
de um canal sai só no lado esquerdo no PipeWire).

Threads e processos: o que é lento roda fora da thread da interface e devolve
o resultado por fila comum; essas threads nunca recebem objetos do Qt (um
objeto do Qt liberado por outra thread derruba o programa). O trabalho pesado
do PyMuPDF — desenhar páginas e OCR — roda num processo filho
(`core/render_worker.py`), porque o PyMuPDF segura a trava global do Python
enquanto trabalha e congelaria a janela.

Outros módulos: `core/download.py` (downloads que nunca deixam arquivo pela
metade), `core/export.py` (MP3 via ffmpeg), `core/ocr.py`,
`core/worker_client.py`, `ui/progress.py` (diálogo de progresso cancelável),
`ui/voice_manager.py`, `ui/shortcuts_dialog.py`. Preferências (voz,
velocidade, tamanho do texto, pasta, janela) em `QSettings`.

Dados do usuário (vozes, tessdata) em `$XDG_DATA_HOME/leitorpdf/`.
Voz padrão: `pt_BR-faber-medium`, baixada no primeiro uso.

## Fases

0. Projeto: git, venv, `pyproject.toml`.
1. MVP: abrir PDF, escolher voz, play/pause.
2. Visualizador com as páginas reais; parar, velocidade, destaque da frase
   na página, escolher onde começar, ler um trecho selecionado, intervalo de
   páginas, zoom, arrastar-e-soltar; interface refeita.
3. Gerenciador de vozes: catálogo por idioma, download com progresso, remover.
4. Exportar MP3 (intervalo, progresso, cancelar).
5. PDF escaneado: aviso + OCR opcional.
6. Atalhos, fontes grandes, revisão das mensagens de erro.
7. Manifest Flatpak, bundle, README em 3 passos.

## Decisões deixadas a quem implementa

- Layout exato das janelas e nomes dos atalhos.
- Quantas frases sintetizar à frente.
- ID do app Flatpak (provisório: `io.github.leitorpdf.LeitorPDF`).
