"""Bhashini (ULCA / Dhruva pipeline) client for speech-to-text and text-to-speech.

How it works (two calls per task):
  1. "Pipeline config": we send our userID + ulcaApiKey and ask which model serves
     (task, language). Bhashini replies with an inference URL, a short-lived inference
     key and the model's serviceId. We cache this per (task, language).
  2. "Compute": we call that inference URL with the serviceId and the payload
     (base64 audio for ASR, text for TTS) and read the result.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, UpstreamError
from app.utils.language import LANGUAGES

log = logging.getLogger("app.bhashini")


class BhashiniService:
    name = "bhashini"
    max_audio_seconds: float | None = None  # no provider-specific limit beyond MAX_AUDIO_SECONDS

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client or httpx.AsyncClient(timeout=settings.bhashini_timeout_seconds)
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def configured(self) -> bool:
        return self.s.bhashini_configured

    def supports(self, language: str, task: str) -> bool:
        lang = LANGUAGES.get(language)
        return bool(lang and (lang.asr if task == "asr" else lang.tts))

    def _require(self) -> None:
        if not self.configured:
            raise ServiceUnavailable(
                "Speech is not configured. Set SARVAM_API_KEY (recommended) or BHASHINI_USER_ID and BHASHINI_ULCA_API_KEY in the backend .env file.",
                code="bhashini_not_configured",
            )

    # ---- step 1: pipeline config --------------------------------------------------------
    async def _pipeline(self, task: str, language: str) -> dict[str, Any]:
        key = (task, language)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.s.bhashini_config_cache_seconds:
            return cached[1]

        body = {
            "pipelineTasks": [{"taskType": task, "config": {"language": {"sourceLanguage": language}}}],
            "pipelineRequestConfig": {"pipelineId": self.s.bhashini_pipeline_id},
        }
        headers = {"userID": self.s.bhashini_user_id, "ulcaApiKey": self.s.bhashini_ulca_api_key}
        data = await self._post(self.s.bhashini_config_url, body, headers, what=f"{task} config")

        try:
            endpoint = data["pipelineInferenceAPIEndPoint"]
            auth = endpoint["inferenceApiKey"]
            service_id = self._pick_service_id(data, task, language)
            info = {
                "url": endpoint["callbackUrl"],
                "auth_header": {auth["name"]: auth["value"]},
                "service_id": service_id,
            }
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError(f"Bhashini has no {task.upper()} model for language '{language}'", code="bhashini_no_model") from exc

        self._cache[key] = (time.monotonic(), info)
        return info

    @staticmethod
    def _pick_service_id(data: dict[str, Any], task: str, language: str) -> str:
        for entry in data.get("pipelineResponseConfig", []):
            if entry.get("taskType") != task:
                continue
            configs = entry.get("config", [])
            for cfg in configs:  # prefer an exact language match
                if cfg.get("language", {}).get("sourceLanguage") == language:
                    return cfg["serviceId"]
            return configs[0]["serviceId"]
        raise KeyError("serviceId")

    # ---- step 2: compute -----------------------------------------------------------------
    async def transcribe(self, wav_bytes: bytes, language: str, sample_rate: int = 16000) -> str:
        self._require()
        p = await self._pipeline("asr", language)
        body = {
            "pipelineTasks": [
                {
                    "taskType": "asr",
                    "config": {
                        "language": {"sourceLanguage": language},
                        "serviceId": p["service_id"],
                        "audioFormat": "wav",
                        "samplingRate": sample_rate,
                    },
                }
            ],
            "inputData": {"audio": [{"audioContent": base64.b64encode(wav_bytes).decode()}]},
        }
        data = await self._post(p["url"], body, p["auth_header"], what="speech recognition", retry_config=("asr", language))
        try:
            return (data["pipelineResponse"][0]["output"][0]["source"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("Unexpected response from Bhashini speech recognition") from exc

    async def synthesize(self, text: str, language: str, gender: str = "female") -> bytes:
        """Return WAV bytes for one short piece of text (callers chunk long text)."""
        self._require()
        p = await self._pipeline("tts", language)
        body = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": language},
                        "serviceId": p["service_id"],
                        "gender": gender,
                        "samplingRate": self.s.bhashini_tts_sampling_rate,
                    },
                }
            ],
            "inputData": {"input": [{"source": text}], "audio": [{"audioContent": None}]},
        }
        data = await self._post(p["url"], body, p["auth_header"], what="speech synthesis", retry_config=("tts", language))
        try:
            return base64.b64decode(data["pipelineResponse"][0]["audio"][0]["audioContent"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise UpstreamError("Unexpected response from Bhashini speech synthesis") from exc

    # ---- http ------------------------------------------------------------------------------
    async def _post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        *,
        what: str,
        retry_config: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = await self._client.post(url, json=body, headers={**headers, "Content-Type": "application/json"})
        except httpx.TimeoutException as exc:
            raise UpstreamError(f"Bhashini {what} timed out", retryable=True, code="bhashini_timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Could not reach Bhashini for {what}", retryable=True, code="bhashini_unreachable") from exc

        if resp.status_code in (401, 403) and retry_config:
            # The cached inference key may have expired: drop the cache once and let the caller retry.
            self._cache.pop(retry_config, None)
        if resp.status_code >= 400:
            log.warning("Bhashini %s failed: HTTP %s", what, resp.status_code)
            raise UpstreamError(
                f"Bhashini {what} failed (HTTP {resp.status_code})",
                retryable=resp.status_code >= 500 or resp.status_code in (401, 403, 429),
                code="bhashini_error",
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise UpstreamError(f"Bhashini {what} returned invalid JSON") from exc
