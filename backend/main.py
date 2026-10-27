from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (
    FRONTEND_DIR,
    MODEL_PRICING,
    PROVIDERS,
    SAMPLES_DIR,
    estimate_tokens,
    pricing_for,
    settings,
)
from . import chat, plans, progress, quiz
from .llm import LLMConfig, LLMError, stream_chat
from .logging_utils import TraceIdMiddleware, setup_logging
from .notes import LEVELS, build_messages, level_info, local_notes
from .parser import ParseError, parse_document
from .pipeline import stream_notes as stream_pipeline
from .retrieval import manager
from .storage import store

FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
(FRONTEND_DIR / "css").mkdir(exist_ok=True)
(FRONTEND_DIR / "js").mkdir(exist_ok=True)

setup_logging(settings.log_level)
app = FastAPI(title="课堂笔记智能体", version="1.0.0")
app.add_middleware(TraceIdMiddleware)


class ApiConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class NotesRequest(BaseModel):
    doc_id: str
    language: Literal["zh", "en", "bilingual"] = "zh"
    level: int = Field(default=3, ge=1, le=5)
    focus: str = ""
    force_local: bool = False
    api: ApiConfig | None = None


class PlanRequest(BaseModel):
    doc_id: str
    user_id: str = "local"
    total_days: int = Field(ge=1, le=30)
    daily_minutes: int = Field(ge=10, le=480)
    difficulty: int = Field(default=3, ge=1, le=5)
    force_fallback: bool = False
    api: ApiConfig | None = None


class ProgressPageRequest(BaseModel):
    page: int = Field(ge=1)
    completed: bool = True


class QuizRequest(BaseModel):
    doc_id: str
    plan_id: str
    milestone_id: str
    question_count: int = Field(default=5, ge=1, le=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    force: bool = False
    force_fallback: bool = False
    api: ApiConfig | None = None


class QuizAnswer(BaseModel):
    question_id: str
    selected: str


class QuizSubmit(BaseModel):
    answers: list[QuizAnswer]


class EmbeddingConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    device: str = ""


class ChatRequest(BaseModel):
    doc_id: str
    user_id: str = "local"
    plan_id: str | None = None
    message: str = Field(min_length=1, max_length=500)
    conversation_history: list[dict] | None = None
    api: ApiConfig | None = None
    retrieval_mode: str | None = None
    embedding: EmbeddingConfig | None = None


class RebuildRequest(BaseModel):
    doc_id: str
    mode: str | None = None
    embedding: EmbeddingConfig | None = None


class CheckQuery(BaseModel):
    query: str
    expected_pages: list[int] = []


class CheckRequest(BaseModel):
    doc_id: str
    queries: list[CheckQuery]
    top_k: int = Field(default=5, ge=1, le=10)
    mode: str | None = None
    embedding: EmbeddingConfig | None = None


def _resolve_api(api: ApiConfig | None) -> LLMConfig:
    api = api or ApiConfig()
    return LLMConfig(
        base_url=(api.base_url or settings.base_url).strip(),
        model=(api.model or settings.model).strip(),
        api_key=(api.api_key or settings.api_key).strip(),
        temperature=(
            api.temperature if api.temperature is not None else settings.temperature
        ),
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _safe_filename(name: str) -> str:
    name = Path(name or "slides").name
    name = re.sub(r"[^\w\-. \u4e00-\u9fff()（）]+", "_", name)
    return name[:120] or "slides"


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": app.version,
        "llm_configured": settings.llm_configured,
        "retrieval_mode": settings.retrieval_mode,
        "pipeline_enabled": settings.pipeline_enabled,
        "llm_transport": "stream",
        "plan_timeout_seconds": settings.plan_timeout_seconds,
        "quiz_timeout_seconds": settings.quiz_timeout_seconds,
    }


@app.get("/api/config")
async def public_config() -> dict:
    return {
        "llm_configured": settings.llm_configured,
        "defaults": {
            "base_url": settings.base_url,
            "model": settings.model,
            "temperature": settings.temperature,
        },
        "providers": PROVIDERS,
        "model_pricing": {
            name: {"input": prices[0], "output": prices[1], "currency": "USD"}
            for name, prices in MODEL_PRICING.items()
        },
        "levels": LEVELS,
        "max_upload_mb": settings.max_upload_mb,
        "max_slides": settings.max_slides,
        "retrieval": {
            "mode": settings.retrieval_mode,
            "top_k": settings.retrieval_top_k,
            "embedding_configured": bool(settings.embedding_base_url and settings.embedding_model),
            "available_modes": ["keyword", "local_vector", "remote_api", "hybrid"],
        },
        "pipeline": {
            "enabled": settings.pipeline_enabled,
            "chunk_chars": settings.pipeline_chunk_chars,
            "max_pages_per_chunk": settings.pipeline_max_pages_per_chunk,
            "concurrency": settings.pipeline_concurrency,
        },
        "learning": {"max_plans_per_doc": 50, "max_questions_per_quiz": 10},
    }


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    original = _safe_filename(file.filename or "slides.pptx")
    suffix = Path(original).suffix.lower()
    if suffix not in (".pptx", ".pdf", ".ppt"):
        raise HTTPException(400, "仅支持 .pptx 和 .pdf 文件（旧版 .ppt 请先另存为 .pptx）。")

    declared = request.headers.get("content-length")
    limit = settings.max_upload_mb * 1024 * 1024
    if declared and declared.isdigit() and int(declared) > limit + 2 * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {settings.max_upload_mb} MB 限制。")

    doc_id, doc_dir = store.new_doc_dir()
    source = doc_dir / f"source{suffix}"
    size = 0
    try:
        with source.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"文件超过 {settings.max_upload_mb} MB 限制。")
                handle.write(chunk)
    except HTTPException:
        store.delete(doc_id)
        raise
    except Exception as exc:  # noqa: BLE001
        store.delete(doc_id)
        raise HTTPException(500, f"文件保存失败：{exc}") from exc
    finally:
        await file.close()

    if size == 0:
        store.delete(doc_id)
        raise HTTPException(400, "文件为空，请重新选择。")

    try:
        doc = await asyncio.to_thread(parse_document, source, doc_id, doc_dir)
    except ParseError as exc:
        store.delete(doc_id)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        store.delete(doc_id)
        raise HTTPException(500, f"解析课件失败：{exc}") from exc
    finally:
        source.unlink(missing_ok=True)

    doc["filename"] = original
    store.save(doc)
    return JSONResponse(doc)


