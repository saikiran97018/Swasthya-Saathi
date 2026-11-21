"""Client for OpenAI-compatible chat-completions APIs serving open-source models, with automatic failover.

Works unchanged with Groq (Llama / gpt-oss), Sarvam (sarvam-105b), OpenRouter, Together, HuggingFace router,
or a local Ollama / vLLM server. Targets are tried in order: the primary (LLM_*) first, then the optional
fallback (LLM_FALLBACK_*), so a Groq rate limit or outage silently falls over to Sarvam. Supports streaming
and native tool calling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, UpstreamError

log = logging.getLogger("app.llm")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string as produced by the model

    def as_openai(self) -> dict[str, Any]:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class LLMChunk:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # only set on the final chunk
    finished: bool = False
    usage: dict[str, Any] | None = None
    model: str | None = None  # the model that actually answered (set on the final chunk)


@dataclass
class LLMTarget:
    name: str
    base_url: str
    api_key: str
    model: str
    extra_body: dict[str, Any]
    client: httpx.AsyncClient

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"  # accepted by Groq, Sarvam, OpenRouter, ...
        return h


def _parse_extra(raw: str) -> dict[str, Any]:
    return json.loads(raw) if raw and raw.strip() else {}


class LLMService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, fallback_client: httpx.AsyncClient | None = None):
        self.s = settings
        self._owned: list[httpx.AsyncClient] = []

        def new_client() -> httpx.AsyncClient:
            c = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
            self._owned.append(c)
            return c

        primary_client = client or new_client()
        self.targets: list[LLMTarget] = []
        if settings.llm_primary_configured:
            self.targets.append(
                LLMTarget("primary", settings.llm_base_url, settings.llm_api_key, settings.llm_model, _parse_extra(settings.llm_extra_body), primary_client)
            )
        if settings.llm_fallback_configured:
            self.targets.append(
                LLMTarget(
                    "fallback", settings.llm_fallback_base_url, settings.llm_fallback_api_key, settings.llm_fallback_model,
                    _parse_extra(settings.llm_fallback_extra_body), fallback_client or primary_client,
                )
            )

    async def aclose(self) -> None:
        for c in self._owned:
            await c.aclose()

    @property
    def configured(self) -> bool:
        return bool(self.targets)

    @property
    def model(self) -> str:
        return self.targets[0].model if self.targets else self.s.llm_model

    def _require(self) -> None:
        if not self.targets:
            raise ServiceUnavailable(
                "The language model is not configured. Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in the backend .env file.",
                code="llm_not_configured",
            )

    def _payload(self, target: LLMTarget, messages, tools, stream, temperature, max_tokens) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": target.model,
            "messages": messages,
            "temperature": self.s.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.s.llm_max_tokens,
            "stream": stream,
            **target.extra_body,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    # ---- non-streaming (titles, summaries, reminder translation) -------------------------------
    async def complete(self, messages: list[dict[str, Any]], *, temperature: float | None = None, max_tokens: int | None = None) -> str:
        self._require()
        last: UpstreamError | None = None
        for i, target in enumerate(self.targets):
            try:
                return await self._complete_once(target, messages, temperature, max_tokens)
            except UpstreamError as exc:
                last = exc
                if i < len(self.targets) - 1:
                    log.warning("LLM %s (%s) failed: %s; failing over", target.name, target.model, exc.code)
        assert last is not None
        raise last

    async def _complete_once(self, target: LLMTarget, messages, temperature, max_tokens) -> str:
        payload = self._payload(target, messages, None, False, temperature, max_tokens)
        try:
            resp = await target.client.post(target.url, json=payload, headers=target.headers())
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach the language model API", retryable=True, code="llm_unreachable") from exc
        if resp.status_code >= 400:
            raise self._http_error(resp.status_code, resp.text)
        try:
            return (resp.json()["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise UpstreamError("Unexpected response from the language model API") from exc

    # ---- streaming chat with tools ---------------------------------------------------------------
    async def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[LLMChunk]:
        self._require()
        last: UpstreamError | None = None
        for ti, target in enumerate(self.targets):
            more_targets = ti < len(self.targets) - 1
            attempts = 2 if more_targets else 3  # don't linger on a failing primary when a fallback is ready
            use_tools = tools
            for attempt in range(attempts):
                started = False
                try:
                    async for chunk in self._stream_once(target, messages, use_tools):
                        started = True
                        yield chunk
                    return
                except UpstreamError as exc:
                    if started:
                        raise  # tokens were already emitted: can't safely retry or switch
                    last = exc
                    if exc.code == "llm_tool_call_failed" and use_tools:
                        if more_targets:
                            break  # the backup model, with tools, answers better than this model without them
                        log.warning("Model produced a malformed tool call; retrying without tools")
                        use_tools = None
                        continue
                    rate_limited = exc.code == "llm_rate_limited"
                    if exc.retryable and attempt < attempts - 1 and not (rate_limited and more_targets):
                        await asyncio.sleep(0.8 * (attempt + 1))
                        continue
                    if exc.code == "llm_empty" and not more_targets:
                        # nobody left to ask: hand back an empty answer so the agent shows its friendly "try again" text
                        yield LLMChunk(finished=True, model=target.model)
                        return
                    break
            if more_targets:
                log.warning("LLM %s (%s) failed: %s; failing over to %s", target.name, target.model, last.code if last else "?", self.targets[ti + 1].model)
        assert last is not None
        raise last

    async def _stream_once(self, target: LLMTarget, messages, tools) -> AsyncIterator[LLMChunk]:
        payload = self._payload(target, messages, tools, True, None, None)
        try:
            async with target.client.stream("POST", target.url, json=payload, headers=target.headers()) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    raise self._http_error(resp.status_code, body)

                calls: dict[int, dict[str, str]] = {}
                usage = None
                said_something = False
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(event.get("error"), dict):  # some providers report failures inside a 200 stream
                        code = str(event["error"].get("status") or event["error"].get("code") or "")
                        raise self._http_error(int(code) if code.isdigit() else 500, json.dumps(event["error"]))
                    if event.get("usage"):
                        usage = event["usage"]
                    if event.get("x_groq", {}).get("usage"):
                        usage = event["x_groq"]["usage"]
                    for choice in event.get("choices") or []:  # the final usage-only chunk has an empty list
                        delta = choice.get("delta") or {}
                        if delta.get("content"):  # `reasoning_content` (e.g. Sarvam) is deliberately not shown to users
                            said_something = True
                            yield LLMChunk(content=delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]

                final_calls = [
                    ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"] or "{}")
                    for i, c in sorted(calls.items())
                    if c["name"]
                ]
                if not said_something and not final_calls:  # an empty answer is a failure: let the retry / backup model handle it
                    raise UpstreamError("The language model returned an empty answer", retryable=True, code="llm_empty")
                yield LLMChunk(tool_calls=final_calls, finished=True, usage=usage, model=target.model)
        except httpx.TimeoutException as exc:
            raise UpstreamError("The language model timed out", retryable=True, code="llm_timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach the language model API", retryable=True, code="llm_unreachable") from exc

    @staticmethod
    def _http_error(status: int, body: str) -> UpstreamError:
        snippet = body[:300].replace("\n", " ")
        log.warning("LLM API error %s: %s", status, snippet)
        if status == 400 and "tool" in body.lower() and ("failed" in body.lower() or "invalid" in body.lower()):
            return UpstreamError("The model produced an invalid tool call", code="llm_tool_call_failed")
        if status in (401, 403):
            return UpstreamError("The language model API rejected the API key", code="llm_auth_failed")
        if status == 402:
            return UpstreamError("The language model account is out of credits", code="llm_no_credits")
        if status == 429:
            return UpstreamError("The language model is rate limited, please retry shortly", retryable=True, code="llm_rate_limited")
        return UpstreamError(f"Language model API error (HTTP {status})", retryable=status >= 500, code="llm_error")
