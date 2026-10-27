from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

from .config import settings
from .llm import LLMConfig, LLMError, stream_chat
from .notes import build_chunk_messages, local_notes
from .postprocess import postprocess
from .prompts import load
from .text_utils import strip_admin_lines


@dataclass(frozen=True)
class Chunk:
    index: int
    page_start: int
    page_end: int
    slides: list[dict[str, Any]]
    text: str
    truncated: bool = False


def _page_body(slide: dict[str, Any]) -> str:
    text = strip_admin_lines((slide.get("text") or "").strip())
    notes = strip_admin_lines((slide.get("notes") or "").strip())
    if notes:
        text = f"{text}\n[讲者备注] {notes}" if text else f"[讲者备注] {notes}"
    return text


def _page_block(slide: dict[str, Any], body: str) -> str:
    title = slide.get("title") or "未命名"
    return f"<<< 第 {slide.get('index')} 页 | {title} >>>\n{body}"


def chunk_budget_chars(
    context_tokens: int | None = None,
    max_output_tokens: int = 4096,
    chunk_chars: int | None = None,
) -> int:
    """Return the effective per-chunk character budget."""
    context = max(1024, context_tokens or settings.model_context_tokens)
    output = max(512, max_output_tokens)
    token_budget = max(512, context - output - 1000)
    by_tokens = int(token_budget * 0.7 * 1.7)
    configured = max(500, chunk_chars or settings.pipeline_chunk_chars)
    return max(500, min(configured, by_tokens))


def plan_chunks(
    doc: dict[str, Any],
    *,
    max_pages: int | None = None,
    max_chars: int | None = None,
    context_tokens: int | None = None,
    max_output_tokens: int = 4096,
) -> list[Chunk]:
    """Split slides at page boundaries without exceeding the per-chunk budget."""
    slides = doc.get("slides") or []
    page_limit = max(1, max_pages or settings.pipeline_max_pages_per_chunk)
    budget = chunk_budget_chars(context_tokens, max_output_tokens, max_chars)

    chunks: list[Chunk] = []
    current: list[dict[str, Any]] = []
    current_text = ""
    truncated = False

    def flush() -> None:
        nonlocal current, current_text, truncated
        if not current:
            return
        chunks.append(
            Chunk(
                index=len(chunks) + 1,
                page_start=int(current[0].get("index") or 1),
                page_end=int(current[-1].get("index") or 1),
                slides=list(current),
                text=current_text.strip(),
                truncated=truncated,
            )
        )
        current = []
        current_text = ""
        truncated = False

    for slide in slides:
        body = _page_body(slide)
        if not body:
            continue
        page_index = int(slide.get("index") or 0)
        block = _page_block(slide, body)
        if len(block) > budget:
            flush()
            clipped = body[: max(0, budget - 80)].rstrip()
            current = [slide]
            current_text = _page_block(slide, clipped + " …")
            truncated = True
            flush()
            continue

        would_pages = len(current) + 1
        would_chars = len(current_text) + (2 if current_text else 0) + len(block)
        if current and (would_pages > page_limit or would_chars > budget):
            flush()

        current.append(slide)
        current_text = f"{current_text}\n\n{block}" if current_text else block
        if len(current) >= page_limit or page_index <= 0:
            flush()

    flush()
    return chunks


def _chunk_doc(doc: dict[str, Any], chunk: Chunk) -> dict[str, Any]:
    result = dict(doc)
    result["page_count"] = len(chunk.slides)
    result["slides"] = chunk.slides
    return result


def _banned_phrases() -> list[str]:
    try:
        return [line.strip() for line in load("rules/banned_phrases.txt").splitlines() if line.strip()]
    except Exception:
        return []


def _dedupe(previous: str, text: str) -> str:
    if not previous:
        return text
    seen = {part.strip() for part in previous.split("\n\n") if part.strip()}
    parts = [part for part in text.split("\n\n") if part.strip() and part.strip() not in seen]
    return "\n\n".join(parts)


