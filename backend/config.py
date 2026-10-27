from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DATA_DIR = ROOT_DIR / "data"
SAMPLES_DIR = ROOT_DIR / "samples"


def load_dotenv(path: Path) -> None:
    """Tiny .env loader so the app has no extra dependency."""
    if not path.exists():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


load_dotenv(ROOT_DIR / ".env")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    temperature: float = _env_float("OPENAI_TEMPERATURE", 0.3)
    max_context_chars: int = _env_int("MAX_CONTEXT_CHARS", 24_000)
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 50)
    max_slides: int = _env_int("MAX_SLIDES", 200)
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _env_int("PORT", 8124)

    # 阶段 2/3/4 使用；本阶段只提供默认值，不改变现有行为。
    model_context_tokens: int = _env_int("MODEL_CONTEXT_TOKENS", 8192)
    pipeline_enabled: bool = _env_bool("PIPELINE_ENABLED", True)
    pipeline_chunk_chars: int = _env_int("PIPELINE_CHUNK_CHARS", 6000)
    pipeline_max_pages_per_chunk: int = _env_int("PIPELINE_MAX_PAGES_PER_CHUNK", 8)
    pipeline_concurrency: int = _env_int("PIPELINE_CONCURRENCY", 2)
    pipeline_max_retries: int = _env_int("PIPELINE_MAX_RETRIES", 2)

    # Slow reasoning models often need >25s for a complete quiz JSON.
    # 0.8 keeps scenarios fresh without breaking the JSON contract too often.
    quiz_temperature: float = _env_float("QUIZ_TEMPERATURE", 0.8)
    quiz_timeout_seconds: float = _env_float("QUIZ_TIMEOUT_SECONDS", 120.0)
    chat_timeout_seconds: float = _env_float("CHAT_TIMEOUT_SECONDS", 30.0)

    retrieval_mode: str = os.getenv("RETRIEVAL_MODE", "keyword").strip().lower()
    retrieval_top_k: int = _env_int("RETRIEVAL_TOP_K", 6)
    retrieval_min_score: float = _env_float("RETRIEVAL_MIN_SCORE", 0.0)
    bm25_chunk_chars: int = _env_int("BM25_CHUNK_CHARS", 1000)
    hybrid_alpha: float = _env_float("HYBRID_ALPHA", 0.5)

    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "").strip()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "").strip()
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "").strip()
    embedding_max_tokens: int | None = _env_optional_int("EMBEDDING_MAX_TOKENS")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu").strip().lower()
    embedding_batch_size: int = _env_int("EMBEDDING_BATCH_SIZE", 16)

    log_level: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    eval_judge_base_url: str = os.getenv("EVAL_JUDGE_BASE_URL", "").strip()
    eval_judge_model: str = os.getenv("EVAL_JUDGE_MODEL", "").strip()
    eval_judge_api_key: str = os.getenv("EVAL_JUDGE_API_KEY", "").strip()

    @property
    def llm_configured(self) -> bool:
        return bool(self.api_key)


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)

PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "logo": "O",
        "color": "#10a37f",
        "pricing": {"input": 0.15, "output": 0.60, "currency": "USD", "note": "参考价"},
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "logo": "D",
        "color": "#4d6bfe",
        "pricing": {"input": 0.27, "output": 1.10, "currency": "USD", "note": "参考价"},
    },
    {
        "id": "moonshot",
        "name": "Moonshot / Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "logo": "K",
        "color": "#6d4aff",
        "pricing": {"input": 1.68, "output": 1.68, "currency": "USD", "note": "参考价"},
    },
    {
        "id": "qwen",
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "logo": "Q",
        "color": "#615ced",
        "pricing": {"input": 0.40, "output": 1.20, "currency": "USD", "note": "参考价"},
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "logo": "G",
        "color": "#3859ff",
        "pricing": {"input": 0.0, "output": 0.0, "currency": "USD", "note": "参考价"},
    },
    {
        "id": "ollama",
        "name": "Ollama（本地）",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "logo": "⌂",
        "color": "#64748b",
        "pricing": {"input": 0.0, "output": 0.0, "currency": "USD", "note": "本机"},
    },
    {
        "id": "custom",
        "name": "自定义 / 其他兼容接口",
        "base_url": "",
        "model": "",
        "logo": "✦",
        "color": "#4f46e5",
        "pricing": None,
    },
]

# USD per 1M tokens (public list prices; approximate and may change).
MODEL_PRICING = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-chat": (0.27, 1.10),
    "qwen-plus": (0.40, 1.20),
    "qwen-turbo": (0.05, 0.20),
    "glm-4-flash": (0.0, 0.0),
    "moonshot": (1.68, 1.68),
}


def pricing_for(base_url: str, model: str) -> dict | None:
    """Best-effort public list price lookup. Returns USD / 1M tokens."""
    name = (model or "").strip().lower()
    for key in sorted(MODEL_PRICING, key=len, reverse=True):
        if name == key or name.startswith(key + "-") or name.startswith(key + ":"):
            input_price, output_price = MODEL_PRICING[key]
            return {
                "input": input_price,
                "output": output_price,
                "currency": "USD",
                "note": "参考价",
            }
    base = (base_url or "").strip()
    for provider in PROVIDERS:
        pricing = provider.get("pricing")
        if not pricing:
            continue
        if provider.get("model") and name == provider["model"].lower():
            return dict(pricing)
        if provider.get("id") == "ollama" and provider.get("base_url") and base.startswith(provider["base_url"]):
            return dict(pricing)
        if not name and provider.get("base_url") and base.startswith(provider["base_url"]):
            return dict(pricing)
    return None


def estimate_tokens(chars: int) -> int:
    """Rough token estimate for mixed Chinese / English text."""
    return max(1, round(max(0, chars) / 1.7))

