"""Plain-text extraction for review snippets; no scanning or report output."""
from __future__ import annotations

import html
import re


def text_of(data: bytes) -> str:
    """Strip markup and collapse whitespace, preserving ruby readings.

    Source-term lookup must remove rt/rp first. Review snippets retain them
    so that changes to readings remain visible to the diff classifier.
    """
    text = data.decode("utf-8", errors="ignore")
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()