async def _run_chunk(
    doc: dict[str, Any],
    chunk: Chunk,
    language: str,
    level: int,
    focus: str,
    api: LLMConfig,
    max_tokens: int,
) -> tuple[str, dict[str, int], bool, int]:
    messages = build_chunk_messages(doc, chunk.slides, language, level, focus)
    input_chars = sum(len(str(message.get("content", ""))) for message in messages)
    chunk_usage: dict[str, int] = {}
    last_error: LLMError | None = None
    for attempt in range(max(0, settings.pipeline_max_retries) + 1):
        try:
            parts: list[str] = []
            async for delta in stream_chat(messages, api, max_tokens=max_tokens, usage=chunk_usage):
                parts.append(delta)
            text = "".join(parts).strip()
            if not text:
                raise LLMError("模型没有返回内容。")
            text = postprocess(text, _banned_phrases(), language)
            return text, chunk_usage, False, input_chars
        except LLMError as exc:
            last_error = exc
            if attempt < settings.pipeline_max_retries:
                await asyncio.sleep(min(2.0, 1.0 + attempt))
    local = local_notes(_chunk_doc(doc, chunk), language, level, "分段生成失败，已使用本地摘录")
    if local.strip():
        return postprocess(local, _banned_phrases(), language), {}, True, input_chars
    raise last_error or LLMError("分段生成失败。")


async def _chunk_events(
    doc: dict[str, Any],
    chunks: list[Chunk],
    language: str,
    level: int,
    focus: str,
    api: LLMConfig,
    max_tokens: int,
) -> AsyncIterator[dict[str, Any]]:
    """Run chunks concurrently but yield results strictly in page order."""
    concurrency = max(1, settings.pipeline_concurrency)
    if concurrency <= 1:
        for chunk in chunks:
            yield {"type": "status", "stage": f"分段 {chunk.index}/{len(chunks)}"}
            result = await _run_chunk(doc, chunk, language, level, focus, api, max_tokens)
            yield {"type": "result", "chunk": chunk, "result": result}
        return

    semaphore = asyncio.Semaphore(concurrency)

    async def run(chunk: Chunk) -> tuple[str, dict[str, int], bool, int]:
        async with semaphore:
            return await _run_chunk(doc, chunk, language, level, focus, api, max_tokens)

    tasks = [asyncio.create_task(run(chunk)) for chunk in chunks]
    try:
        for chunk, task in zip(chunks, tasks):
            yield {"type": "status", "stage": f"分段 {chunk.index}/{len(chunks)}"}
            result = await task
            yield {"type": "result", "chunk": chunk, "result": result}
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def stream_notes(
    doc: dict[str, Any],
    language: str,
    level: int,
    focus: str,
    api: LLMConfig,
    max_tokens: int,
    usage: dict[str, int] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield pipeline SSE events; chunks are buffered to preserve page order."""
    chunks = plan_chunks(doc)
    if not chunks:
        raise LLMError("课件没有可用于生成笔记的文本。")
    total_chars = 0
    total_input_chars = 0
    fallback_chunks = 0
    all_usage: dict[str, int] = {}
    previous = ""
    async for event in _chunk_events(doc, chunks, language, level, focus, api, max_tokens):
        if event["type"] == "status":
            yield event
            continue
        chunk = event["chunk"]
        text, chunk_usage, fallback, input_chars = event["result"]
        total_input_chars += input_chars
        if fallback:
            fallback_chunks += 1
            yield {
                "type": "notice",
                "message": f"第 {chunk.page_start}–{chunk.page_end} 页生成失败，已使用本地摘录。",
            }
        for key, value in chunk_usage.items():
            all_usage[key] = all_usage.get(key, 0) + int(value)
        text = _dedupe(previous, text)
        # Do not inject prose transition prompts into the user-facing notes.
        # The SSE status event already reports chunk progress.
        previous = f"{previous}\n\n{text}" if previous else text
        total_chars += len(text)
        if text:
            yield {"type": "delta", "text": text}
    if usage is not None:
        usage.update(all_usage)
    yield {
        "type": "done",
        "chars": total_chars,
        "input_chars": total_input_chars,
        "usage": all_usage,
        "chunks": len(chunks),
        "fallback_chunks": fallback_chunks,
        "concurrency": max(1, settings.pipeline_concurrency),
        "degraded": fallback_chunks > 0,
    }
