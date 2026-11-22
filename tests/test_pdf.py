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


def page_words(doc, page=0):
    return [doc.pages[page][w.start : w.end] for w in doc.words[page]]


def test_words_map_to_page_text(make_pdf):
    doc = load_pdf(make_pdf(["Olá mundo cruel."]))
    assert page_words(doc) == ["Olá", "mundo", "cruel."]
    assert all(w.rect[0] < w.rect[2] and w.rect[1] < w.rect[3] for w in doc.words[0])
    assert doc.words[0][0].rect[0] < doc.words[0][1].rect[0] < doc.words[0][2].rect[0]
    assert len({w.line for w in doc.words[0]}) == 1


def test_page_sizes(make_pdf):
    assert load_pdf(make_pdf(["a", ""])).page_sizes == ((595.0, 842.0), (595.0, 842.0))


def test_blank_page_has_no_words(make_pdf):
    assert load_pdf(make_pdf([""])).words == ((),)


def test_lines_get_increasing_ids(make_pdf):
    doc = load_pdf(make_pdf(["Primeira linha\nsegunda linha"]))
    lines = [w.line for w in doc.words[0]]
    assert lines == sorted(lines)
    assert len(set(lines)) == 2


def test_hyphenated_word_keeps_both_rectangles(make_pdf):
    doc = load_pdf(make_pdf(["Este é um exem-\nplo simples."]))
    assert doc.pages[0] == "Este é um exemplo simples."
    assert page_words(doc) == ["Este", "é", "um", "exem", "plo", "simples."]
    exem, plo = doc.words[0][3], doc.words[0][4]
    assert exem.end == plo.start
    assert exem.line != plo.line


def test_numeric_range_broken_across_lines_keeps_its_hyphen(make_pdf):
    doc = load_pdf(make_pdf(["De 1990-\n1995 foi assim."]))
    assert doc.pages[0] == "De 1990-1995 foi assim."


def test_hyphen_before_a_capital_is_kept(make_pdf):
    doc = load_pdf(make_pdf(["Ele mora no Rio-\nGrande agora."]))
    assert doc.pages[0] == "Ele mora no Rio-Grande agora."


def test_two_columns_are_read_column_by_column(tmp_path):
    path = tmp_path / "colunas.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for row, word in enumerate(["L1", "L2", "L3"]):
        page.insert_text((72, 100 + 20 * row), word, fontsize=12)
    for row, word in enumerate(["R1", "R2", "R3"]):
        page.insert_text((320, 100 + 20 * row), word, fontsize=12)
    doc.save(path)
    doc.close()
    assert load_pdf(path).pages[0].split() == ["L1", "L2", "L3", "R1", "R2", "R3"]


def test_rotated_page_words_match_what_is_displayed(tmp_path):
    path = tmp_path / "girado.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "um dois tres", fontsize=12)
    page.set_rotation(90)
    doc.save(path)
    doc.close()
    loaded = load_pdf(path)
    assert loaded.page_sizes == ((842.0, 595.0),)
    rects = [w.rect for w in loaded.words[0]]
    # On screen the line now runs top to bottom, near the right edge.
    assert rects[0][1] < rects[1][1] < rects[2][1]
    assert all(700 < r[0] < r[2] < 842 for r in rects)


# ---- documents made by a real word processor (LibreOffice) -----------------------
# The same text laid out four ways: single or 1.5 line spacing, one or two columns,
# justified, with automatic hyphenation (which LibreOffice marks with U+00AD).

from pathlib import Path  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUTS = ["lo_single", "lo_abnt15", "lo_twocol", "lo_twocol15"]


def fixture(name):
    return load_pdf(FIXTURES / f"{name}.pdf")


def flat(doc):
    return " ".join(" ".join(doc.pages).split())


@pytest.mark.parametrize("name", LAYOUTS)
def test_soft_hyphens_are_rejoined(name):
    doc = fixture(name)
    text = flat(doc)
    assert "­" not in text
    assert "Tornou-se, desde então, referência" in text
    assert "constitucionalismo contemporâneo." in text
    assert "transformações extraordinariamente" in text
    assert "República Federativa do Brasil" in text


@pytest.mark.parametrize("name", LAYOUTS)
def test_real_hyphen_survives_a_line_break_when_the_file_marks_soft_ones(name):
    assert "1988, estabeleceu-se como o marco" in flat(fixture(name))


@pytest.mark.parametrize("name", LAYOUTS)
def test_words_still_map_to_the_text_after_hyphen_handling(name):
    doc = fixture(name)
    for page_text, words in zip(doc.pages, doc.words):
        rebuilt = "".join(page_text[w.start : w.end] for w in words)
        assert rebuilt == "".join(page_text.split())
        assert all(w.start < w.end for w in words)


def test_line_spacing_does_not_split_paragraphs_into_lines():
    single, spaced = fixture("lo_single"), fixture("lo_abnt15")
    first_paragraph = (
        "A Constituição da República Federativa do Brasil, promulgada em 1988, "
        "estabeleceu-se como o marco fundamental da redemocratização do país, "
        "garantindo-lhe um extenso rol de direitos fundamentais e reorganizando "
        "profundamente as instituições políticas brasileiras. Tornou-se, desde então, "
        "referência obrigatória para os estudiosos do constitucionalismo contemporâneo."
    )
    for doc in (single, spaced):
        paragraphs = doc.pages[0].split("\n\n")
        assert paragraphs[0] == "Universidade Federal — Relatório Anual de Atividades"
        assert paragraphs[1] == first_paragraph
        assert paragraphs[2].startswith("Durante o período de 1990-1995, a economia")


def test_two_columns_with_wide_line_spacing_read_like_the_compact_layout():
    compact, spaced = fixture("lo_twocol"), fixture("lo_twocol15")
    assert spaced.pages[0].split("\n\n")[1].startswith(
        "A Constituição da República Federativa do Brasil, promulgada em 1988, estabeleceu-se"
    )
    # Same words in the same order on the first page, whatever the spacing.
    spaced_words = flat(spaced).split()[:150]
    assert spaced_words == flat(compact).split()[:150]


def test_short_lines_stay_separate(tmp_path):
    # A list at 1.5 spacing: no line is "full", so none continues on the next.
    path = tmp_path / "lista.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    items = ["Item um", "Item dois bem maior", "Item três", "Item quatro", "Item cinco", "Seis"]
    for row, item in enumerate(items):
        page.insert_text((72, 100 + 18 * row), item, fontsize=12)
    page.insert_textbox(
        (72, 300, 523, 500),
        "Um parágrafo comum, largo o bastante para mostrar onde fica a margem direita "
        "desta página, com várias linhas completas de texto corrido para comparar.",
        fontsize=12,
    )
    doc.save(path)
    doc.close()
    assert load_pdf(path).pages[0].split("\n\n")[:6] == items


def test_heading_in_a_bigger_font_stays_apart_from_the_text_below(tmp_path):
    path = tmp_path / "titulo.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Um título que ocupa a largura quase toda da página aqui", fontsize=16)
    page.insert_text((72, 118), "Texto logo abaixo do título, em letra menor.", fontsize=11)
    doc.save(path)
    doc.close()
    assert load_pdf(path).pages[0] == (
        "Um título que ocupa a largura quase toda da página aqui\n\n"
        "Texto logo abaixo do título, em letra menor."
    )


def test_pdf_without_pages_is_invalid(tmp_path):
    path = tmp_path / "vazio.pdf"
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n"
        b"trailer << /Root 1 0 R >>\n%%EOF\n"
    )
    with pytest.raises(PdfError, match=re.escape(MSG_INVALID)):
        load_pdf(path)
