from __future__ import annotations

import re
from typing import Iterable

from .text_utils import is_admin_heading, is_admin_text, strip_banned_phrases

_HEADING_LINE_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")

# N2 protects Markdown structures before splitting, then restores them verbatim.
_PROTECT_PATTERNS = (
    r"```.*?```",
    r"~~~.*?~~~",
    r"`[^`\n]+`",
    r"\$\$.*?\$\$",
    r"\$[^$\n]+\$",
    r"^:::[^\n]*\n.*?^:::\s*$",
    r"(?:^\|.*\|\s*$\n?)+",
    r"https?://[^\s)>\]]+",
    r"\[\[VISUAL\s+p\.\d+\]\]",
    r"\[p\.\d+\]",
)
_PROTECT_RE = re.compile("|".join(f"(?:{pattern})" for pattern in _PROTECT_PATTERNS), re.MULTILINE | re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\x00N2P(\d+)\x00")
_SENTENCE_RE = re.compile(r"[^。！？；!?;\n]+(?:[。！？；!?;]+|$)")
_BULLET_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’_-]*")
_CLAUSE_RE = re.compile(r"[^，,；;：:、]+[，,；;：:、]?")
_EN_SPLIT_RE = re.compile(r"[^,;:.!?]+[,;:.!?]?")


def _protect(text: str) -> tuple[str, dict[str, str]]:
    saved: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"\x00N2P{len(saved)}\x00"
        saved[token] = match.group(0)
        return token

    return _PROTECT_RE.sub(replace, text), saved


def _restore(text: str, saved: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return saved.get(match.group(0), match.group(0))

    return _PLACEHOLDER_RE.sub(replace, text)


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text))


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _split_cjk_clauses(text: str, limit: int = 30) -> list[str]:
    clauses = [part for part in _CLAUSE_RE.findall(text) if part]
    pieces: list[str] = []
    current = ""
    for clause in clauses:
        if len(current) + len(clause) <= limit:
            current += clause
            continue
        if current:
            pieces.append(current)
            current = ""
        while _cjk_count(clause) > limit:
            cut = 0
            count = 0
            for index, char in enumerate(clause):
                if _CJK_RE.match(char):
                    count += 1
                if count >= limit:
                    cut = index + 1
                    break
            if cut <= 0:
                break
            pieces.append(clause[:cut])
            clause = clause[cut:]
        current = clause
    if current:
        pieces.append(current)
    return pieces or [text]


def _split_en_clauses(text: str, limit: int = 18) -> list[str]:
    clauses = [part for part in _EN_SPLIT_RE.findall(text) if part.strip()]
    pieces: list[str] = []
    current: list[str] = []
    for clause in clauses:
        words = clause.split()
        if current and len(current) + len(words) > limit:
            pieces.append(" ".join(current).strip())
            current = []
        while len(words) > limit:
            pieces.append(" ".join(words[:limit]).strip())
            words = words[limit:]
        current.extend(words)
    if current:
        pieces.append(" ".join(current).strip())
    return pieces or [text.strip()]


def _terminate_pieces(pieces: list[str]) -> list[str]:
    result = [piece.strip() for piece in pieces if piece.strip()]
    for index, piece in enumerate(result[:-1]):
        if re.search(r"[，,；;：:、]$", piece):
            result[index] = re.sub(r"[，,；;：:、]$", "", piece).rstrip() + "。"
        elif not re.search(r"[。！？；!?;.]$", piece):
            result[index] = piece + "。"
    return result


def _split_long_sentence(sentence: str) -> list[str]:
    text = sentence.strip()
    if not text:
        return []
    if _cjk_count(text) > 30:
        return _terminate_pieces(_split_cjk_clauses(text))
    if _word_count(text) > 18 and not _CJK_RE.search(text):
        return _terminate_pieces(_split_en_clauses(text))
    return [text]


def _sentences(text: str) -> list[str]:
    pieces = [match.group(0).strip() for match in _SENTENCE_RE.finditer(text) if match.group(0).strip()]
    if not pieces:
        return [text.strip()] if text.strip() else []
    # A citation placeholder can become its own "sentence". Keep it attached.
    merged: list[str] = []
    for piece in pieces:
        if merged and re.fullmatch(r"\x00N2P\d+\x00", piece):
            merged[-1] += piece
        else:
            merged.append(piece)
    return merged


