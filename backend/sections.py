"""Note-driven study sections.

The notes outline (``##`` headings) is the study plan: every section owns the
pages it cites, students tick sections off, and quizzes are generated only for
sections that are already ticked.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .text_utils import is_admin_heading

_LOCK = threading.RLock()
_SIGNATURE_RE = re.compile(r"^[a-z]{2,12}\|[1-5]$")
_PAGE_RE = re.compile(
    r"\[p{1,2}\.?\s*(\d+)(?:\s*[-–—~]\s*(\d+))?\]|\[第\s*(\d+)\s*页\]",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")

MAX_SECTIONS = 60
MAX_TITLE_CHARS = 80
MAX_PAGES_PER_SECTION = 60
DEFAULT_SIGNATURE = "zh|3"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_signature(value: str) -> str:
    """Signature identifies one notes variant: language + level."""
    signature = str(value or "").strip().lower()
    return signature if _SIGNATURE_RE.match(signature) else DEFAULT_SIGNATURE


def _slug(signature: str) -> str:
    return normalize_signature(signature).replace("|", "-")


def sections_dir(doc_id: str) -> Path:
    return DATA_DIR / doc_id / "sections"


def sections_path(doc_id: str, signature: str) -> Path:
    return sections_dir(doc_id) / f"{_slug(signature)}.json"


def progress_path(doc_id: str, signature: str) -> Path:
    return sections_dir(doc_id) / f"{_slug(signature)}.progress.json"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def pages_from_text(text: str) -> list[int]:
    pages: set[int] = set()
    for match in _PAGE_RE.finditer(str(text or "")):
        start = int(match.group(3) or match.group(1) or 0)
        if not start:
            continue
        end = start if match.group(3) else int(match.group(2) or start)
        if end < start:
            start, end = end, start
        for page in range(start, min(end, start + 40) + 1):
            pages.add(page)
    return sorted(pages)


def section_id(title: str, pages: list[int]) -> str:
    """Stable id so regenerated notes keep their tick marks when possible."""
    key = _SPACE_RE.sub("", str(title or "")) + "|" + ",".join(str(p) for p in sorted(set(pages)))
    return "sec_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def normalize_sections(raw: Any, total_pages: int = 0) -> list[dict[str, Any]]:
    """Validate client sections, drop logistics headings and page-less items."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    limit = max(0, int(total_pages or 0))
    for entry in list(raw or [])[:MAX_SECTIONS]:
        if not isinstance(entry, dict):
            continue
        title = _SPACE_RE.sub(" ", str(entry.get("title") or "")).strip()[:MAX_TITLE_CHARS]
        if not title or is_admin_heading(title):
            continue
        pages: set[int] = set()
        for value in entry.get("pages") or []:
            try:
                page = int(value)
            except (TypeError, ValueError):
                continue
            if page >= 1 and (not limit or page <= limit):
                pages.add(page)
        if not pages:
            pages = {
                page
                for page in pages_from_text(title)
                if page >= 1 and (not limit or page <= limit)
            }
        if not pages:
            continue
        ordered = sorted(pages)[:MAX_PAGES_PER_SECTION]
        sid = str(entry.get("section_id") or "").strip()[:32]
        if not sid.startswith("sec_") or sid in seen:
            sid = section_id(title, ordered)
        if sid in seen:
            continue
        seen.add(sid)
        try:
            level = int(entry.get("level") or 2)
        except (TypeError, ValueError):
            level = 2
        items.append(
            {
                "section_id": sid,
                "title": title,
                "pages": ordered,
                "level": max(1, min(6, level)),
            }
        )
    return items


def save_sections(
    doc_id: str,
    signature: str,
    raw: Any,
    total_pages: int = 0,
) -> dict[str, Any]:
    """Register the sections of one notes variant and prune stale check marks."""
    signature = normalize_signature(signature)
    data = {
        "doc_id": doc_id,
        "signature": signature,
        "total_pages": int(total_pages or 0),
        "sections": normalize_sections(raw, total_pages),
        "updated_at": _now(),
    }
    with _LOCK:
        _write(sections_path(doc_id, signature), data)
        progress = load_progress(doc_id, signature)
        valid = {item["section_id"] for item in data["sections"]}
        kept = [sid for sid in progress["completed_section_ids"] if sid in valid]
        if kept != progress["completed_section_ids"]:
            progress["completed_section_ids"] = kept
            _write(progress_path(doc_id, signature), progress)
    return data


def load_sections(doc_id: str, signature: str) -> dict[str, Any] | None:
    return _read(sections_path(doc_id, normalize_signature(signature)))


def load_progress(doc_id: str, signature: str) -> dict[str, Any]:
    signature = normalize_signature(signature)
    data = _read(progress_path(doc_id, signature)) or {}
    data.setdefault("doc_id", doc_id)
    data.setdefault("signature", signature)
    raw_ids = data.get("completed_section_ids")
    data["completed_section_ids"] = (
        [str(value) for value in raw_ids] if isinstance(raw_ids, list) else []
    )
    data.setdefault("updated_at", _now())
    return data


def toggle_section(
    doc_id: str,
    signature: str,
    section_id_value: str,
    completed: bool = True,
) -> dict[str, Any]:
    signature = normalize_signature(signature)
    with _LOCK:
        data = load_progress(doc_id, signature)
        ids = set(data["completed_section_ids"])
        if completed:
            ids.add(section_id_value)
        else:
            ids.discard(section_id_value)
        data["completed_section_ids"] = sorted(ids)
        data["updated_at"] = _now()
        _write(progress_path(doc_id, signature), data)
        return data


def section_states(
    section_data: dict[str, Any] | None,
    progress_data: dict[str, Any],
) -> list[dict[str, Any]]:
    completed = set(progress_data.get("completed_section_ids") or [])
    return [
        {**item, "completed": item["section_id"] in completed}
        for item in (section_data or {}).get("sections", [])
    ]


def summary(
    section_data: dict[str, Any] | None,
    progress_data: dict[str, Any],
) -> dict[str, Any]:
    states = section_states(section_data, progress_data)
    total = len(states)
    done = sum(1 for item in states if item["completed"])
    return {
        "completed": done,
        "total": total,
        "percent": round(done / total * 100, 1) if total else 0.0,
    }
