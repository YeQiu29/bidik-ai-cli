"""Klien HTTP & OpenAI Streaming untuk 9router LLM Server."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx
from openai import OpenAI

from .config import BidikConfig


@dataclass
class ModelInfo:
    id: str
    owned_by: str = "custom"
    context_window: int = 0
    max_output: int = 0
    supports_tools: bool = True
    supports_reasoning: bool = False
    supports_vision: bool = False

    @property
    def group_label(self) -> str:
        mapping = {
            "combo": "⭐ COMBO",
            "ag": "🚀 ANTIGRAVITY",
            "gemini": "✨ GEMINI",
            "oc": "⚡ OPENCODE",
            "mmf": "🌐 MIMO",
            "ollama": "🦙 OLLAMA",
        }
        return mapping.get(self.owned_by.lower(), f"🔹 {self.owned_by.upper()}")

    @property
    def sort_priority(self) -> tuple[int, str]:
        order = {"combo": 0, "ag": 1, "gemini": 2, "oc": 3, "mmf": 4, "ollama": 5}
        return (order.get(self.owned_by.lower(), 9), self.id.lower())

    @property
    def context_label(self) -> str:
        if not self.context_window:
            return "-"
        if self.context_window >= 1_000_000:
            return f"{self.context_window / 1_048_576:.0f}M ctx"
        return f"{self.context_window // 1024}K ctx"


@dataclass
class ServerStatus:
    online: bool
    latency_ms: int = 0
    model_count: int = 0
    error: str = ""
    models: list[ModelInfo] = field(default_factory=list)


class ThinkTagParser:
    """Memisahkan tag <think>...</think> jika model mengirimkannya di dalam content."""

    def __init__(self) -> None:
        self.in_think = False
        self.buffer = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        self.buffer += text
        while self.buffer:
            if not self.in_think:
                idx = self.buffer.find("<think>")
                if idx == -1:
                    # Tahan jika akhiran mirip awalan '<think>'
                    partial = self._partial_suffix(self.buffer, "<think>")
                    emit = self.buffer[: len(self.buffer) - partial]
                    if emit:
                        events.append(("content", emit))
                    self.buffer = self.buffer[len(self.buffer) - partial :]
                    break
                if idx > 0:
                    events.append(("content", self.buffer[:idx]))
                self.buffer = self.buffer[idx + len("<think>") :]
                self.in_think = True
            else:
                idx = self.buffer.find("</think>")
                if idx == -1:
                    partial = self._partial_suffix(self.buffer, "</think>")
                    emit = self.buffer[: len(self.buffer) - partial]
                    if emit:
                        events.append(("reasoning", emit))
                    self.buffer = self.buffer[len(self.buffer) - partial :]
                    break
                if idx > 0:
                    events.append(("reasoning", self.buffer[:idx]))
                self.buffer = self.buffer[idx + len("</think>") :]
                self.in_think = False
        return events

    def flush(self) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if self.buffer:
            kind = "reasoning" if self.in_think else "content"
            events.append((kind, self.buffer))
            self.buffer = ""
        return events

    @staticmethod
    def _partial_suffix(text: str, tag: str) -> int:
        max_len = min(len(text), len(tag) - 1)
        for length in range(max_len, 0, -1):
            if text.endswith(tag[:length]):
                return length
        return 0


class BidikClient:
    """Wrapper komunikasi ke 9router (OpenAI-compatible endpoint)."""

    def __init__(self, config: BidikConfig) -> None:
        self.config = config
        self._cached_models: list[ModelInfo] = []

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    def check_status(self, timeout: float = 5.0) -> ServerStatus:
        start = time.perf_counter()
        url = f"{self.config.api_base.rstrip('/')}/models"
        try:
            with httpx.Client(timeout=timeout) as http:
                resp = http.get(url, headers=self._headers())
                resp.raise_for_status()
                payload = resp.json()
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            models = self._parse_models(payload.get("data", []))
            self._cached_models = models
            return ServerStatus(
                online=True,
                latency_ms=elapsed_ms,
                model_count=len(models),
                models=models,
            )
        except Exception as exc:
            return ServerStatus(online=False, error=str(exc))

    def fetch_models(self, force_refresh: bool = True) -> list[ModelInfo]:
        if self._cached_models and not force_refresh:
            return self._cached_models
        status = self.check_status(timeout=8.0)
        if status.online:
            return status.models
        raise RuntimeError(status.error or "Gagal menghubungi server 9router")

    @staticmethod
    def _parse_models(raw_list: list[dict[str, Any]]) -> list[ModelInfo]:
        result: list[ModelInfo] = []
        for item in raw_list:
            caps = item.get("capabilities") or {}
            ctx = (
                caps.get("contextWindow")
                or item.get("context_length")
                or 0
            )
            max_out = (
                caps.get("maxOutput")
                or item.get("max_completion_tokens")
                or 0
            )
            info = ModelInfo(
                id=str(item.get("id", "")),
                owned_by=str(item.get("owned_by", "custom")),
                context_window=int(ctx or 0),
                max_output=int(max_out or 0),
                supports_tools=bool(caps.get("tools", True)),
                supports_reasoning=bool(caps.get("reasoning", False)),
                supports_vision=bool(caps.get("vision", False)),
            )
            if info.id:
                result.append(info)
        result.sort(key=lambda m: m.sort_priority)
        return result

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[tuple[str, Any]]:
        """Stream respons chat & tool calls dari 9router."""
        sdk = OpenAI(
            base_url=self.config.api_base,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = sdk.chat.completions.create(**kwargs)

        full_content: list[str] = []
        full_reasoning: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        actual_model = self.config.model
        usage_info: dict[str, int] = {}
        think_parser = ThinkTagParser()

        for chunk in stream:
            if getattr(chunk, "model", None):
                actual_model = chunk.model

            usage_obj = getattr(chunk, "usage", None)
            if usage_obj:
                usage_info = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
                }

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = choices[0].delta
            if delta is None:
                continue

            # Tangkap reasoning eksplisit (DeepSeek / Gemini / 9router)
            reasoning_piece = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if reasoning_piece:
                full_reasoning.append(reasoning_piece)
                yield ("reasoning", reasoning_piece)

            # Tangkap content teks (dan pisahkan <think> jika ada)
            content_piece = getattr(delta, "content", None)
            if content_piece:
                for kind, piece in think_parser.feed(content_piece):
                    if kind == "reasoning":
                        full_reasoning.append(piece)
                        yield ("reasoning", piece)
                    else:
                        full_content.append(piece)
                        yield ("content", piece)

            # Tangkap streaming tool_calls
            delta_tools = getattr(delta, "tool_calls", None)
            if delta_tools:
                for tc in delta_tools:
                    idx = getattr(tc, "index", 0) or 0
                    entry = tool_calls_acc.setdefault(
                        idx,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn:
                        if getattr(fn, "name", None):
                            entry["function"]["name"] += fn.name
                            yield ("tool_start", entry["function"]["name"])
                        if getattr(fn, "arguments", None):
                            entry["function"]["arguments"] += fn.arguments

        for kind, piece in think_parser.flush():
            if kind == "reasoning":
                full_reasoning.append(piece)
                yield ("reasoning", piece)
            else:
                full_content.append(piece)
                yield ("content", piece)

        ordered_tools = [
            tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())
        ]
        for idx, tc in enumerate(ordered_tools):
            if not tc["id"]:
                tc["id"] = f"call_{idx}_{int(time.time() * 1000)}"

        yield (
            "done",
            {
                "content": "".join(full_content).strip(),
                "reasoning": "".join(full_reasoning).strip(),
                "tool_calls": ordered_tools,
                "actual_model": actual_model,
                "usage": usage_info,
            },
        )
