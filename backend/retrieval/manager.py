from __future__ import annotations

from typing import Any

from ..config import DATA_DIR, settings
from . import bm25, vector


def _embedding_config(embedding: dict[str, Any] | None = None, mode: str | None = None) -> dict[str, Any]:
    data = embedding or {}
    return {
        "base_url": str(data.get("base_url") or settings.embedding_base_url or "").strip(),
        "model": str(data.get("model") or settings.embedding_model or "").strip(),
        "api_key": str(data.get("api_key") or settings.embedding_api_key or "").strip(),
        "max_tokens": data.get("max_tokens") or settings.embedding_max_tokens,
        "batch_size": int(data.get("batch_size") or settings.embedding_batch_size),
        "device": str(data.get("device") or settings.embedding_device or "cpu"),
        "provider": "local" if mode == "local_vector" else "remote",
    }


def _select_mode(requested: str | None, embedding: dict[str, Any] | None) -> tuple[str, str | None]:
    mode = (requested or settings.retrieval_mode or "keyword").strip().lower()
    if mode not in {"keyword", "local_vector", "remote_api", "hybrid"}:
        return "keyword", f"未知检索模式 {mode}，已降级为关键词检索"
    if mode == "keyword":
        return mode, None
    config = _embedding_config(embedding)
    if mode == "local_vector":
        if not config["model"]:
            return "keyword", "未配置本地 Embedding 模型，已降级为关键词检索"
        try:
            import importlib.util

            if importlib.util.find_spec("sentence_transformers") is None:
                raise ImportError
        except ImportError:
            return "keyword", "本地向量模式未安装 sentence-transformers，已降级为关键词检索"
        return mode, None
    if not config["base_url"] or not config["model"]:
        return "keyword", "未配置 Embedding Base URL/模型，已降级为关键词检索"
    return mode, None


def _keyword_index(doc: dict[str, Any]) -> dict[str, Any]:
    meta = bm25.metadata(doc["doc_id"])
    if not meta or meta.get("doc_hash") != bm25.doc_hash(doc):
        meta = bm25.build(doc)
    return meta


