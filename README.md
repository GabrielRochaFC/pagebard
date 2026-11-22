# LeitorPDF

Lê PDFs em voz alta no Linux, sem internet, usando as vozes do
[Piper](https://github.com/OHF-Voice/piper1-gpl). Funciona só com a CPU.

## Como usar

1. **Abrir PDF…** (ou arraste o arquivo para a janela). As páginas aparecem
   como no documento original.
2. **Reproduzir.** A frase que está sendo lida fica destacada na página.
3. Para escolher o que ouvir:
   - **clique** numa palavra para começar daquele ponto (durante a leitura,
     pula para lá); **duplo clique** começa a ler na hora;
   - **arraste** sobre o texto para ler só um trecho;
   - ou limite a leitura em **Páginas**.

| Tecla | O que faz |
|---|---|
| Ctrl+O | Abrir PDF |
| Espaço | Reproduzir / pausar / continuar |
| Esc | Parar; com a leitura parada, limpa a seleção e o ponto de início |
| + e - | Leitura mais rápida / mais devagar |
| Ctrl++, Ctrl+-, Ctrl+0 | Aumentar, diminuir, ajustar a página à largura |
| Ctrl+C | Copiar o trecho selecionado |

Na primeira vez o programa oferece baixar uma voz em português (63 MB).
Depois disso funciona sem internet.

## Rodar em desenvolvimento

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m leitorpdf
```

Testes: `.venv/bin/python -m pytest`

## Licença

AGPL-3.0-or-later. Veja [LICENSE](LICENSE).
