from leitorpdf.core.segmenter import MAX_SENTENCE_CHARS, split_sentences


def texts(source):
    return [s.text for s in split_sentences(source)]


def test_basic():
    assert texts("Olá mundo. Tudo bem? Sim!") == ["Olá mundo.", "Tudo bem?", "Sim!"]


def test_abbreviation():
    assert texts("O Sr. Silva chegou. Ele sorriu.") == [
        "O Sr. Silva chegou.",
        "Ele sorriu.",
    ]


def test_initials():
    assert texts("J. K. Rowling escreveu. Fim.") == ["J. K. Rowling escreveu.", "Fim."]


def test_decimal():
    assert texts("O valor é 3.14 metros. Certo.") == [
        "O valor é 3.14 metros.",
        "Certo.",
    ]


def test_closing_quote():
    assert texts('Ele disse: "Vamos." Depois saiu.') == [
        'Ele disse: "Vamos."',
        "Depois saiu.",
    ]


def test_abbreviation_before_number_does_not_split():
    assert texts("Veja a pág. 3 do livro. Fim.") == ["Veja a pág. 3 do livro.", "Fim."]


def test_paragraphs_split_without_punctuation():
    assert texts("Título\n\nPrimeiro parágrafo sem ponto\n\nSegundo.") == [
        "Título",
        "Primeiro parágrafo sem ponto",
        "Segundo.",
    ]


def test_offsets_match_source():
    source = "  Olá mundo.  Tudo bem?\n\nSim!  "
    out = split_sentences(source)
    assert [s.text for s in out] == ["Olá mundo.", "Tudo bem?", "Sim!"]
    assert all(source[s.start : s.end] == s.text for s in out)
    assert [s.start for s in out] == sorted({s.start for s in out})


def test_long_text_with_commas_is_capped():
    source = "palavra, " * 100
    out = split_sentences(source)
    assert len(out) > 1
    assert all(len(s.text) <= MAX_SENTENCE_CHARS for s in out)
    assert all(s.text.endswith(",") for s in out)
    assert "".join("".join(s.text.split()) for s in out) == "".join(source.split())


def test_long_text_without_spaces_is_capped():
    out = split_sentences("a" * 1000)
    assert all(len(s.text) <= MAX_SENTENCE_CHARS for s in out)
    assert sum(len(s.text) for s in out) == 1000


def test_empty():
    assert texts("") == []
    assert texts("   \n\n ") == []


def test_symbol_only_pieces_are_dropped():
    assert texts("*** --- ...\n\nTexto.") == ["Texto."]


def test_book_sized_text_splits_quickly():
    import time

    source = "Esta é a frase de um livro bem longo. " * 40000  # ~1.5 MB
    began = time.perf_counter()
    out = split_sentences(source)
    assert len(out) == 40000
    assert time.perf_counter() - began < 1.0
