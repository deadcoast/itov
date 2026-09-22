"""Standalone log redirection before the stock observer initializes CUDA."""

import os
import runpy
import sys

if __name__ == "__main__":
    with open(sys.argv[1], "xb", buffering=0) as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        # ComfyUI wraps these buffers without retaining the original TextIOWrapper.
        # Keep owners alive so replacement of sys.stdout/stderr cannot close a buffer.
        stdout_stream = os.fdopen(1, "w", encoding="utf-8", buffering=1, closefd=False)
        stderr_stream = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)
        sys.stdout, sys.stderr = stdout_stream, stderr_stream
        sys.argv = sys.argv[2:]
        runpy.run_path(sys.argv[0], run_name="__main__")
