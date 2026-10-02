"""Stable OS-owned locks; process exit releases ownership without PID probing."""

from __future__ import annotations

import contextlib
import errno
import math
import os
import time
from pathlib import Path


@contextlib.contextmanager
def file_lock(path: Path, *, timeout: float = 0):
    if not math.isfinite(timeout) or not 0 <= timeout <= 60:
        raise ValueError("Lock timeout must be between 0 and 60 seconds")
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError(f"Lock path redirects: {path}")
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise ValueError(f"Another process holds the lock: {path}") from error
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
