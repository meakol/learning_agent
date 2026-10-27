from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.is_file():
        return dict(default or {})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default or {})


def index_path(doc_id: str) -> Path:
    return DATA_DIR / doc_id / "progress" / "local" / "index.json"


def progress_path(doc_id: str, plan_id: str) -> Path:
    return DATA_DIR / doc_id / "progress" / "local" / f"{plan_id}.json"


def load_index(doc_id: str) -> dict[str, Any]:
    data = _read(index_path(doc_id), {"doc_id": doc_id, "user_id": "local", "active_plan_id": None, "plan_ids": []})
    data.setdefault("doc_id", doc_id)
    data.setdefault("plan_ids", [])
    return data


def save_index(doc_id: str, index: dict[str, Any]) -> None:
    index["updated_at"] = _now()
    _write(index_path(doc_id), index)


def set_active_plan(doc_id: str, plan_id: str | None) -> dict[str, Any]:
    with _LOCK:
        index = load_index(doc_id)
        ids = list(index.get("plan_ids") or [])
        if plan_id and plan_id not in ids:
            ids.insert(0, plan_id)
        if not plan_id and ids:
            plan_id = ids[0]
        index["plan_ids"] = ids
        index["active_plan_id"] = plan_id
        save_index(doc_id, index)
        return index


def ensure_progress(doc_id: str, plan_id: str) -> dict[str, Any]:
    path = progress_path(doc_id, plan_id)
    with _LOCK:
        data = _read(path)
        if not data:
            now = _now()
            data = {
                "progress_id": f"prog_{plan_id.removeprefix('plan_')}",
                "user_id": "local",
                "doc_id": doc_id,
                "plan_id": plan_id,
                "completed_pages": [],
                "completed_milestones": [],
                "quiz_results": [],
                "chat_history": [],
                "created_at": now,
                "updated_at": now,
            }
            _write(path, data)
            index = load_index(doc_id)
            if plan_id not in index["plan_ids"]:
                index["plan_ids"].insert(0, plan_id)
                index.setdefault("active_plan_id", plan_id)
                save_index(doc_id, index)
        return data


def load_progress(doc_id: str, plan_id: str) -> dict[str, Any]:
    return _read(progress_path(doc_id, plan_id))


def _save_progress(data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    _write(progress_path(data["doc_id"], data["plan_id"]), data)


def milestone_states(plan: dict[str, Any], progress: dict[str, Any]) -> list[dict[str, Any]]:
    completed = set(int(p) for p in progress.get("completed_pages", []))
    last = plan.get("milestones", [])[-1:] or []
    last_id = last[0].get("milestone_id") if last else None
    states = []
    for milestone in plan.get("milestones", []):
        rng = milestone.get("page_range") or {}
        start, end = int(rng.get("start", 1)), int(rng.get("end", 0))
        pages = list(range(start, end + 1))
        done = sum(1 for page in pages if page in completed)
        states.append(
            {
                "milestone_id": milestone.get("milestone_id"),
                "completed_pages": done,
                "total_pages": len(pages),
                "completed": bool(pages) and done == len(pages),
                "quiz_available": milestone.get("milestone_id") == last_id
                or (bool(pages) and done == len(pages)),
            }
        )
    return states


def summary(plan: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    total = int(plan.get("total_pages") or 0)
    done = len(set(progress.get("completed_pages", [])))
    return {
        "completed_pages": done,
        "total_pages": total,
        "completed_milestones": len(progress.get("completed_milestones", [])),
        "total_milestones": len(plan.get("milestones", [])),
        "percent": round(done / total * 100, 1) if total else 0.0,
    }


def update_page(
    doc_id: str,
    plan_id: str,
    plan: dict[str, Any],
    page: int,
    completed: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    with _LOCK:
        data = ensure_progress(doc_id, plan_id)
        pages = set(int(p) for p in data.get("completed_pages", []))
        before = set(data.get("completed_milestones", []))
        changed = (page in pages) != bool(completed)
        if completed:
            pages.add(page)
        else:
            pages.discard(page)
        data["completed_pages"] = sorted(pages)
        completed_now = []
        for milestone in plan.get("milestones", []):
            rng = milestone.get("page_range") or {}
            wanted = set(range(int(rng.get("start", 1)), int(rng.get("end", 0)) + 1))
            if wanted and wanted <= pages:
                completed_now.append(milestone.get("milestone_id"))
        data["completed_milestones"] = completed_now
        _save_progress(data)
        states = milestone_states(plan, data)
        event = {
            "changed": changed,
            "milestone_completed": [item for item in completed_now if item not in before],
            "milestone_reopened": [item for item in before if item not in completed_now],
        }
        return data, states, event


def add_quiz_result(doc_id: str, plan_id: str, result: dict[str, Any]) -> None:
    with _LOCK:
        data = ensure_progress(doc_id, plan_id)
        results = list(data.get("quiz_results") or [])
        results.append(result)
        data["quiz_results"] = results[-50:]
        _save_progress(data)


def _doc_chat_path(doc_id: str) -> Path:
    return DATA_DIR / doc_id / "chat" / "local.json"


def load_chat(doc_id: str, plan_id: str | None = None) -> list[dict[str, Any]]:
    if plan_id:
        return list(load_progress(doc_id, plan_id).get("chat_history") or [])
    data = _read(_doc_chat_path(doc_id), {"messages": []})
    return list(data.get("messages") or [])


def append_chat(doc_id: str, plan_id: str | None, messages: list[dict[str, Any]]) -> None:
    with _LOCK:
        if plan_id:
            data = ensure_progress(doc_id, plan_id)
            history = list(data.get("chat_history") or []) + messages
            data["chat_history"] = history[-20:]
            _save_progress(data)
        else:
            path = _doc_chat_path(doc_id)
            data = _read(path, {"doc_id": doc_id, "user_id": "local", "plan_id": None, "messages": []})
            history = list(data.get("messages") or []) + messages
            data["messages"] = history[-20:]
            data["updated_at"] = _now()
            _write(path, data)


def clear_chat(doc_id: str, plan_id: str | None = None) -> None:
    with _LOCK:
        if plan_id:
            data = ensure_progress(doc_id, plan_id)
            data["chat_history"] = []
            _save_progress(data)
        else:
            _write(
                _doc_chat_path(doc_id),
                {
                    "doc_id": doc_id,
                    "user_id": "local",
                    "plan_id": None,
                    "messages": [],
                    "updated_at": _now(),
                },
            )

