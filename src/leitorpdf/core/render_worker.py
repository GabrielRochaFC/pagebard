"""Child process that draws PDF pages; run as `python -m leitorpdf.core.render_worker`.

PyMuPDF keeps Python's global lock while it draws a page, so drawing inside
the application would freeze its window on heavy pages. This process does
the drawing instead and talks over its standard input and output:

    request  (one JSON line):  {"op": "open", "path": "..." | null}
                               {"op": "render", "page": 0, "scale": 1.5}
    reply    (one JSON line):  {"ok": true | false, ...}
             for a successful render the line also carries "width", "height",
             "stride" and "size", and is followed by `size` bytes of RGB pixels.

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


def _reply(replies, header: dict, payload: bytes = b"") -> None:
    replies.write(json.dumps(header).encode() + b"\n")
    replies.write(payload)
    replies.flush()


if __name__ == "__main__":
    raise SystemExit(main())
