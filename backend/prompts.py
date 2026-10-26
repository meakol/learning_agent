from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import ROOT_DIR

PROMPTS_DIR = ROOT_DIR / "prompts"
_VERSION_RE = re.compile(r"^<!--\s*prompt-version:\s*\d+\s*-->\n?")
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_CACHE: dict[str, tuple[int, int, str]] = {}


class PromptError(RuntimeError):
    """Raised when a prompt file is missing, unsafe, or incomplete."""


def _path(name: str) -> Path:
    if not name or name.startswith(("/", "\\")) or ".." in Path(name).parts:
        raise PromptError(f"非法提示词路径：{name!r}")
    path = (PROMPTS_DIR / name).resolve()
    root = PROMPTS_DIR.resolve()
    if root not in path.parents and path != root:
        raise PromptError(f"提示词路径越界：{name!r}")
    if not path.is_file():
        raise PromptError(f"提示词文件不存在：{name}")
    return path


def _read(name: str) -> str:
    path = _path(name)
    stat = path.stat()
    key = str(path)
    cached = _CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    text = path.read_text(encoding="utf-8")
    text = _VERSION_RE.sub("", text, count=1)
    _CACHE[key] = (stat.st_mtime_ns, stat.st_size, text)
    return text


def load(name: str, **variables: str | int | float) -> str:
    """Load a UTF-8 prompt and replace {{variables}}.

    Missing variables are errors; unknown placeholders are never left behind.
    """
    text = _read(name)
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    remaining = sorted(set(_PLACEHOLDER_RE.findall(text)))
    if remaining:
        raise PromptError(f"提示词缺少变量：{', '.join(remaining)}（{name}）")
    return text


def load_json(name: str) -> Any:
    """Load a JSON rule file from prompts/."""
    try:
        return json.loads(_read(name))
    except json.JSONDecodeError as exc:
        raise PromptError(f"提示词 JSON 无效：{name}: {exc}") from exc


def prompt_hash(names: list[str]) -> str:
    """Stable hash of the listed prompt files and their current contents."""
    digest = hashlib.sha1()
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_read(name).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def require_files(names: list[str]) -> None:
    for name in names:
        _path(name)
