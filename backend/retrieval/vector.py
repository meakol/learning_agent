from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ..config import DATA_DIR, settings
from ..text_utils import slugify
from . import bm25


def index_dir(doc_id: str, model: str) -> Path:
    return DATA_DIR / f"index_vector_{slugify(model)}" / doc_id


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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


def _local_embed(texts: list[str], config: dict[str, Any]) -> np.ndarray:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ValueError("未安装 sentence-transformers，无法使用 local_vector。") from exc
    model_name = str(config.get("model") or "").strip()
    model = SentenceTransformer(model_name, device=str(config.get("device") or "cpu"))
    max_tokens = config.get("max_tokens")
    if max_tokens:
        model.max_seq_length = max(1, int(max_tokens))
    vectors = model.encode(
        texts,
        batch_size=max(1, int(config.get("batch_size") or settings.embedding_batch_size)),
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    array = np.asarray(vectors, dtype="float32")
    if array.ndim != 2 or array.shape[1] == 0:
        raise ValueError("本地 Embedding 维度无效。")
    return array


def _embed(texts: list[str], config: dict[str, Any]) -> np.ndarray:
    if config.get("provider") == "local":
        return _local_embed(texts, config)
    base = str(config.get("base_url") or "").strip().rstrip("/")
    model = str(config.get("model") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    batch_size = max(1, int(config.get("batch_size") or settings.embedding_batch_size))
    if not base or not model:
        raise ValueError("未配置 Embedding Base URL 或模型。")
    url = base if base.endswith("/embeddings") else base + "/embeddings"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    vectors: list[list[float]] = []
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=60.0, write=20.0, pool=20.0)) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            response = client.post(url, headers=headers, json={"model": model, "input": batch})
            response.raise_for_status()
            rows = response.json().get("data") or []
            if len(rows) != len(batch):
                raise ValueError("Embedding 返回数量不匹配。")
            vectors.extend([row.get("embedding") for row in rows])
    array = np.asarray(vectors, dtype="float32")
    if array.ndim != 2 or array.shape[1] == 0:
        raise ValueError("Embedding 维度无效。")
    return array


def metadata(doc_id: str, model: str) -> dict[str, Any] | None:
    return _read(index_dir(doc_id, model) / "meta.json", None)


def build(doc: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    model = str(config.get("model") or "").strip()
    if not model:
        raise ValueError("未配置 Embedding 模型。")
    bm25.build(doc)
    chunks = bm25.chunks(doc["doc_id"])
    texts = [f"{item.get('title', '')}\n{item.get('text', '')}" for item in chunks]
    embeddings = _embed(texts, config)
    meta = {
        "doc_id": doc["doc_id"],
        "mode": "local_vector" if config.get("provider") == "local" else "remote_api",
        "model": model,
        "dimension": int(embeddings.shape[1]),
        "max_tokens": config.get("max_tokens"),
        "chunk_count": len(chunks),
        "doc_hash": bm25.doc_hash(doc),
        "created_at": _now(),
        "app_version": "1.0.0",
    }
    folder = index_dir(doc["doc_id"], model)
    _write(folder / "chunks.json", chunks)
    np.save(folder / "embeddings.npy", embeddings)
    _write(folder / "meta.json", meta)
    return meta


def is_stale(doc: dict[str, Any], meta: dict[str, Any] | None, config: dict[str, Any]) -> bool:
    mode = "local_vector" if config.get("provider") == "local" else "remote_api"
    return (
        not meta
        or meta.get("doc_hash") != bm25.doc_hash(doc)
        or meta.get("model") != config.get("model")
        or meta.get("max_tokens") != config.get("max_tokens")
        or meta.get("mode") != mode
    )


def search(doc_id: str, model: str, query: str, config: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    folder = index_dir(doc_id, model)
    chunks = _read(folder / "chunks.json", [])
    try:
        embeddings = np.load(folder / "embeddings.npy")
    except (OSError, ValueError):
        return []
    if not chunks or embeddings.ndim != 2:
        return []
    query_vec = _embed([query], config)[0]
    scores = embeddings @ query_vec / (
        np.linalg.norm(embeddings, axis=1) * max(1e-9, float(np.linalg.norm(query_vec)))
    )
    ranked = sorted(enumerate(scores), key=lambda pair: float(pair[1]), reverse=True)[: max(1, top_k)]
    results = []
    for index, score in ranked:
        item = dict(chunks[index])
        item["score"] = round(float(score), 4)
        item["mode"] = "local_vector" if config.get("provider") == "local" else "remote_api"
        results.append(item)
    return results


def delete(doc_id: str, model: str) -> None:
    folder = index_dir(doc_id, model)
    if folder.is_dir():
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
