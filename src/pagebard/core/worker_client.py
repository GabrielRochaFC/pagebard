"""Talk to the child process that does the heavy PyMuPDF work.

See core/render_worker.py for what the process does and the protocol.
"""

import json
import subprocess
import sys
import threading

_WORKER_COMMAND = [sys.executable, "-P", "-m", "pagebard.core.render_worker"]


class WorkerProcess:
    """One child process, started when first needed and replaced if it dies."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None

    def exchange(self, request: dict) -> tuple[dict, bytes] | None:
        """Send one request and read its reply; None if the process failed."""
        try:
            process = self._ensure()
            process.stdin.write(json.dumps(request).encode() + b"\n")
            process.stdin.flush()
            header = json.loads(process.stdout.readline())
            size = header.get("size", 0)
            payload = process.stdout.read(size) if size else b""
            if len(payload) != size:
                raise OSError("worker closed its output")
            return header, payload
        except (OSError, ValueError):
            self.stop()
            return None

    def pid(self) -> int | None:
        """Process id while the process is alive."""
        process = self._process
        return process.pid if process is not None and process.poll() is None else None

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()  # closing its input is what tells it to exit
            except OSError:
                pass
        # Reaped in the background: it may still be busy starting or working.
        threading.Thread(target=_reap, args=(process,), daemon=True).start()

    def _ensure(self) -> subprocess.Popen:
        if self._process is None or self._process.poll() is not None:
            self._process = subprocess.Popen(
                _WORKER_COMMAND,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        return self._process


def _reap(process: subprocess.Popen) -> None:
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
