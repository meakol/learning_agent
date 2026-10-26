from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi

from ..config import DATA_DIR, settings
from ..text_utils import split_sentences

INDEX_ROOT = DATA_DIR / "index_bm25"
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_STOP_GRAMS = {
    "什么", "怎么", "如何", "为什", "是什", "么是", "解释", "意思", "请问",
    "可以", "是否", "哪些", "这个", "那个", "一下", "关于", "以及", "就是",
}
_QUERY_STOPWORDS = {
    "什么", "怎么", "如何", "为什么", "为何", "请问", "解释", "意思", "哪些",
    "这个", "那个", "一下", "关于", "以及", "就是", "可以", "能否", "是否",
    "the", "a", "an", "is", "are", "what", "how", "why", "please", "explain",
}


def index_dir(doc_id: str) -> Path:
    return INDEX_ROOT / doc_id


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def doc_hash(doc: dict[str, Any]) -> str:
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "sha1:" + hashlib.sha1(raw).hexdigest()


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in jieba.lcut((text or "").lower()):
        word = word.strip()
        if len(word) < 2 and not _WORD_RE.fullmatch(word):
            continue
        if word and not word.isspace():
            tokens.append(word)
    tokens.extend(_WORD_RE.findall((text or "").lower()))
    return tokens


def _grams(text: str) -> set[str]:
    normalized = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", (text or "").lower()))
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    grams = {normalized[index:index + 2] for index in range(len(normalized) - 1)}
    grams.update(re.findall(r"[a-z0-9]{2,}", normalized))
    return grams


def _lexical_fallback(chunks: list[dict[str, Any]], query: str, top_k: int) -> list[dict[str, Any]]:
    """Character n-gram overlap for paraphrases BM25 tokenization misses."""
    query_grams = _grams(query)
    if not query_grams:
        return []
    ranked: list[tuple[float, int]] = []
    meaningful_query = query_grams - _STOP_GRAMS
    if len(meaningful_query) < 2:
        return []
    for index, chunk in enumerate(chunks):
        chunk_grams = _grams((chunk.get("title") or "") + "\n" + (chunk.get("text") or ""))
        overlap = meaningful_query & (chunk_grams - _STOP_GRAMS)
        if len(overlap) < 2:
            continue
        score = len(overlap) / max(1.0, (len(meaningful_query) * len(chunk_grams)) ** 0.5)
        if score < 0.12:
            continue
        ranked.append((score, index))
    results = []
    for score, index in sorted(ranked, reverse=True)[: max(1, top_k)]:
        item = dict(chunks[index])
        item["score"] = round(float(score), 4)
        item["mode"] = "keyword"
        results.append(item)
    return results


def _split(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    pieces = []
    current = ""
    for sentence in split_sentences(text):
        if len(current) + len(sentence) > size and current:
            pieces.append(current)
            current = ""
        while len(sentence) > size:
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        current += sentence
    if current.strip():
        pieces.append(current)
    return pieces


def build(doc: dict[str, Any]) -> dict[str, Any]:
    doc_id = doc["doc_id"]
    folder = index_dir(doc_id)
    chunks = []
    for slide in doc.get("slides", []):
        page = int(slide.get("index") or 0)
        title = slide.get("title") or f"第 {page} 页"
        text = (slide.get("text") or "").strip()
        notes = (slide.get("notes") or "").strip()
        body = f"{title}\n{text}" + (f"\n{notes}" if notes else "")
        for number, piece in enumerate(_split(body, settings.bm25_chunk_chars), 1):
            if not piece.strip():
                continue
            chunks.append(
                {
                    "chunk_id": f"p{page}_c{number}",
                    "page": page,
                    "title": title,
                    "text": piece,
                    "tokens": tokenize(piece),
                }
            )
    meta = {
        "doc_id": doc_id,
        "mode": "keyword",
        "model": None,
        "dimension": 0,
        "max_tokens": None,
        "chunk_count": len(chunks),
        "doc_hash": doc_hash(doc),
        "created_at": _now(),
        "app_version": "1.0.0",
    }
    _write(folder / "chunks.json", chunks)
    _write(folder / "meta.json", meta)
    return meta


def metadata(doc_id: str) -> dict[str, Any] | None:
    return _read(index_dir(doc_id) / "meta.json", None)


def chunks(doc_id: str) -> list[dict[str, Any]]:
    return _read(index_dir(doc_id) / "chunks.json", [])


def load(doc_id: str) -> tuple[list[dict[str, Any]], BM25Okapi] | None:
    chunks = _read(index_dir(doc_id) / "chunks.json", [])
    if not chunks:
        return None
    return chunks, BM25Okapi([item.get("tokens") or [] for item in chunks])


def search(doc_id: str, query: str, top_k: int = 6) -> list[dict[str, Any]]:
    loaded = load(doc_id)
    if not loaded:
        return []
    chunks, bm25 = loaded
    tokens = [token for token in tokenize(query) if token not in _QUERY_STOPWORDS]
    results = []
    if tokens:
        scores = bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)[: max(1, top_k)]
        for index, score in ranked:
            if float(score) <= 0:
                continue
            item = dict(chunks[index])
            item["score"] = round(float(score), 4)
            item["mode"] = "keyword"
            results.append(item)
    if not results:
        results = _lexical_fallback(chunks, query, top_k)
    return results


def delete(doc_id: str) -> None:
    folder = index_dir(doc_id)
    if folder.is_dir():
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