@app.get("/api/doc/{doc_id}")
async def get_doc(doc_id: str) -> JSONResponse:
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "课件不存在或已过期，请重新上传。")
    return JSONResponse(doc)


@app.get("/api/doc/{doc_id}/pages/{name}")
async def get_page_image(doc_id: str, name: str) -> FileResponse:
    if not re.fullmatch(r"p\d+\.png", name):
        raise HTTPException(404, "页面不存在。")
    doc_dir = store.doc_dir(doc_id)
    if not doc_dir:
        raise HTTPException(404, "课件不存在。")
    path = doc_dir / "pages" / name
    if not path.exists():
        raise HTTPException(404, "页面不存在。")
    return FileResponse(path, media_type="image/png")


@app.get("/api/doc/{doc_id}/media/{name}")
async def get_media(doc_id: str, name: str) -> FileResponse:
    if not re.fullmatch(r"[\w.\-]+", name):
        raise HTTPException(404, "资源不存在。")
    doc_dir = store.doc_dir(doc_id)
    if not doc_dir:
        raise HTTPException(404, "课件不存在。")
    path = (doc_dir / "media" / name).resolve()
    if doc_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "资源不存在。")
    return FileResponse(path)


@app.post("/api/demo")
async def demo(kind: str = "pptx") -> JSONResponse:
    if kind not in ("pptx", "pdf"):
        raise HTTPException(400, "示例类型仅支持 pptx 或 pdf。")
    sample = SAMPLES_DIR / ("demo.pptx" if kind == "pptx" else "demo.pdf")
    if not sample.exists():
        raise HTTPException(404, "示例课件不存在，请直接上传课件。")
    doc_id, doc_dir = store.new_doc_dir()
    try:
        doc = await asyncio.to_thread(parse_document, sample, doc_id, doc_dir)
    except Exception as exc:  # noqa: BLE001
        store.delete(doc_id)
        raise HTTPException(500, f"示例课件解析失败：{exc}") from exc
    doc["filename"] = (
        "示例课件：Transformer 与注意力机制.pptx"
        if kind == "pptx"
        else "示例课件：机器学习基础.pdf"
    )
    store.save(doc)
    return JSONResponse(doc)


