import re
import threading
import time

import pymupdf
import pytest
from fakes import PATIENCE

from pagebard.core import ocr, paths
from pagebard.core.pdf import load_pdf, with_ocr
from pagebard.core.reading import build_reading

TEXT = "Este documento foi escaneado. O reconhecimento deve encontrar estas palavras."


def test_scanned_pages_are_detected(make_scanned_pdf, tmp_path):
    scan = make_scanned_pdf([TEXT, ""])
    assert load_pdf(scan).scanned_pages == (0,)  # the blank page is not a scan

    mixed = pymupdf.open(scan)
    mixed.new_page().insert_text((72, 72), "Página com texto de verdade.")
    path = tmp_path / "misto.pdf"
    mixed.save(path)
    doc = load_pdf(path)
    assert doc.scanned_pages == (0,)
    assert doc.pages[2] == "Página com texto de verdade."


def test_text_pdf_has_no_scanned_pages(make_pdf):
    assert load_pdf(make_pdf(["Texto.", ""])).scanned_pages == ()


def test_language_follows_the_voice():
    assert ocr.language_for("pt_BR") == "por"
    assert ocr.language_for("pt_PT") == "por"
    assert ocr.language_for("en_US") == "eng"
    assert ocr.language_for("es_MX") == "spa"
    assert ocr.language_for("fr_FR") == "fra"
    assert ocr.language_for("de_DE") == "deu"
    assert ocr.language_for("it_IT") == "ita"
    assert ocr.language_for("sw_CD") == "por"


def test_tessdata_dir_is_in_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.tessdata_dir() == tmp_path / "pagebard" / "tessdata"
    assert paths.tessdata_dir().is_dir()


def remote(tmp_path, content=b"dados de ocr" * 20000):
    folder = tmp_path / "remote"
    folder.mkdir()
    (folder / "por.traineddata").write_bytes(content)
    return folder.as_uri(), content


def test_download_language(tmp_path):
    base, content = remote(tmp_path)
    dest = tmp_path / "tessdata"
    calls = []
    assert not ocr.has_language("por", dest)
    ocr.download_language("por", dest, progress=lambda d, t: calls.append((d, t)), base_url=base)
    assert ocr.has_language("por", dest)
    assert (dest / "por.traineddata").read_bytes() == content
    assert calls[-1] == (len(content), len(content))
    assert [p.name for p in dest.iterdir()] == ["por.traineddata"]


def test_download_language_cancel_leaves_nothing(tmp_path):
    base, _ = remote(tmp_path)
    dest = tmp_path / "tessdata"
    cancel = threading.Event()
    with pytest.raises(ocr.OcrCancelled):
        ocr.download_language(
            "por", dest, progress=lambda d, t: cancel.set(), cancel=cancel, base_url=base
        )
    assert list(dest.iterdir()) == []
    assert not ocr.has_language("por", dest)


def test_download_language_failure_is_reported(tmp_path):
    dest = tmp_path / "tessdata"

    def offline(url):
        raise OSError("sem rede")

    with pytest.raises(ocr.OcrError, match=re.escape(ocr.MSG_OCR_DATA)):
        ocr.download_language("por", dest, opener=offline)
    assert list(dest.iterdir()) == []


def test_with_ocr_builds_text_and_keeps_other_pages(make_scanned_pdf, tmp_path):
    scan = pymupdf.open(make_scanned_pdf([TEXT, TEXT]))
    scan.new_page().insert_text((72, 72), "Página com texto de verdade.")
    path = tmp_path / "misto.pdf"
    scan.save(path)
    doc = load_pdf(path)
    assert doc.scanned_pages == (0, 1)
    recognized = {
        0: [
            [72.0, 80.0, 100.0, 96.0, "Olá", 0, 0, 0],
            [104.0, 80.0, 160.0, 96.0, "mundo.", 0, 0, 1],
        ],
        1: [],  # nothing found on this one
    }
    result = with_ocr(doc, recognized)
    assert result.pages == ("Olá mundo.", "", "Página com texto de verdade.")
    assert [(w.start, w.end, w.rect) for w in result.words[0]] == [
        (0, 3, (72.0, 80.0, 100.0, 96.0)),
        (4, 10, (104.0, 80.0, 160.0, 96.0)),
    ]
    assert result.words[2] == doc.words[2]
    assert result.scanned_pages == (1,)  # still without text
    assert result.page_sizes == doc.page_sizes and result.path == doc.path
    assert doc.pages[0] == ""  # the original is untouched


