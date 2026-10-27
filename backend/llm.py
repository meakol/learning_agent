from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from .logging_utils import log_event

logger = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.3

    def endpoint(self) -> str:
        base = (self.base_url or "").strip().rstrip("/")
        if not base:
            raise LLMError("未配置 API Base URL。")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def redacted(self) -> dict[str, str]:
        return {"base_url": self.base_url, "model": self.model}


async def stream_chat(
    messages: list[dict[str, str]],
    config: LLMConfig,
    max_tokens: int = 4096,
    usage: dict | None = None,
) -> AsyncIterator[str]:
    url = config.endpoint()
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": True,
        "temperature": config.temperature,
        "max_tokens": max_tokens,
    }
    timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    raw = (await response.aread()).decode("utf-8", "replace")
                    detail = raw[:500]
                    try:
                        data = json.loads(raw)
                        detail = (
                            data.get("error", {}).get("message")
                            or data.get("message")
                            or detail
                        )
                    except Exception:
                        pass
                    if response.status_code == 401:
                        raise LLMError(
                            "API Key 无效或已过期（401）。请在右上角“设置”中检查 Key。",
                            response.status_code,
                        )
                    if response.status_code == 404:
                        raise LLMError(
                            f"接口地址或模型不存在（404）：{detail}。请检查 Base URL 是否需要包含 /v1，以及模型名称。",
                            response.status_code,
                        )
                    if response.status_code == 429:
                        raise LLMError(
                            f"请求过于频繁或额度不足（429）：{detail}",
                            response.status_code,
                        )
                    raise LLMError(
                        f"模型接口返回错误（{response.status_code}）：{detail}",
                        response.status_code,
                    )

                got_content = False
                async for line in response.aiter_lines():
                    line = (line or "").strip()
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        error = data["error"]
                        message = error.get("message") if isinstance(error, dict) else str(error)
                        raise LLMError(f"生成过程中出错：{message}")
                    if usage is not None and isinstance(data.get("usage"), dict):
                        for key in (
                            "prompt_tokens",
                            "completion_tokens",
                            "total_tokens",
                            "input_tokens",
                            "output_tokens",
                        ):
                            value = data["usage"].get(key)
                            if isinstance(value, int):
                                usage[key] = value
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, list):
                        content = "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict)
                        )
                    if content:
                        got_content = True
                        yield content
                if not got_content:
                    raise LLMError(
                        "模型没有返回任何内容。请确认该模型支持流式输出，或稍后重试。"
                    )
    except LLMError:
        raise
    except httpx.ConnectError as exc:
        raise LLMError(
            f"无法连接到模型接口（{config.base_url}）。请检查 Base URL、网络或本地服务是否启动。"
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMError("调用模型超时，请稍后重试或降低笔记详细程度。") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"网络请求失败：{exc}") from exc


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Retry delay in seconds: Retry-After first, then 1s/2s + jitter."""
    if response is not None:
        raw = response.headers.get("Retry-After", "").strip()
        if raw:
            try:
                return min(10.0, max(0.0, float(raw)))
            except ValueError:
                pass
    return min(10.0, float(2 ** attempt) + (time.monotonic() % 0.3))


def _error_from_response(response: httpx.Response, detail: str) -> LLMError:
    if response.status_code == 401:
        return LLMError(
            "API Key 无效或已过期（401）。请在右上角“设置”中检查 Key。",
            response.status_code,
        )
    if response.status_code == 404:
        return LLMError(
            f"接口地址或模型不存在（404）：{detail}。请检查 Base URL 是否需要包含 /v1，以及模型名称。",
            response.status_code,
        )
    if response.status_code == 429:
        return LLMError(f"请求过于频繁或额度不足（429）：{detail}", response.status_code)
    return LLMError(f"模型接口返回错误（{response.status_code}）：{detail}", response.status_code)


async def complete_chat(
    messages: list[dict[str, str]],
    config: LLMConfig,
    *,
    max_tokens: int = 2048,
    temperature: float | None = None,
    timeout: float = 60.0,
    usage: dict | None = None,
) -> str:
    """Collect a streaming completion into a complete string.

    Some OpenAI-compatible gateways only implement the streaming endpoint
    reliably.  Chat already uses that path, so quizzes use the same
    transport and apply bounded retries around it.
    """
    call_config = config
    if temperature is not None:
        from dataclasses import replace

        call_config = replace(config, temperature=temperature)
    last_error: LLMError | None = None

    for attempt in range(3):
        started = time.perf_counter()
        try:
            async def collect() -> str:
                parts: list[str] = []
                async for delta in stream_chat(
                    messages,
                    call_config,
                    max_tokens=max_tokens,
                    usage=usage,
                ):
                    parts.append(delta)
                return "".join(parts).strip()

            content = await asyncio.wait_for(collect(), timeout=timeout)
            if not content:
                raise LLMError("模型没有返回任何内容。")
            elapsed = round((time.perf_counter() - started) * 1000)
            used = usage or {}
            log_event(
                logger,
                "llm.response",
                model=config.model,
                status=200,
                latency_ms=elapsed,
                attempt=attempt + 1,
                input_tokens=used.get("prompt_tokens") or used.get("input_tokens"),
                output_tokens=used.get("completion_tokens") or used.get("output_tokens"),
            )
            return content
        except LLMError as exc:
            last_error = exc
            if attempt >= 2 or exc.status in {400, 401, 403, 404}:
                raise
            log_event(
                logger,
                "llm.retry",
                model=config.model,
                status=exc.status,
                attempt=attempt + 1,
                delay_seconds=round(_retry_delay(None, attempt), 2),
            )
        except (asyncio.TimeoutError, TimeoutError):
            last_error = LLMError("调用模型超时，请稍后重试。")
            if attempt >= 2:
                raise last_error
            log_event(
                logger,
                "llm.retry",
                model=config.model,
                attempt=attempt + 1,
                delay_seconds=round(_retry_delay(None, attempt), 2),
            )
        except httpx.TimeoutException:
            last_error = LLMError("调用模型超时，请稍后重试。")
            if attempt >= 2:
                raise last_error
        except httpx.HTTPError as exc:
            last_error = LLMError(f"网络请求失败：{exc}")
            if attempt >= 2:
                raise last_error
        if attempt < 2:
            await asyncio.sleep(_retry_delay(None, attempt))
    raise last_error or LLMError("模型调用失败。")
