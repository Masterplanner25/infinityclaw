"""BlockStreamer — splits a completed response into semantic blocks for delivery."""
from __future__ import annotations

import re


def split_blocks(text: str, max_block: int = 3500) -> list[str]:
    """Split *text* into deliverable blocks.

    Splits at paragraph boundaries, then hard-wraps blocks that exceed
    *max_block* characters. Designed for channels with message length limits.
    """
    if not text.strip():
        return []

    paragraphs = re.split(r"\n{2,}", text)
    blocks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_block:
            current = candidate
        else:
            if current:
                blocks.append(current)
            # Hard-wrap oversized paragraph
            if len(para) > max_block:
                blocks.extend(_hard_wrap(para, max_block))
                current = ""
            else:
                current = para

    if current:
        blocks.append(current)

    return blocks


def _hard_wrap(text: str, limit: int) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks
