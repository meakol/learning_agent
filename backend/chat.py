from __future__ import annotations

import re
from typing import Any

from . import progress
from .config import settings
from .prompts import load
from .retrieval import manager

_CITE_RE = re.compile(r"\[p\.(\d+)(?:\s*[-–]\s*(\d+))?\]")
_PAGE_RE = re.compile(r"第\s*(\d+|[零〇一二两三四五六七八九十百]+)\s*页|page\s*(\d+)", re.IGNORECASE)
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    total = 0
    current = 0
    for char in value:
        if char in _CN_DIGITS:
            current = _CN_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    return total + current


def page_hint(message: str) -> int | None:
    match = _PAGE_RE.search(message or "")
    if not match:
        return None
    return _cn_number(match.group(1) or match.group(2) or "")


def page_hit(doc: dict[str, Any], page: int) -> dict[str, Any] | None:
    for slide in doc.get("slides") or []:
        if int(slide.get("index") or 0) == page:
            text = "\n".join(
                part for part in ((slide.get("title") or "").strip(), (slide.get("text") or "").strip()) if part
            )
            if not text:
                return None
            return {
                "chunk_id": f"page-{page}",
                "page": page,
                "title": slide.get("title") or f"第 {page} 页",
                "text": text,
                "score": 1.0,
            }
    return None


def retrieve(
    doc: dict[str, Any],
    message: str,
    top_k: int | None = None,
    mode: str | None = None,
    embedding: dict[str, Any] | None = None,
):
    hits, actual_mode, reason = manager.search(doc, message, top_k or settings.retrieval_top_k, mode, embedding)
    hinted_page = page_hint(message)
    if hinted_page:
        hinted = page_hit(doc, hinted_page)
        if hinted:
            hits = [hinted] + [hit for hit in hits if int(hit.get("page") or 0) != hinted_page]
    return hits, actual_mode, reason


def load_history(doc_id: str, plan_id: str | None = None) -> list[dict[str, Any]]:
    return progress.load_chat(doc_id, plan_id)


def append_history(
    doc_id: str,
    plan_id: str | None,
    question: str,
    answer: str,
    citations: list[int],
) -> None:
    from datetime import datetime

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    progress.append_chat(
        doc_id,
        plan_id,
        [
            {"role": "user", "content": question, "timestamp": now},
            {
                "role": "assistant",
                "content": answer,
                "citations": citations,
                "timestamp": now,
            },
        ],
    )


def clear_history(doc_id: str, plan_id: str | None = None) -> None:
    progress.clear_chat(doc_id, plan_id)


def build_messages(
    doc: dict[str, Any],
    hits: list[dict[str, Any]],
    history: list[dict[str, Any]],
    message: str,
    general_knowledge: bool = False,
) -> list[dict[str, str]]:
    system = load("chat/system.md")
    context_parts = []
    for hit in hits:
        context_parts.append(
            f"[第 {hit['page']} 页 | {hit.get('title') or ''}]\n{hit['text']}"
        )
    context = "\n\n".join(context_parts) or "（未检索到相关片段）"
    if general_knowledge or not hits:
        user = (
            f"【课件片段】\n{context}\n\n"
            f"【问题】\n{message}\n\n"
            "课件中没有检索到直接依据。请基于通用知识回答，并在开头注明"
            "“课件中未找到直接依据，以下是通用知识解释：”。不要编造页码引用，"
            "不要假装内容来自课件；如果问题本身不适合通用知识回答，再说明限制。"
        )
    else:
        user = (
            f"【课件片段】\n{context}\n\n"
            f"【问题】\n{message}\n\n"
            "请优先依据以上片段回答；片段不足时可以使用通用知识补充，"
            "但必须区分课件依据和通用知识，并不要编造页码引用。"
        )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for item in history[-20:]:
        role = item.get("role")
        content = str(item.get("content") or "")[:1000]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user})
    return messages


def extract_citations(text: str) -> list[int]:
    pages: set[int] = set()
    for match in _CITE_RE.finditer(text or ""):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        for page in range(min(start, end), max(start, end) + 1):
            pages.add(page)
    return sorted(pages)


def validate_citations(text: str, hits: list[dict[str, Any]]) -> tuple[bool, list[int]]:
    citations = extract_citations(text)
    source_pages = {int(hit["page"]) for hit in hits}
    return bool(citations) and set(citations) <= source_pages, citations


def source_cards(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    result = []
    for hit in hits:
        page = int(hit["page"])
        if page in seen:
            continue
        seen.add(page)
        result.append(
            {
                "page": page,
                "title": hit.get("title") or f"第 {page} 页",
                "score": hit.get("score"),
                "chunk_id": hit.get("chunk_id"),
            }
        )
    return result[:5]
