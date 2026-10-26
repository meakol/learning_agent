from __future__ import annotations

import asyncio
import json
import math
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR, settings
from .llm import LLMConfig, complete_chat
from .progress import ensure_progress, load_index, load_progress, save_index, set_active_plan, summary
from .prompts import load
from .text_utils import extract_json

PLAN_ID_RE = re.compile(r"^plan_[a-f0-9]{12}$")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def plan_path(doc_id: str, plan_id: str) -> Path:
    return DATA_DIR / doc_id / "plans" / f"{plan_id}.json"


def _all_docs() -> list[Path]:
    return [
        path
        for path in DATA_DIR.iterdir()
        if path.is_dir() and re.fullmatch(r"[a-f0-9]{12}", path.name)
    ]


def _count(pages: int) -> int:
    if pages <= 1:
        return 1
    if pages == 2:
        return 2
    return max(3, min(8, math.ceil(pages / 10)))


def _titles(doc: dict[str, Any]) -> dict[int, str]:
    return {
        int(slide.get("index") or index): (slide.get("title") or f"第 {index} 页")
        for index, slide in enumerate(doc.get("slides", []), 1)
    }


def _minutes(total: int, count: int) -> list[int]:
    total = max(count, int(total))
    base, rest = divmod(total, count)
    values = [base] * count
    for index in range(rest):
        values[index] += 1
    return values


def _fallback(
    doc: dict[str, Any],
    total_days: int,
    daily_minutes: int,
    difficulty: int,
    reason: str,
) -> dict[str, Any]:
    pages = int(doc.get("page_count") or len(doc.get("slides", [])))
    count = _count(pages)
    size = math.ceil(pages / count) if pages else 1
    titles = _titles(doc)
    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    total_minutes = total_days * daily_minutes
    allocations = _minutes(total_minutes, count)
    milestones = []
    for index in range(count):
        start = index * size + 1
        if start > pages:
            break
        end = min(pages, start + size - 1)
        page_titles = [titles.get(page, f"第 {page} 页") for page in range(start, end + 1)]
        milestones.append(
            {
                "milestone_id": f"ms_{plan_id[5:]}_{index + 1:02d}",
                "order": index + 1,
                "title": f"第 {start}–{end} 页 · {page_titles[0]}"[:40],
                "page_range": {"start": start, "end": end},
                "page_titles": page_titles,
                "estimated_minutes": allocations[index] if index < len(allocations) else 1,
                "learning_objectives": [
                    f"理解第 {start}–{end} 页的核心概念",
                    f"能复述“{page_titles[0]}”的关键结论",
                ],
                "quiz_available": index == len(range(count)) - 1,
            }
        )
    return {
        "plan_id": plan_id,
        "doc_id": doc["doc_id"],
        "user_id": "local",
        "title": f"{doc.get('filename', '课件')} · {total_days} 天学习计划"[:80],
        "total_pages": pages,
        "total_milestones": len(milestones),
        "estimated_days": total_days,
        "daily_minutes": daily_minutes,
        "difficulty": difficulty,
        "total_estimated_minutes": total_minutes,
        "milestones": milestones,
        "status": "fallback" if reason else "ready",
        "source": "fallback",
        "warnings": [reason] if reason else [],
        "created_at": _now(),
        "updated_at": _now(),
    }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_plan(plan: dict[str, Any]) -> None:
    doc_id = plan["doc_id"]
    _write(plan_path(doc_id, plan["plan_id"]), plan)
    ensure_progress(doc_id, plan["plan_id"])
    set_active_plan(doc_id, plan["plan_id"])


def find_plan(plan_id: str) -> dict[str, Any] | None:
    if not PLAN_ID_RE.match(plan_id or ""):
        return None
    for doc_dir in _all_docs():
        path = doc_dir / "plans" / f"{plan_id}.json"
        if path.is_file():
            data = _read(path)
            if data:
                return data
    return None


def _summary(plan: dict[str, Any]) -> dict[str, Any]:
    progress = load_progress(plan["doc_id"], plan["plan_id"])
    return {
        "plan_id": plan["plan_id"],
        "title": plan.get("title", ""),
        "total_pages": plan.get("total_pages", 0),
        "total_milestones": plan.get("total_milestones", 0),
        "estimated_days": plan.get("estimated_days", 0),
        "daily_minutes": plan.get("daily_minutes", 0),
        "difficulty": plan.get("difficulty", 3),
        "source": plan.get("source"),
        "status": plan.get("status"),
        "created_at": plan.get("created_at"),
        "progress": summary(plan, progress),
    }


def list_plans(doc_id: str) -> list[dict[str, Any]]:
    folder = DATA_DIR / doc_id / "plans"
    plans = []
    if folder.is_dir():
        for path in folder.glob("*.json"):
            data = _read(path)
            if data:
                plans.append(_summary(data))
    plans.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return plans


def get_plan(plan_id: str) -> dict[str, Any] | None:
    return find_plan(plan_id)


def activate_plan(plan_id: str) -> dict[str, Any] | None:
    plan = find_plan(plan_id)
    if not plan:
        return None
    index = set_active_plan(plan["doc_id"], plan_id)
    return {"ok": True, "doc_id": plan["doc_id"], "active_plan_id": index.get("active_plan_id")}


