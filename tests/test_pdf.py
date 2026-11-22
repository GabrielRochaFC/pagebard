import re

import pymupdf
import pytest

from leitorpdf.core.pdf import (
    MSG_INVALID,
    MSG_NOT_FOUND,
    MSG_PASSWORD,
    PdfError,
    load_pdf,
)


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
    path = tmp_path / "blocos.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Título", fontsize=12)
    page.insert_text((72, 400), "Corpo do texto.", fontsize=12)
    doc.save(path)
    doc.close()
    assert load_pdf(path).pages[0] == "Título\n\nCorpo do texto."


def test_blank_pdf_has_no_text(make_pdf):
    doc = load_pdf(make_pdf(["", ""]))
    assert doc.pages == ("", "")
    assert not doc.has_text


def test_missing_file(tmp_path):
    with pytest.raises(PdfError, match=re.escape(MSG_NOT_FOUND)):
        load_pdf(tmp_path / "nao-existe.pdf")


def test_garbage_with_pdf_extension(tmp_path):
    path = tmp_path / "lixo.pdf"
    path.write_bytes(b"isto nao e um pdf")
    with pytest.raises(PdfError, match=re.escape(MSG_INVALID)):
        load_pdf(path)


def test_non_pdf_document_is_rejected(tmp_path):
    path = tmp_path / "nota.txt"
    path.write_text("apenas texto", encoding="utf-8")
    with pytest.raises(PdfError, match=re.escape(MSG_INVALID)):
        load_pdf(path)


def test_password_protected(tmp_path):
    path = tmp_path / "senha.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Segredo.")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x")
    doc.close()
    with pytest.raises(PdfError, match=re.escape(MSG_PASSWORD)):
        load_pdf(path)
