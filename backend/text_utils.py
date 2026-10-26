from __future__ import annotations

import json
import re
from typing import Any, Iterable

_SENTENCE_RE = re.compile(r"(?<=[。！？；!?;])\s*|(?<=\.)\s+")
_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def estimate_tokens(chars: int) -> int:
    """Approximate mixed Chinese/English tokens used by the current project."""
    return max(1, round(max(0, chars) / 1.7))


def split_sentences(text: str) -> list[str]:
    """Split text into non-empty sentences without changing their order."""
    result: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip(" \t•·-–—*")
        if not line:
            continue
        for piece in _SENTENCE_RE.split(line):
            piece = piece.strip()
            if piece:
                result.append(piece)
    return result


def split_paragraphs(text: str, max_sentences: int = 3) -> list[str]:
    """Split long paragraphs at sentence boundaries, keeping short ones intact."""
    if max_sentences < 1:
        raise ValueError("max_sentences 必须 >= 1")
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", str(text or "")):
        block = block.strip()
        if not block:
            continue
        sentences = split_sentences(block)
        if len(sentences) <= max_sentences:
            paragraphs.append(block)
            continue
        for index in range(0, len(sentences), max_sentences):
            paragraphs.append("".join(sentences[index:index + max_sentences]))
    return paragraphs


def strip_banned_phrases(text: str, phrases: Iterable[str]) -> str:
    """Remove configured filler phrases and tidy resulting punctuation."""
    result = str(text or "")
    for phrase in sorted({p for p in phrases if p}, key=len, reverse=True):
        result = result.replace(phrase, "")
    result = re.sub(r"[，,]\s*[，,]+", "，", result)
    result = re.sub(r"([。！？；])[。！？；]+", r"\1", result)
    result = _SPACE_RE.sub(" ", result)
    result = _MULTI_BLANK_RE.sub("\n\n", result)
    return result


def extract_json(text: str) -> Any:
    """Extract the first balanced JSON object/array from model prose or fences."""
    source = str(text or "").strip()
    source = re.sub(r"^```(?:json)?\s*|\s*```$", "", source, flags=re.IGNORECASE).strip()
    start = min(
        (index for index in (source.find("{"), source.find("[")) if index >= 0),
        default=-1,
    )
    if start < 0:
        raise ValueError("模型没有返回 JSON。")
    opening = source[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return json.loads(source[start:index + 1])
    raise ValueError("模型返回的 JSON 不完整。")


def normalize_text(text: str) -> str:
    return re.sub(
        r"[\s，。！？；：、,.!?;:'\"“”‘’()（）\[\]【】]",
        "",
        str(text or ""),
    ).lower()


def longest_common_substring(left: str, right: str) -> str:
    """Return the longest common contiguous substring (used for quote checks)."""
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return ""
    previous = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i, ch in enumerate(a, 1):
        current = [0] * (len(b) + 1)
        for j, other in enumerate(b, 1):
            if ch == other:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len = current[j]
                    best_end = i
        previous = current
    return a[best_end - best_len:best_end]


def slugify(value: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._-")
    return (slug or "default")[:max_length]