def ensure_index(
    doc: dict[str, Any],
    mode: str | None = None,
    embedding: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    selected, reason = _select_mode(mode, embedding)
    meta = _keyword_index(doc)
    if selected in {"remote_api", "hybrid", "local_vector"}:
        config = _embedding_config(embedding, selected)
        try:
            existing = vector.metadata(doc["doc_id"], config["model"])
            if force or vector.is_stale(doc, existing, config):
                meta = vector.build(doc, config)
            else:
                meta = existing
            meta = dict(meta)
            meta["mode"] = selected
        except Exception as exc:  # noqa: BLE001
            selected = "keyword"
            reason = f"Embedding 不可用，已降级为关键词检索：{exc}"
            meta = dict(_keyword_index(doc))
    if reason:
        meta = dict(meta)
        meta["degraded"] = True
        meta["degraded_reason"] = reason
    return meta


def _minmax(hits: list[dict[str, Any]]) -> dict[str, float]:
    scores = [float(hit.get("score") or 0.0) for hit in hits]
    if not scores:
        return {}
    low, high = min(scores), max(scores)
    if len(scores) == 1 or high <= low:
        return {str(hit.get("chunk_id")): 1.0 for hit in hits}
    return {
        str(hit.get("chunk_id")): max(0.0, min(1.0, (float(hit.get("score") or 0.0) - low) / (high - low)))
        for hit in hits
    }


def _fuse(
    bm25_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    limit: int,
    alpha: float,
) -> list[dict[str, Any]]:
    """Fuse BM25 and cosine scores using the SPEC alpha weighting."""
    alpha = max(0.0, min(1.0, float(alpha)))
    bm25_norm = _minmax(bm25_hits)
    merged: dict[str, dict[str, Any]] = {}
    for hit in bm25_hits:
        key = str(hit.get("chunk_id"))
        item = dict(hit)
        item["score"] = round((1.0 - alpha) * bm25_norm.get(key, 0.0), 4)
        item["mode"] = "hybrid"
        merged[key] = item
    for hit in vector_hits:
        key = str(hit.get("chunk_id"))
        item = merged.get(key, dict(hit))
        vector_score = max(0.0, min(1.0, float(hit.get("score") or 0.0)))
        item["score"] = round(float(item.get("score") or 0.0) + alpha * vector_score, 4)
        item["mode"] = "hybrid"
        merged[key] = item
    return sorted(merged.values(), key=lambda item: float(item.get("score") or 0), reverse=True)[: max(1, limit)]


def search(
    doc: dict[str, Any],
    query: str,
    top_k: int | None = None,
    mode: str | None = None,
    embedding: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str, str | None]:
    selected, reason = _select_mode(mode, embedding)
    limit = top_k or settings.retrieval_top_k
    if selected == "keyword":
        ensure_index(doc, "keyword")
        return bm25.search(doc["doc_id"], query, limit), "keyword", reason
    config = _embedding_config(embedding, selected)
    try:
        ensure_index(doc, selected, embedding)
        candidate_limit = max(limit, limit * 2)
        vector_hits = vector.search(doc["doc_id"], config["model"], query, config, candidate_limit)
        if selected in {"remote_api", "local_vector"}:
            return vector_hits[:limit], selected, reason
        bm25_hits = bm25.search(doc["doc_id"], query, candidate_limit)
        return _fuse(bm25_hits, vector_hits, limit, settings.hybrid_alpha), "hybrid", reason
    except Exception as exc:  # noqa: BLE001
        fallback = bm25.search(doc["doc_id"], query, limit)
        return fallback, "keyword", f"向量检索失败，已降级为关键词检索：{exc}"


def is_stale(
    doc: dict[str, Any],
    mode: str | None = None,
    embedding: dict[str, Any] | None = None,
) -> bool:
    selected, reason = _select_mode(mode, embedding)
    if selected == "keyword" or reason:
        return False
    config = _embedding_config(embedding, selected)
    return vector.is_stale(doc, vector.metadata(doc["doc_id"], config["model"]), config)


def status(doc_id: str) -> dict[str, Any] | None:
    return bm25.metadata(doc_id)


def delete_doc(doc_id: str) -> None:
    bm25.delete(doc_id)
    if DATA_DIR.is_dir():
        for folder in DATA_DIR.glob("index_vector_*"):
            target = folder / doc_id
            if target.is_dir():
                import shutil

                shutil.rmtree(target, ignore_errors=True)


def config(
    doc_id: str | None = None,
    mode: str | None = None,
    embedding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected, reason = _select_mode(mode, embedding)
    cfg = _embedding_config(embedding, selected)
    meta = bm25.metadata(doc_id) if doc_id else None
    stale = False
    if doc_id and selected != "keyword" and cfg["model"]:
        vector_meta = vector.metadata(doc_id, cfg["model"])
        if vector_meta:
            meta = vector_meta
        else:
            stale = True
    documents = []
    if doc_id and meta:
        documents.append(
            {
                "doc_id": doc_id,
                "indexed": True,
                "stale": stale,
                "chunk_count": meta.get("chunk_count", 0),
                "model": meta.get("model"),
                "dimension": meta.get("dimension", 0),
                "built_at": meta.get("created_at"),
            }
        )
    return {
        "mode": selected,
        "available_modes": ["keyword", "local_vector", "remote_api", "hybrid"],
        "embedding": {
            "configured": bool(cfg["model"] and (selected == "local_vector" or cfg["base_url"])),
            "model": cfg["model"] or None,
            "dimension": meta.get("dimension") if meta and selected != "keyword" else None,
            "max_tokens": cfg["max_tokens"],
        },
        "degraded": bool(reason),
        "degraded_reason": reason,
        "documents": documents,
    }


def check(
    doc: dict[str, Any],
    queries: list[dict[str, Any]],
    top_k: int = 5,
    mode: str | None = None,
    embedding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results = []
    actual_mode = "keyword"
    actual_reason = None
    for item in queries:
        query = str(item.get("query") or "").strip()
        expected = {int(page) for page in item.get("expected_pages") or []}
        hits, actual_mode, actual_reason = search(doc, query, top_k, mode, embedding)
        pages = [hit["page"] for hit in hits]
        results.append(
            {
                "query": query,
                "hits": [
                    {
                        "page": hit["page"],
                        "title": hit["title"],
                        "score": hit["score"],
                        "chunk_id": hit["chunk_id"],
                    }
                    for hit in hits
                ],
                "hit": bool(expected & set(pages)),
            }
        )
    return {
        "doc_id": doc["doc_id"],
        "mode": actual_mode,
        "degraded": bool(actual_reason),
        "degraded_reason": actual_reason,
        "results": results,
    }

