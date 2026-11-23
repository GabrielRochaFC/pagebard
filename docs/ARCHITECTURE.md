# Architecture

Pagebard turns the text of a PDF into speech while showing the real pages. This
note explains how the pieces fit and the few rules that keep it stable.

## Layout

```
src/pagebard/
├── core/            no user-interface code; plain data in, plain data out
│   ├── pdf.py           text of each page plus every word's rectangle
│   ├── segmenter.py     text → sentences
│   ├── reading.py       the document as one text, tied to page geometry
│   ├── voices.py        installed voices, the catalog, downloads
│   ├── tts.py           Piper wrapper: text → 16-bit mono PCM
│   ├── export.py        PCM → MP3 through ffmpeg
│   ├── ocr.py           text recognition for scanned pages
│   ├── render_worker.py the child process (draws pages, runs OCR)
│   ├── worker_client.py talks to that process
│   ├── download.py      downloads that never leave half a file
│   ├── i18n.py          translations
│   └── paths.py         where user data lives (XDG)
├── playback/
│   ├── synth_worker.py  thread that synthesises a few sentences ahead
│   ├── player.py        feeds the sound device, reports the current sentence
│   └── audio_out.py     the sound device (Qt Multimedia)
├── ui/
│   ├── main_window.py   the window and everything the user can do
│   ├── pdf_view.py      pages, highlights, word selection, zoom
│   ├── page_renderer.py asks the child process for page images
│   ├── progress.py      cancellable progress dialog for slow work
│   ├── voice_manager.py, voice_download.py, shortcuts_dialog.py, messages.py
│   └── tasks.py         run a function on a worker thread
└── locale/          one .po file per language
```

## From page to voice

1. `pdf.load_pdf` extracts the words of every page with their rectangles, in
   the order the file stores them (that keeps columns together), and groups
   lines into paragraphs by typesetting: a line only wraps when the next word
   did not fit.
2. `reading.build_reading` joins the pages into one text and splits it into
   sentences. Any range of that text can be mapped back to rectangles on pages.
3. `SynthWorker` synthesises sentences ahead of time into a small queue.
4. `Player` pushes the audio to the device and announces each sentence as it
   starts; the window highlights it through `PdfView`.

Choosing what to read is just choosing a slice of sentences: from a clicked
word, a dragged selection, or a page range.

## Rules that matter

**Worker threads never receive Qt objects.** A Qt object freed by a thread
other than the one that owns it crashes the program, and so does a plain object
that a signal connection watches. Threads get plain values, a `queue`, and a
`threading.Event`; results come back through a queue polled by a timer
(`ui/progress.py`) or through one long-lived bridge object (`ui/tasks.py`).

**Heavy PyMuPDF work runs in a child process.** PyMuPDF holds Python's global
lock while it draws a page or runs OCR, which would freeze the window. The
child (`core/render_worker.py`) speaks a small JSON-lines protocol over its
standard input and output and exits when its input closes.

**Downloads and exports are all-or-nothing.** Files are written under a
temporary name and renamed when complete, so a cancelled download never looks
like an installed voice and a failed export never replaces a good file.

**The language is chosen once, at start-up.** Many texts are module constants
built at import time. `app.main` picks the language before importing anything
that has text; changing it in the menu takes effect on the next start.

## Audio

Voices are mono. The device stream is opened with two channels and every sample
is sent to both: a one-channel stream is wired to the left speaker only on
PipeWire.

## Tests

`pytest` runs everything without a display. Fakes for the sound device and the
synthesiser live in `tests/fakes.py`; real engines (Piper, Tesseract, ffmpeg,
the sound device with silence) are exercised where they are available and
skipped where they are not. The tests pin the interface to Portuguese; English
and Spanish are checked in fresh processes by `tests/test_i18n.py`.
