import os

# Must be set before any Qt module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