def _join_sentences(sentences: list[str]) -> str:
    result = ""
    for sentence in sentences:
        if not result:
            result = sentence
        elif _CJK_RE.search(sentence) and not result.endswith((" ", "\n")):
            result += sentence
        else:
            result += " " + sentence
    return result.strip()


def _process_line(line: str, language: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return [line]
    if _HEADING_RE.match(line):
        return [line]
    bullet = _BULLET_RE.match(line)
    prefix = bullet.group(1) if bullet else ""
    content = bullet.group(2).strip() if bullet else stripped
    sentences = _sentences(content)
    if not sentences:
        return [line]
    split_sentences: list[str] = []
    for sentence in sentences:
        split_sentences.extend(_split_long_sentence(sentence))

    if bullet and len(split_sentences) > 1 and _word_count(content) > 18 and not _CJK_RE.search(content):
        # English long bullets become one short bullet per sentence.
        return [prefix + sentence for sentence in split_sentences]

    if len(split_sentences) <= 3:
        return [prefix + _join_sentences(split_sentences)]
    if bullet:
        return [prefix + _join_sentences(split_sentences[index:index + 3]) for index in range(0, len(split_sentences), 3)]
    return ["\n\n".join(_join_sentences(split_sentences[index:index + 3]) for index in range(0, len(split_sentences), 3))]


def _strip_admin_blocks(text: str) -> str:
    """Drop logistics headings (with their bodies) and stray logistics lines."""
    lines = text.split("\n")
    output: list[str] = []
    skipping = 0
    for line in lines:
        match = _HEADING_LINE_RE.match(line)
        if match:
            level = len(match.group(1))
            if skipping and level > skipping:
                continue
            skipping = 0
            if is_admin_heading(match.group(2)):
                skipping = level
                continue
        elif skipping:
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith(("|", ":::")) and is_admin_text(stripped):
            continue
        output.append(line)
    return "\n".join(output)


def _drop_empty_sections(text: str) -> str:
    """Remove a heading when everything under it was filtered out."""
    lines = text.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        match = _HEADING_LINE_RE.match(lines[index])
        if not match or len(match.group(1)) < 2:
            output.append(lines[index])
            index += 1
            continue
        level = len(match.group(1))
        end = index + 1
        body: list[str] = []
        while end < len(lines):
            inner = _HEADING_LINE_RE.match(lines[end])
            if inner and len(inner.group(1)) <= level:
                break
            body.append(lines[end])
            end += 1
        meaningful = [
            line
            for line in body
            if line.strip()
            and not re.fullmatch(r"\s*\[\[VISUAL[^\]]*\]\]\s*", line.strip())
        ]
        if meaningful:
            output.extend(lines[index:end])
        index = end
    return "\n".join(output)


def _dedupe_blocks(text: str) -> str:
    blocks = re.split(r"\n{2,}", text)
    result: list[str] = []
    previous = None
    for block in blocks:
        normalized = block.strip()
        if not normalized:
            continue
        if normalized == previous:
            continue
        result.append(normalized)
        previous = normalized
    return "\n\n".join(result)


def postprocess(text: str, banned_phrases: Iterable[str] | None = None, language: str = "zh") -> str:
    """Apply N2 density rules while preserving code, formulas, tables and markers."""
    source = str(text or "")
    if not source.strip():
        return ""
    protected, saved = _protect(source)
    protected = _strip_admin_blocks(protected)
    protected = strip_banned_phrases(protected, banned_phrases or [])
    lines = protected.split("\n")
    output: list[str] = []
    for line in lines:
        if not line.strip():
            output.append("")
            continue
        output.extend(_process_line(line, language))
    processed = "\n".join(output)
    processed = re.sub(r"\n{3,}", "\n\n", processed).strip()
    processed = _dedupe_blocks(processed)
    processed = _drop_empty_sections(processed)
    return _restore(processed, saved).strip()