@app.post("/api/notes/stream")
async def notes_stream(payload: NotesRequest, request: Request) -> StreamingResponse:
    doc = store.get(payload.doc_id)
    if not doc:
        raise HTTPException(404, "课件不存在或已过期，请重新上传。")

    api = _resolve_api(payload.api)
    level = max(1, min(5, payload.level))
    language = payload.language
    info = level_info(level)
    max_tokens = 6144 if level >= 4 else 4096
    mode = "local" if (payload.force_local or not api.api_key) else "llm"
    started = time.perf_counter()

    async def generate() -> AsyncIterator[str]:
        try:
            yield _sse(
                {
                    "type": "meta",
                    "mode": mode,
                    "model": api.model if mode == "llm" else "local-extractive",
                    "language": language,
                    "level": level,
                    "level_name": info["zh"],
                    "pages": doc.get("page_count", 0),
                    "filename": doc.get("filename", ""),
                    "pipeline": mode == "llm" and settings.pipeline_enabled,
                }
            )
            if mode == "local":
                yield _sse({"type": "status", "stage": "读取课件文本"})
                await asyncio.sleep(0.05)
                reason = (
                    "已选择本地摘录模式"
                    if payload.force_local
                    else "未配置大模型 API Key"
                )
                text = await asyncio.to_thread(local_notes, doc, language, level, reason)
                yield _sse({"type": "status", "stage": "抽取知识点"})
                buffer = ""
                for line in text.splitlines(keepends=True):
                    buffer += line
                    if len(buffer) >= 60 or line.endswith("\n\n"):
                        yield _sse({"type": "delta", "text": buffer})
                        buffer = ""
                        await asyncio.sleep(0.012)
                if buffer:
                    yield _sse({"type": "delta", "text": buffer})
                yield _sse(
                    {
                        "type": "done",
                        "chars": len(text),
                        "elapsed": round(time.perf_counter() - started, 2),
                        "mode": "local",
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": estimate_tokens(len(text)),
                            "estimated": True,
                        },
                        "cost": {
                            "usd": 0.0,
                            "currency": "USD",
                            "estimated": True,
                            "free": True,
                        },
                    }
                )
                return

            if settings.pipeline_enabled:
                pipeline_usage: dict[str, int] = {}
                async for event in stream_pipeline(
                    doc, language, level, payload.focus, api, max_tokens, pipeline_usage
                ):
                    if await request.is_disconnected():
                        return
                    if event.get("type") == "done":
                        chars = int(event.get("chars") or 0)
                        input_chars = int(event.get("input_chars") or 0)
                        used = event.get("usage") or {}
                        actual_input = used.get("prompt_tokens") or used.get("input_tokens")
                        actual_output = used.get("completion_tokens") or used.get("output_tokens")
                        input_tokens = int(actual_input or estimate_tokens(input_chars))
                        output_tokens = int(actual_output or estimate_tokens(chars))
                        pricing = pricing_for(api.base_url, api.model)
                        cost = None
                        if pricing:
                            usd = (
                                input_tokens / 1_000_000 * float(pricing["input"])
                                + output_tokens / 1_000_000 * float(pricing["output"])
                            )
                            cost = {
                                "usd": round(usd, 6),
                                "currency": pricing.get("currency", "USD"),
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "estimated": not bool(actual_input or actual_output),
                                "pricing": pricing,
                            }
                        yield _sse(
                            {
                                "type": "done",
                                "chars": chars,
                                "elapsed": round(time.perf_counter() - started, 2),
                                "mode": "llm",
                                "usage": {
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "estimated": not bool(actual_input or actual_output),
                                    "calls": int(event.get("chunks") or 0),
                                    "chunks": int(event.get("chunks") or 0),
                                    "fallback_chunks": int(event.get("fallback_chunks") or 0),
                                },
                                "cost": cost,
                                "pipeline": True,
                                "degraded": bool(event.get("degraded")),
                                "chunks": int(event.get("chunks") or 0),
                                "fallback_chunks": int(event.get("fallback_chunks") or 0),
                            }
                        )
                    else:
                        yield _sse(event)
                return

            messages, truncated = build_messages(
                doc, language, level, settings.max_context_chars, payload.focus
            )
            if truncated:
                yield _sse(
                    {
                        "type": "notice",
                        "message": "课件文字较多，已按上下文上限截断部分内容。",
                    }
                )
            yield _sse({"type": "status", "stage": "理解课件结构"})
            yield _sse({"type": "status", "stage": f"按「{info['zh']}」难度提炼知识点"})
            chunks = 0
            usage: dict[str, int] = {}
            async for delta in stream_chat(
                messages, api, max_tokens=max_tokens, usage=usage
            ):
                if await request.is_disconnected():
                    return
                chunks += len(delta)
                yield _sse({"type": "delta", "text": delta})

            input_chars = sum(len(message.get("content", "")) for message in messages)
            actual_input = usage.get("prompt_tokens") or usage.get("input_tokens")
            actual_output = usage.get("completion_tokens") or usage.get("output_tokens")
            input_tokens = int(actual_input or estimate_tokens(input_chars))
            output_tokens = int(actual_output or estimate_tokens(chunks))
            pricing = pricing_for(api.base_url, api.model)
            cost = None
            if pricing:
                usd = (
                    input_tokens / 1_000_000 * float(pricing["input"])
                    + output_tokens / 1_000_000 * float(pricing["output"])
                )
                cost = {
                    "usd": round(usd, 6),
                    "currency": pricing.get("currency", "USD"),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated": not bool(actual_input or actual_output),
                    "pricing": pricing,
                }
            yield _sse(
                {
                    "type": "done",
                    "chars": chunks,
                    "elapsed": round(time.perf_counter() - started, 2),
                    "mode": "llm",
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "estimated": not bool(actual_input or actual_output),
                    },
                    "cost": cost,
                }
            )
        except LLMError as exc:
            yield _sse(
                {
                    "type": "error",
                    "message": exc.message,
                    "status": exc.status,
                    "can_fallback": True,
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield _sse(
                {"type": "error", "message": f"生成失败：{exc}", "can_fallback": True}
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Learning features: documents, plans, progress, quizzes, retrieval, chat
# --------------------------------------------------------------------------- #
def _plan_or_404(plan_id: str) -> dict:
    plan = plans.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "计划不存在或已删除。")
    return plan


def _doc_or_404(doc_id: str) -> dict:
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "课件不存在或已过期，请重新上传。")
    return doc


@app.get("/api/docs")
async def list_docs() -> dict:
    return {"docs": store.list_docs()}


@app.delete("/api/doc/{doc_id}")
async def delete_doc(doc_id: str) -> dict:
    if not store.doc_dir(doc_id):
        raise HTTPException(404, "课件不存在。")
    manager.delete_doc(doc_id)
    store.delete(doc_id)
    return {"ok": True, "doc_id": doc_id}


@app.post("/api/plan")
async def create_plan(payload: PlanRequest) -> JSONResponse:
    doc = _doc_or_404(payload.doc_id)
    started = time.perf_counter()
    plan = await plans.create_plan(
        doc,
        payload.total_days,
        payload.daily_minutes,
        payload.difficulty,
        _resolve_api(payload.api),
        payload.force_fallback,
    )
    plans.save_plan(plan)
    result = dict(plan)
    result["generated_in_seconds"] = round(time.perf_counter() - started, 2)
    return JSONResponse(result, status_code=201)


@app.get("/api/doc/{doc_id}/plans")
async def list_plans(doc_id: str) -> dict:
    _doc_or_404(doc_id)
    index = progress.load_index(doc_id)
    return {
        "doc_id": doc_id,
        "active_plan_id": index.get("active_plan_id"),
        "plans": plans.list_plans(doc_id),
    }


@app.get("/api/plan/{plan_id}")
async def get_plan(plan_id: str) -> dict:
    return _plan_or_404(plan_id)


@app.post("/api/plan/{plan_id}/activate")
async def activate_plan(plan_id: str) -> dict:
    result = plans.activate_plan(plan_id)
    if not result:
        raise HTTPException(404, "计划不存在或已删除。")
    return result


@app.delete("/api/plan/{plan_id}")
async def delete_plan(plan_id: str) -> dict:
    result = plans.delete_plan(plan_id)
    if not result:
        raise HTTPException(404, "计划不存在或已删除。")
    return result


@app.get("/api/progress/{doc_id}/{plan_id}")
async def get_progress(doc_id: str, plan_id: str) -> dict:
    plan = _plan_or_404(plan_id)
    if plan.get("doc_id") != doc_id:
        raise HTTPException(404, "计划不存在或已删除。")
    data = progress.ensure_progress(doc_id, plan_id)
    return {
        "progress": data,
        "milestone_states": progress.milestone_states(plan, data),
        "summary": progress.summary(plan, data),
    }


@app.post("/api/progress/{doc_id}/{plan_id}/page")
async def update_progress(doc_id: str, plan_id: str, payload: ProgressPageRequest) -> dict:
    plan = _plan_or_404(plan_id)
    if plan.get("doc_id") != doc_id:
        raise HTTPException(404, "计划不存在或已删除。")
    if payload.page < 1 or payload.page > int(plan.get("total_pages") or 0):
        raise HTTPException(400, "页面超出计划范围。")
    data, states, event = progress.update_page(
        doc_id, plan_id, plan, payload.page, payload.completed
    )
    return {
        "progress": data,
        "milestone_states": states,
        "summary": progress.summary(plan, data),
        **event,
    }


def _active_plan_id(doc_id: str, requested: str | None) -> str | None:
    if requested:
        return requested
    return progress.load_index(doc_id).get("active_plan_id")


@app.post("/api/quiz")
async def create_quiz(payload: QuizRequest) -> JSONResponse:
    doc = _doc_or_404(payload.doc_id)
    plan = _plan_or_404(payload.plan_id)
    if plan.get("doc_id") != doc["doc_id"]:
        raise HTTPException(404, "计划不存在或已删除。")
    milestone = next(
        (item for item in plan.get("milestones", []) if item.get("milestone_id") == payload.milestone_id),
        None,
    )
    if not milestone:
        raise HTTPException(404, "里程碑不存在。")
    data = progress.ensure_progress(doc["doc_id"], plan["plan_id"])
    states = progress.milestone_states(plan, data)
    state = next((item for item in states if item["milestone_id"] == payload.milestone_id), None)
    last_id = plan["milestones"][-1]["milestone_id"] if plan.get("milestones") else None
    if payload.milestone_id != last_id and state and not state.get("completed"):
        raise HTTPException(409, "完成该里程碑后才能测试。")
    api = _resolve_api(payload.api)
    cached = None
    if not payload.force:
        candidate = quiz._cache_match(
            doc["doc_id"],
            plan["plan_id"],
            payload.milestone_id,
            payload.difficulty,
            payload.question_count,
        )
        if candidate and (candidate.get("source") != "fallback" or not api.api_key):
            cached = candidate
    result = await quiz.generate_quiz(
        doc,
        plan,
        milestone,
        payload.question_count,
        payload.difficulty,
        api,
        payload.force,
        payload.force_fallback,
    )
    status = 201 if not cached else 200
    return JSONResponse({"cached": bool(cached), "quiz": quiz.sanitize_quiz(result)}, status_code=status)


@app.get("/api/quiz/history")
async def quiz_history(doc_id: str, plan_id: str, milestone_id: str | None = None) -> dict:
    doc = _doc_or_404(doc_id)
    plan = _plan_or_404(plan_id)
    if plan.get("doc_id") != doc["doc_id"]:
        raise HTTPException(404, "计划不存在或已删除。")
    milestones = {item.get("milestone_id"): item for item in plan.get("milestones", [])}
    if milestone_id and milestone_id not in milestones:
        raise HTTPException(404, "里程碑不存在。")
    progress_data = progress.load_progress(doc_id, plan_id)
    all_results = list(progress_data.get("quiz_results") or [])
    results = [
        item for item in all_results
        if not milestone_id or item.get("milestone_id") == milestone_id
    ]
    result_by_quiz = {}
    for item in results:
        if item.get("quiz_id"):
            result_by_quiz[item["quiz_id"]] = item
    last_result = results[-1] if results else None
    candidates = quiz.list_for_plan(doc_id, plan_id, milestone_id)
    latest = quiz.latest_for_milestone(
        doc_id,
        plan_id,
        milestone_id,
        preferred_quiz_id=last_result.get("quiz_id") if last_result else None,
    ) if milestone_id else (candidates[0] if candidates else None)
    records = []
    for item in candidates:
        result = result_by_quiz.get(item.get("quiz_id"))
        records.append(
            {
                "quiz_id": item.get("quiz_id"),
                "plan_id": item.get("plan_id"),
                "milestone_id": item.get("milestone_id"),
                "milestone_title": (milestones.get(item.get("milestone_id")) or {}).get("title", ""),
                "created_at": item.get("created_at"),
                "difficulty": item.get("difficulty"),
                "question_count_actual": item.get("question_count_actual", 0),
                "status": item.get("status"),
                "source": item.get("source"),
                "result": result,
                "quiz": quiz.sanitize_quiz(item),
            }
        )
    return {
        "quiz": quiz.sanitize_quiz(latest) if latest else None,
        "result": result_by_quiz.get(latest.get("quiz_id")) if latest else last_result,
        "records": records,
    }


@app.get("/api/quiz/{quiz_id}")
async def get_quiz(quiz_id: str) -> dict:
    data = quiz.find_quiz(quiz_id)
    if not data:
        raise HTTPException(404, "测试不存在或已删除。")
    return quiz.sanitize_quiz(data)


@app.post("/api/quiz/{quiz_id}/submit")
async def submit_quiz(quiz_id: str, payload: QuizSubmit) -> dict:
    data = quiz.find_quiz(quiz_id)
    if not data:
        raise HTTPException(404, "测试不存在或已删除。")
    try:
        result = quiz.grade_quiz(data, [item.model_dump() for item in payload.answers])
    except ValueError as exc:
        code = str(exc)
        if code == "QUIZ_EMPTY":
            raise HTTPException(409, "该测试没有可提交的题目。") from exc
        if code == "INCOMPLETE_ANSWERS":
            raise HTTPException(400, "请提交全部题目。") from exc
        raise HTTPException(400, "答案无效。") from exc
    progress.add_quiz_result(data["doc_id"], data["plan_id"], result)
    return result


@app.get("/api/retrieval/config")
async def retrieval_config(doc_id: str | None = None) -> dict:
    return manager.config(doc_id)


@app.post("/api/retrieval/rebuild")
async def rebuild_index(payload: RebuildRequest) -> dict:
    doc = _doc_or_404(payload.doc_id)
    embedding = payload.embedding.model_dump() if payload.embedding else None
    meta = await asyncio.to_thread(manager.ensure_index, doc, payload.mode, embedding, True)
    return {
        "ok": True,
        "doc_id": doc["doc_id"],
        "mode": meta.get("mode", "keyword"),
        "chunk_count": meta.get("chunk_count", 0),
        "warnings": [meta.get("degraded_reason")] if meta.get("degraded_reason") else [],
    }


@app.post("/api/retrieval/check")
async def retrieval_check(payload: CheckRequest) -> dict:
    doc = _doc_or_404(payload.doc_id)
    return await asyncio.to_thread(
        manager.check,
        doc,
        [item.model_dump() for item in payload.queries],
        payload.top_k,
        payload.mode,
        payload.embedding.model_dump() if payload.embedding else None,
    )


@app.get("/api/chat/history")
async def chat_history(doc_id: str, plan_id: str | None = None) -> dict:
    _doc_or_404(doc_id)
    plan = _active_plan_id(doc_id, plan_id)
    messages = chat.load_history(doc_id, plan)
    return {"doc_id": doc_id, "plan_id": plan, "messages": messages}


@app.delete("/api/chat/history")
async def clear_chat_history(doc_id: str, plan_id: str | None = None) -> dict:
    _doc_or_404(doc_id)
    plan = _active_plan_id(doc_id, plan_id)
    chat.clear_history(doc_id, plan)
    return {"ok": True, "doc_id": doc_id, "plan_id": plan}


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    doc = _doc_or_404(payload.doc_id)
    if payload.user_id != "local":
        raise HTTPException(400, "当前仅支持本地单用户。")
    api = _resolve_api(payload.api)
    if not api.api_key:
        raise HTTPException(503, "未配置模型 API Key，无法问答。")
    if len(doc.get("slides") or []) < 1 or int((doc.get("stats") or {}).get("chars") or 0) < 20:
        raise HTTPException(409, "当前课件没有可检索文字。")
    plan_id = _active_plan_id(doc["doc_id"], payload.plan_id)
    if plan_id and not plans.get_plan(plan_id):
        raise HTTPException(404, "计划不存在或已删除。")
    history = chat.load_history(doc["doc_id"], plan_id)
    embedding = payload.embedding.model_dump() if payload.embedding else None
    hits, mode, degraded_reason = await asyncio.to_thread(
        chat.retrieve, doc, payload.message, None, payload.retrieval_mode, embedding
    )
    index_stale = await asyncio.to_thread(
        manager.is_stale, doc, payload.retrieval_mode, embedding
    )

    async def generate() -> AsyncIterator[str]:
        started = time.perf_counter()
        cjk = sum(1 for char in payload.message if "\u4e00" <= char <= "\u9fff")
        yield _sse(
            {
                "type": "meta",
                "mode": "llm",
                "model": api.model,
                "doc_id": doc["doc_id"],
                "plan_id": plan_id,
                "retrieval_mode": mode,
                "degraded": bool(degraded_reason),
                "degraded_reason": degraded_reason,
                "index_stale": index_stale,
                "general_knowledge": not hits,
                "answer_language": "zh" if cjk > len(payload.message) * 0.2 else "en",
            }
        )
        general_knowledge = not hits
        messages = chat.build_messages(doc, hits, history, payload.message, general_knowledge)
        usage: dict[str, int] = {}
        answer = ""
        truncated = False
        try:
            async with asyncio.timeout(settings.chat_timeout_seconds):
                async for delta in stream_chat(messages, api, max_tokens=1200, usage=usage):
                    if await request.is_disconnected():
                        return
                    if len(answer) + len(delta) > 500:
                        delta = delta[: max(0, 500 - len(answer))]
                        truncated = True
                    answer += delta
                    if delta:
                        yield _sse({"type": "delta", "text": delta})
                    if truncated:
                        break
        except (LLMError, asyncio.TimeoutError) as exc:
            yield _sse(
                {
                    "type": "error",
                    "message": getattr(exc, "message", "问答请求超时或失败，请稍后重试。"),
                    "status": getattr(exc, "status", None),
                    "can_retry": True,
                }
            )
            return

        grounded, citations = chat.validate_citations(answer, hits)
        if not grounded and not general_knowledge:
            yield _sse({"type": "delta", "text": "\n\n> 引用校验未通过，建议重试。"})
        chat.append_history(doc["doc_id"], plan_id, payload.message, answer, citations)
        actual_input = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        actual_output = usage.get("completion_tokens") or usage.get("output_tokens") or estimate_tokens(len(answer))
        yield _sse(
            {
                "type": "done",
                "chars": len(answer),
                "elapsed": round(time.perf_counter() - started, 2),
                "usage": {
                    "input_tokens": int(actual_input),
                    "output_tokens": int(actual_output),
                    "estimated": not bool(usage),
                },
                "cost": None,
                "sources": chat.source_cards(hits),
                "citations": citations,
                "grounded": grounded,
                "general_knowledge": general_knowledge,
                "truncated": truncated,
                "warnings": (
                    ["课件未检索到直接依据，已使用通用知识回答"]
                    if general_knowledge
                    else ([] if grounded else ["未通过引用校验"])
                ),
            }
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# Static frontend (mounted last so /api routes win).
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
