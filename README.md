# LeitorPDF

Lê PDFs em voz alta no Linux, sem internet, usando as vozes do
[Piper](https://github.com/OHF-Voice/piper1-gpl). Funciona só com a CPU.

## Rodar em desenvolvimento

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m leitorpdf
```

Testes: `.venv/bin/python -m pytest`

## Licença

AGPL-3.0-or-later. Veja [LICENSE](LICENSE).
