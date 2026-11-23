"""Child process that draws PDF pages; run as `python -m pagebard.core.render_worker`.

PyMuPDF keeps Python's global lock while it draws a page, so drawing inside
the application would freeze its window on heavy pages. This process does
the drawing instead and talks over its standard input and output:

    request  (one JSON line):  {"op": "open", "path": "..." | null}
                               {"op": "render", "page": 0, "scale": 1.5}
                               {"op": "ocr", "page": 0, "language": "por",
                                "tessdata": "/folder", "dpi": 300}
    reply    (one JSON line):  {"ok": true | false, ...}
             for a successful render the line also carries "width", "height",
             "stride" and "size", and is followed by `size` bytes of RGB pixels;
             for a successful ocr it carries "size" and is followed by `size`
             bytes of JSON: the words found, each as
             [x0, y0, x1, y1, text, block, line, number], in the coordinates of
             the page as it is displayed.

It ends when its input is closed, which also happens if the application dies.
"""

import json
import sys

import pymupdf


def main() -> int:
    requests, replies = sys.stdin.buffer, sys.stdout.buffer
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    doc = None
    for line in requests:
        try:
            request = json.loads(line)
            if request["op"] == "open":
                if doc is not None:
                    doc.close()
                    doc = None
                if request["path"] is not None:
                    doc = pymupdf.open(request["path"])
                _reply(replies, {"ok": True})
            elif request["op"] == "ocr":
                words = _recognize(doc[request["page"]], request)
                payload = json.dumps(words).encode()
                _reply(replies, {"ok": True, "size": len(payload)}, payload)
            else:
                scale = request["scale"]
                pixmap = doc[request["page"]].get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                pixels = pixmap.samples
                header = {
                    "ok": True,
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "stride": pixmap.stride,
                    "size": len(pixels),
                }
                _reply(replies, header, pixels)
        except Exception:
            _reply(replies, {"ok": False})
    return 0


_OCR_MAX_SIDE_PIXELS = 4000
_SCREEN_DPI = 72


def ocr_dpi(width: float, height: float, wanted: int = 300) -> int:
    """Resolution to recognize a page of that size (in points) at.

    The picture is capped at 4000 pixels on its longer side: an oversized page
    at full resolution takes gigabytes of memory and minutes of work.
    """
    limit = int(_OCR_MAX_SIDE_PIXELS * 72 / max(width, height, 1.0))
    return max(_SCREEN_DPI, min(wanted, limit))


def _recognize(page: pymupdf.Page, request: dict) -> list:
    """Words read from the page as it is displayed.

    The picture of the page is placed on a fresh, unrotated page first: scans
    are often stored turned, and recognizing the stored orientation misses the
    text or returns coordinates that do not match what is on screen.
    """
    dpi = ocr_dpi(page.rect.width, page.rect.height, request.get("dpi", 300))
    picture = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    scratch = pymupdf.open()
    try:
        flat = scratch.new_page(width=page.rect.width, height=page.rect.height)
        flat.insert_image(flat.rect, pixmap=picture)
        textpage = flat.get_textpage_ocr(
            language=request["language"], dpi=dpi, full=True, tessdata=request["tessdata"]
        )
        words = flat.get_text("words", textpage=textpage, sort=False)
    finally:
        scratch.close()
    return [list(word) for word in words]


def _reply(replies, header: dict, payload: bytes = b"") -> None:
    replies.write(json.dumps(header).encode() + b"\n")
    replies.write(payload)
    replies.flush()


if __name__ == "__main__":
    raise SystemExit(main())
