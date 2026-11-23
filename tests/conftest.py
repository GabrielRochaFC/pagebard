import os

# Must be set before any Qt module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The tests check the Portuguese texts; other languages have tests of their own.
os.environ["PAGEBARD_LANGUAGE"] = "pt_BR"

import pymupdf
import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_pdf(tmp_path):
    """Build a PDF with one page per string; an empty string is a blank page."""

    def build(pages, name="doc.pdf"):
        doc = pymupdf.open()
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text, fontsize=12)
        path = tmp_path / name
        doc.save(path)
        doc.close()
        return path

    return build


@pytest.fixture
def make_scanned_pdf(tmp_path):
    """A PDF whose pages are pictures of text, like a scan; "" gives a blank page."""

    def build(pages, name="scan.pdf", rotation=0):
        source, scan = pymupdf.open(), pymupdf.open()
        for text in pages:
            page = source.new_page()
            if not text:
                scan.new_page()
                continue
            page.insert_textbox((72, 72, 523, 400), text, fontsize=16)
            picture = page.get_pixmap(dpi=150)
            sideways = rotation in (90, 270)
            target = scan.new_page(width=842, height=595) if sideways else scan.new_page()
            # Stored turned, with the rotation flag that shows it upright again.
            target.insert_image(target.rect, pixmap=picture, rotate=rotation)
            target.set_rotation(rotation)
        path = tmp_path / name
        scan.save(path)
        return path

    return build


@pytest.fixture(scope="session")
def tessdata():
    """Real Portuguese OCR data, downloaded once per machine session."""
    import tempfile
    from pathlib import Path

    from pagebard.core import ocr

    folder = Path(tempfile.gettempdir()) / "pagebard-test-tessdata"
    if not ocr.has_language("por", folder):
        try:
            ocr.download_language("por", folder)
        except Exception as exc:  # offline: the tests that need it are skipped
            pytest.skip(f"OCR data not available: {exc}")
    return folder