# ---- with the real OCR engine ---------------------------------------------------------


def words_of(recognized, page):
    return [entry[4] for entry in recognized[page]]


def test_recognize_reads_the_page(tessdata, make_scanned_pdf):
    path = make_scanned_pdf([TEXT, "Segunda página do documento escaneado."])
    calls = []
    recognized = ocr.recognize(
        path, [0, 1], "por", tessdata, progress=lambda d, t: calls.append((d, t))
    )
    assert " ".join(words_of(recognized, 0)) == TEXT
    assert " ".join(words_of(recognized, 1)) == "Segunda página do documento escaneado."
    assert calls == [(1, 2), (2, 2)]
    x0, y0, x1, y1 = recognized[0][0][:4]
    assert 60 < x0 < x1 < 200 and 60 < y0 < y1 < 120  # "Este", at the top left


def test_recognized_document_can_be_read(tessdata, make_scanned_pdf):
    sentences = [
        "Este documento foi escaneado em uma biblioteca antiga da cidade.",
        "O reconhecimento de texto precisa juntar as linhas de cada frase.",
        "Assim a leitura em voz alta soa natural, sem pausas no fim de cada linha.",
        "A quarta frase serve apenas para completar um parágrafo de tamanho normal.",
        "Por fim, a última frase termina o parágrafo e o teste.",
    ]
    path = make_scanned_pdf([" ".join(sentences)])
    doc = load_pdf(path)
    reading = build_reading(with_ocr(doc, ocr.recognize(path, doc.scanned_pages, "por", tessdata)))
    assert [s.text for s in reading.sentences] == sentences  # whole, not one per line
    rects = reading.rects(reading.sentences[1].start, reading.sentences[1].end)
    assert len(rects) == 2  # the second sentence wraps onto a second line
    assert all(page == 0 for page, _ in rects)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_recognize_handles_scans_stored_turned(tessdata, make_scanned_pdf, rotation):
    path = make_scanned_pdf(["Primeira linha do documento."], rotation=rotation)
    recognized = ocr.recognize(path, [0], "por", tessdata)
    assert " ".join(words_of(recognized, 0)) == "Primeira linha do documento."
    x0, y0, x1, y1 = recognized[0][0][:4]
    assert 60 < x0 < x1 < 200 and 60 < y0 < y1 < 120  # where it shows on screen


def test_recognize_can_be_cancelled(tessdata, make_scanned_pdf):
    path = make_scanned_pdf([TEXT, TEXT, TEXT])
    cancel = threading.Event()
    calls = []

    def progress(done, total):
        calls.append(done)
        cancel.set()

    with pytest.raises(ocr.OcrCancelled):
        ocr.recognize(path, [0, 1, 2], "por", tessdata, progress=progress, cancel=cancel)
    assert calls == [1]


def test_recognize_without_language_data_is_an_error(make_scanned_pdf, tmp_path):
    empty = tmp_path / "tessdata"
    empty.mkdir()
    with pytest.raises(ocr.OcrError, match=re.escape(ocr.MSG_OCR)):
        ocr.recognize(make_scanned_pdf([TEXT]), [0], "por", empty)


def test_recognize_a_missing_file_is_an_error(tessdata, tmp_path):
    with pytest.raises(ocr.OcrError, match=re.escape(ocr.MSG_OCR)):
        ocr.recognize(tmp_path / "nao-existe.pdf", [0], "por", tessdata)


def test_recognition_does_not_stall_this_process(tessdata, make_scanned_pdf):
    path = make_scanned_pdf([TEXT, TEXT])
    done = threading.Event()
    result = {}

    def work():
        result["pages"] = ocr.recognize(path, [0, 1], "por", tessdata)
        done.set()

    threading.Thread(target=work).start()
    longest_gap, last = 0.0, time.monotonic()
    while not done.wait(0.001):
        now = time.monotonic()
        longest_gap = max(longest_gap, now - last)
        last = now
    assert len(result["pages"]) == 2
    assert longest_gap < 0.05 * PATIENCE


def test_ocr_resolution_is_capped_for_oversized_pages():
    from pagebard.core.render_worker import ocr_dpi

    assert ocr_dpi(595, 842) == 300  # A4
    assert ocr_dpi(842, 1191) == 241  # A3: 4000 px on the long side
    assert ocr_dpi(2480, 3508) == 82  # a scan saved as if it were 72 dpi
    assert ocr_dpi(20000, 20000) == 72  # never below screen resolution
    assert ocr_dpi(100, 100) == 300
