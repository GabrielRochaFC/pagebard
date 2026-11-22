# LeitorPDF

Lê PDFs em voz alta no Linux, sem internet, usando as vozes do
[Piper](https://github.com/OHF-Voice/piper1-gpl). Funciona só com a CPU.

## Instalar em 3 passos

1. Baixe o arquivo **`LeitorPDF.flatpak`**.
2. Dê dois cliques nele. A loja de aplicativos abre: clique em **Instalar**.
3. Abra o **LeitorPDF** pelo menu de aplicativos.

Na primeira leitura o programa oferece baixar uma voz em português (63 MB).
Depois disso funciona sem internet.

> É preciso que o computador tenha o **Flatpak** (já vem no Fedora, Linux Mint,
> Pop!_OS e outros). No Ubuntu ele precisa ser instalado antes, uma única vez:
> `sudo apt install flatpak gnome-software-plugin-flatpak`
>
> Se o duplo clique não abrir a loja (nem toda distribuição associa arquivos
> `.flatpak`), instale com um único comando no terminal:
> `flatpak install --user LeitorPDF.flatpak`

## Como usar

1. **Abrir PDF…** (ou arraste o arquivo para a janela). As páginas aparecem
   como no documento original.
2. **Reproduzir.** A frase que está sendo lida fica destacada na página.
3. Para escolher o que ouvir:
   - **clique** numa palavra para começar daquele ponto (durante a leitura,
     pula para lá); **duplo clique** começa a ler na hora;
   - **arraste** sobre o texto para ler só um trecho;
   - ou limite a leitura em **Páginas**.

Também dá para:

- **Exportar MP3…** — grava a leitura das páginas escolhidas num arquivo de
  áudio, com a voz e a velocidade atuais.
- **Vozes…** — baixar outras vozes (vários idiomas) ou remover as que não usa.
- **PDF escaneado** — ao abrir um PDF que é só imagem, o programa oferece
  reconhecer o texto (OCR). Também está em *Arquivo → Reconhecer texto (OCR)…*
- **Texto maior na interface** — *Exibir → Texto da interface*.

| Tecla | O que faz |
|---|---|
| Ctrl+O | Abrir PDF |
| Ctrl+E | Exportar para MP3 |
| Espaço | Reproduzir / pausar / continuar |
| Esc | Parar; com a leitura parada, limpa a seleção e o ponto de início |
| + e - | Leitura mais rápida / mais devagar |
| Ctrl++, Ctrl+-, Ctrl+0 | Aumentar, diminuir, ajustar a página à largura |
| Ctrl+C | Copiar o trecho selecionado |
| F1 | Lista completa de atalhos |
| Ctrl+Q | Sair |

O programa lembra a voz, a velocidade e o tamanho do texto entre uma sessão e
outra.

## Gerar o pacote

Com `flatpak` e `flatpak-builder` instalados:

```bash
packaging/flatpak/build.sh
```

O resultado é `LeitorPDF.flatpak`, na raiz do projeto. O que falta (SDK e
bibliotecas Python) é baixado do Flathub e do PyPI durante a construção.

## Rodar em desenvolvimento

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m leitorpdf
```

Testes: `.venv/bin/python -m pytest`

Para exportar MP3 fora do Flatpak é preciso ter o `ffmpeg` instalado.

## Licença

AGPL-3.0-or-later. Veja [LICENSE](LICENSE).
