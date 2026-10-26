from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .config import DATA_DIR

DOC_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class DocumentStore:
    def __init__(self, base_dir: Path = DATA_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}

    def new_doc_dir(self) -> tuple[str, Path]:
        doc_id = uuid.uuid4().hex[:12]
        doc_dir = self.base_dir / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "media").mkdir(exist_ok=True)
        (doc_dir / "pages").mkdir(exist_ok=True)
        return doc_id, doc_dir

    def save(self, doc: dict[str, Any]) -> None:
        doc_id = doc["doc_id"]
        doc_dir = self.base_dir / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "doc.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
        self._cache[doc_id] = doc

    def get(self, doc_id: str) -> dict[str, Any] | None:
        if not DOC_ID_RE.match(doc_id or ""):
            return None
        if doc_id in self._cache:
            return self._cache[doc_id]
        path = self.base_dir / doc_id / "doc.json"
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        self._cache[doc_id] = doc
        return doc

    def doc_dir(self, doc_id: str) -> Path | None:
        if not DOC_ID_RE.match(doc_id or ""):
            return None
        path = self.base_dir / doc_id
        return path if path.is_dir() else None

    def list_docs(self) -> list[dict[str, Any]]:
        docs = []
        for path in self.base_dir.iterdir() if self.base_dir.exists() else []:
            if not path.is_dir() or not DOC_ID_RE.match(path.name):
                continue
            doc = self.get(path.name)
            if not doc:
                continue
            docs.append(
                {
                    "doc_id": path.name,
                    "filename": doc.get("filename", ""),
                    "kind": doc.get("kind", ""),
                    "page_count": doc.get("page_count", 0),
                    "created_at": doc.get("created_at", ""),
                    "warnings": len(doc.get("warnings") or []),
                }
            )
        docs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return docs

    def delete(self, doc_id: str) -> None:
        self._cache.pop(doc_id, None)
        if DOC_ID_RE.match(doc_id or ""):
            shutil.rmtree(self.base_dir / doc_id, ignore_errors=True)


store = DocumentStore()
