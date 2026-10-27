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


def chat_path(doc_id: str) -> Path:
    return DATA_DIR / doc_id / "chat" / "local.json"


def load_chat(doc_id: str) -> list[dict[str, Any]]:
    return list(_read(chat_path(doc_id), {"messages": []}).get("messages") or [])


def append_chat(doc_id: str, messages: list[dict[str, Any]]) -> None:
    with _LOCK:
        path = chat_path(doc_id)
        data = _read(path, {"doc_id": doc_id, "user_id": "local", "messages": []})
        history = list(data.get("messages") or []) + list(messages or [])
        data["doc_id"] = doc_id
        data["user_id"] = "local"
        data["messages"] = history[-20:]
        data["updated_at"] = _now()
        _write(path, data)


def clear_chat(doc_id: str) -> None:
    with _LOCK:
        _write(
            chat_path(doc_id),
            {
                "doc_id": doc_id,
                "user_id": "local",
                "messages": [],
                "updated_at": _now(),
            },
        )

