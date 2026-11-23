import os
import time

import pymupdf
import pytest
from fakes import PATIENCE

from pagebard.ui.page_renderer import PageRenderer


@pytest.fixture
def renderer():
    renderer = PageRenderer()
    yield renderer
    renderer.close()


def results(renderer, count=1, timeout=5.0):
    """Poll until `count` results arrived."""
    found = []
    deadline = time.monotonic() + timeout
    while len(found) < count:
        if time.monotonic() > deadline:
            raise AssertionError(f"only {len(found)} of {count} results arrived")
        found.extend(renderer.poll())
        time.sleep(0.005)
    return found


def ask(renderer, page, scale):
    renderer.set_wanted({(page, scale)})
    renderer.request(page, scale)


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_renders_a_page_at_the_requested_scale(renderer, make_pdf):
    generation = renderer.open(make_pdf(["Olá mundo."]))
    ask(renderer, 0, 2.0)
    [(got_generation, page, scale, image)] = results(renderer)
    assert (got_generation, page, scale) == (generation, 0, 2.0)
    assert (image.width(), image.height()) == (1190, 1684)
    assert image.pixelColor(5, 5).lightness() == 255  # blank corner of the page
    dark = sum(
        1 for x in range(140, 260, 2) for y in range(115, 150, 2)
        if image.pixelColor(x, y).lightness() < 100
    )
    assert dark > 10  # the text is there


def test_pages_are_drawn_in_another_process(renderer, make_pdf):
    # PyMuPDF keeps Python's lock while it draws; in this process that would
    # freeze the window for as long as a heavy page takes.
    renderer.open(make_pdf(["Olá mundo."]))
    ask(renderer, 0, 1.0)
    results(renderer)
    pid = renderer.worker_pid()
    assert pid is not None and pid != os.getpid()
    assert not gone(pid)
    renderer.close()
    deadline = time.monotonic() + 3.0
    while not gone(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert gone(pid)
    assert renderer.worker_pid() is None


def test_ui_thread_keeps_running_while_a_heavy_page_is_drawn(renderer, tmp_path):
    path = tmp_path / "pesado.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    width, height = 2480, 3508  # an A4 page scanned at 300 dpi
    noise = pymupdf.Pixmap(pymupdf.csRGB, width, height, os.urandom(width * height * 3), False)
    page.insert_image(page.rect, pixmap=noise)
    doc.save(path)
    doc.close()

    renderer.open(path)
    ask(renderer, 0, 1.0)
    results(renderer, timeout=20.0)  # warm up: process started, document open
    ask(renderer, 0, 4.0)
    longest_gap = 0.0
    last = time.monotonic()
    found = []
    deadline = last + 30.0
    while not found and time.monotonic() < deadline:
        time.sleep(0.001)
        now = time.monotonic()
        longest_gap = max(longest_gap, now - last)
        last = now
        found = renderer.poll()
    assert found and found[0][3] is not None
    assert longest_gap < 0.05 * PATIENCE


def test_requests_no_longer_wanted_are_skipped(renderer, make_pdf):
    renderer.open(make_pdf(["Um.", "Dois."]))
    renderer.set_wanted({(1, 1.0)})
    renderer.request(0, 1.0)  # scrolled away before it was drawn
    renderer.request(1, 1.0)
    [(_, page, _, image)] = results(renderer)
    assert page == 1 and image is not None
    time.sleep(0.1)
    assert renderer.poll() == []


def test_a_page_that_cannot_be_drawn_gives_no_image(renderer, make_pdf):
    renderer.open(make_pdf(["Um."]))
    ask(renderer, 7, 1.0)  # no such page
    [(_, page, _, image)] = results(renderer)
    assert page == 7 and image is None
    ask(renderer, 0, 1.0)
    [(_, page, _, image)] = results(renderer)
    assert page == 0 and image is not None


def test_recovers_when_the_drawing_process_dies(renderer, make_pdf):
    renderer.open(make_pdf(["Um."]))
    ask(renderer, 0, 1.0)
    results(renderer)
    os.kill(renderer.worker_pid(), 9)
    time.sleep(0.1)
    ask(renderer, 0, 1.5)
    found = results(renderer, count=1)
    if found[0][3] is None:  # the request that hit the dead process
        ask(renderer, 0, 1.5)
        found = results(renderer, count=1)
    assert found[0][3] is not None


def test_switching_documents(renderer, make_pdf):
    renderer.open(make_pdf(["Primeiro."], name="a.pdf"))
    second = renderer.open(make_pdf(["Um.", "Dois.", "Três."], name="b.pdf"))
    ask(renderer, 2, 1.0)  # only the second file has a third page
    [(generation, page, _, image)] = results(renderer)
    assert (generation, page) == (second, 2) and image is not None
    renderer.open(None)
    ask(renderer, 0, 1.0)
    [(_, _, _, image)] = results(renderer)
    assert image is None
