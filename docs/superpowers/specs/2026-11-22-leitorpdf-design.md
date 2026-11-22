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

- Flatpak (escolhido): o runtime já traz Python 3.14 e ffmpeg com MP3;
  `io.qt.PySide.BaseApp` fornece o PySide6; sandbox; um único arquivo
  `.flatpak` instalável pela loja de aplicativos.
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
  demanda (escolhido, a confirmar com teste na fase de OCR): nenhum binário
  extra no Flatpak.
- Binário `tesseract` compilado como módulo do Flatpak: plano B.

## Arquitetura

```
src/leitorpdf/
├── core/        sem Qt, coberto por pytest
│   ├── pdf.py        texto por página, detecção de PDF escaneado
│   ├── segmenter.py  texto → frases com offsets (para o destaque)
│   ├── voices.py     catálogo voices.json, download, vozes instaladas
│   ├── tts.py        wrapper do Piper → PCM 16-bit mono
│   ├── export.py     PCM → MP3 via ffmpeg
│   ├── ocr.py        OCR via PyMuPDF + tessdata
│   └── paths.py      diretórios XDG
├── playback/
│   ├── synth_worker.py  thread: fila de frases → áudio, alguns blocos à frente
│   └── player.py        QAudioSink, play/pause/parar, sinal "frase atual"
└── ui/          janelas e diálogos; todo texto visível em pt-BR
```

Fluxo de leitura: `pdf` extrai texto → `segmenter` divide em frases →
`synth_worker` sintetiza à frente em thread própria → `player` toca cada
bloco e emite a frase atual → `ui` destaca.

Dados do usuário (vozes, tessdata) em `$XDG_DATA_HOME/leitorpdf/`.
Voz padrão: `pt_BR-faber-medium`, baixada no primeiro uso.

## Fases

0. Projeto: git, venv, `pyproject.toml`.
1. MVP: abrir PDF, escolher voz, play/pause.
2. Parar, velocidade, destaque da frase, intervalo de páginas,
   arrastar-e-soltar.
3. Gerenciador de vozes: catálogo por idioma, download com progresso, remover.
4. Exportar MP3 (intervalo, progresso, cancelar).
5. PDF escaneado: aviso + OCR opcional.
6. Atalhos, fontes grandes, revisão das mensagens de erro.
7. Manifest Flatpak, bundle, README em 3 passos.

## Decisões deixadas a quem implementa

- Layout exato das janelas e nomes dos atalhos.
- Quantas frases sintetizar à frente.
- ID do app Flatpak (provisório: `io.github.leitorpdf.LeitorPDF`).