def delete_plan(plan_id: str) -> dict[str, Any] | None:
    plan = find_plan(plan_id)
    if not plan:
        return None
    doc_id = plan["doc_id"]
    path = plan_path(doc_id, plan_id)
    if path.is_file():
        path.unlink()
    progress_file = DATA_DIR / doc_id / "progress" / "local" / f"{plan_id}.json"
    if progress_file.is_file():
        progress_file.unlink()
    quizzes = DATA_DIR / doc_id / "quizzes"
    if quizzes.is_dir():
        for quiz_path in quizzes.glob("*.json"):
            data = _read(quiz_path)
            if data and data.get("plan_id") == plan_id:
                quiz_path.unlink()
    index = load_index(doc_id)
    index["plan_ids"] = [item for item in index.get("plan_ids", []) if item != plan_id]
    if index.get("active_plan_id") == plan_id:
        index["active_plan_id"] = index["plan_ids"][0] if index["plan_ids"] else None
    save_index(doc_id, index)
    return {"ok": True, "doc_id": doc_id, "active_plan_id": index.get("active_plan_id")}


def validate_plan(plan: dict[str, Any]) -> tuple[bool, str]:
    try:
        total = int(plan["total_pages"])
        milestones = plan["milestones"]
        if total < 1 or not milestones:
            return False, "页面或里程碑为空"
        expected = 1
        for item in milestones:
            rng = item["page_range"]
            if int(rng["start"]) != expected or int(rng["end"]) < int(rng["start"]):
                return False, "页面区间不连续"
            expected = int(rng["end"]) + 1
            if len(item["page_titles"]) != int(rng["end"]) - int(rng["start"]) + 1:
                return False, "page_titles 长度不匹配"
            if not item["learning_objectives"]:
                return False, "学习目标为空"
        if expected != total + 1:
            return False, "未覆盖全部页面"
        if sum(int(item["estimated_minutes"]) for item in milestones) != int(
            plan["total_estimated_minutes"]
        ):
            return False, "分钟数不匹配"
        return True, ""
    except (KeyError, TypeError, ValueError):
        return False, "字段类型错误"


async def create_plan(
    doc: dict[str, Any],
    total_days: int,
    daily_minutes: int,
    difficulty: int,
    api: LLMConfig,
    force_fallback: bool = False,
) -> dict[str, Any]:
    pages = int(doc.get("page_count") or len(doc.get("slides", [])))
    if pages < 1:
        raise ValueError("课件没有页面")
    total_minutes = int(total_days) * int(daily_minutes)
    if force_fallback or not api.api_key or pages <= 2:
        return _fallback(
            doc,
            total_days,
            daily_minutes,
            difficulty,
            "" if pages <= 2 else "未配置模型，使用等分计划",
        )

    count = _count(pages)
    lines = []
    for slide in doc.get("slides", []):
        text = (slide.get("text") or "").strip().replace("\n", " ")
        lines.append(
            f"{slide.get('index')} | {slide.get('title') or '第 ' + str(slide.get('index')) + ' 页'} | {text[:80]}"
        )
    digest = "\n".join(lines)[:12000]
    user = (
        f"请把以下 {pages} 页课件分成 {count} 个连续里程碑。\n"
        f"总天数 {total_days}，每天 {daily_minutes} 分钟，难度 {difficulty}。\n"
        f"页面摘要：\n{digest}"
    )
    try:
        text = await asyncio.wait_for(
            complete_chat(
                [
                    {"role": "system", "content": load("plan/system.md")},
                    {"role": "user", "content": user},
                ],
                api,
                max_tokens=2500,
                temperature=0.2,
                timeout=settings.plan_timeout_seconds,
            ),
            timeout=settings.plan_timeout_seconds + 2,
        )
        data = extract_json(text)
        if not isinstance(data, dict):
            raise ValueError("计划 JSON 不是对象")
        raw_milestones = data.get("milestones") or []
        if not 3 <= len(raw_milestones) <= 8:
            raise ValueError("里程碑数量不合法")
        titles = _titles(doc)
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        allocations = _minutes(total_minutes, len(raw_milestones))
        milestones = []
        for index, item in enumerate(raw_milestones):
            start, end = int(item["page_start"]), int(item["page_end"])
            if start < 1 or end < start or end > pages:
                raise ValueError("页面区间越界")
            page_titles = [titles.get(page, f"第 {page} 页") for page in range(start, end + 1)]
            objectives = [
                str(value).strip()
                for value in item.get("learning_objectives") or []
                if str(value).strip()
            ]
            if not objectives:
                raise ValueError("学习目标为空")
            milestones.append(
                {
                    "milestone_id": f"ms_{plan_id[5:]}_{index + 1:02d}",
                    "order": index + 1,
                    "title": str(item.get("title") or f"第 {start}–{end} 页")[:40],
                    "page_range": {"start": start, "end": end},
                    "page_titles": page_titles,
                    "estimated_minutes": allocations[index],
                    "learning_objectives": objectives[:4],
                    "quiz_available": index == len(raw_milestones) - 1,
                }
            )
        plan = {
            "plan_id": plan_id,
            "doc_id": doc["doc_id"],
            "user_id": "local",
            "title": str(
                data.get("title") or f"{doc.get('filename', '课件')} · {total_days} 天学习计划"
            )[:80],
            "total_pages": pages,
            "total_milestones": len(milestones),
            "estimated_days": total_days,
            "daily_minutes": daily_minutes,
            "difficulty": difficulty,
            "total_estimated_minutes": total_minutes,
            "milestones": milestones,
            "status": "ready",
            "source": "llm",
            "warnings": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        ok, reason = validate_plan(plan)
        if not ok:
            raise ValueError(reason)
        return plan
    except Exception as exc:
        detail = str(exc).strip().replace("\n", " ")[:160] or type(exc).__name__
        reason = "模型生成失败或超时，使用等分计划"
        if detail:
            reason += f"（{detail}）"
        return _fallback(doc, total_days, daily_minutes, difficulty, reason)

