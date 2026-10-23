"""Shared UTF-8 initialization for tool stdout and stderr.

Only CLI entrypoints call this function. Importing a tool as a library must not
reconfigure the embedding application's streams.
"""
from __future__ import annotations

import sys


def configure_output() -> None:
    """Use UTF-8 on both console and redirected streams; accept capture streams."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                # Closed or read-only capture streams cannot be reconfigured.
                pass
