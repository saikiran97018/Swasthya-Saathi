"""Speech provider with an automatic backup (for example Bhashini first, Sarvam if Bhashini fails).

It implements the same small interface as a single provider, so the rest of the app does not know or care.
A provider is tried only if it is configured AND supports the requested language; any upstream failure
(rate limit, outage, timeout, missing model, bad key) moves on to the next one. An empty transcript is NOT a
failure (silence is silence), so it never triggers a second paid call.
"""
from __future__ import annotations

import logging

from app.core.errors import ServiceUnavailable, UpstreamError

log = logging.getLogger("app.speech")


class FailoverSpeechProvider:
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary
        self._providers = [primary, secondary]

    # --- identity ---------------------------------------------------------------------------------
    @property
    def name(self) -> str:  # the provider users see as "the" speech engine; the backup is reported separately
        return self.primary.name

    @property
    def fallback_name(self) -> str:
        return self.secondary.name

    @property
    def configured(self) -> bool:
        return any(p.configured for p in self._providers)

    @property
    def max_audio_seconds(self) -> float | None:
        first = next((p for p in self._providers if p.configured), self.primary)
        return first.max_audio_seconds

    def supports(self, language: str, task: str) -> bool:
        return any(p.configured and p.supports(language, task) for p in self._providers)

    def _candidates(self, language: str, task: str):
        return [p for p in self._providers if p.configured and p.supports(language, task)]

    # --- work -------------------------------------------------------------------------------------
    async def transcribe(self, wav_bytes: bytes, language: str, sample_rate: int = 16000) -> str:
        return await self._run("asr", language, lambda p: p.transcribe(wav_bytes, language, sample_rate))

    async def synthesize(self, text: str, language: str, gender: str = "female") -> bytes:
        return await self._run("tts", language, lambda p: p.synthesize(text, language, gender))

    async def _run(self, task: str, language: str, call):
        providers = self._candidates(language, task)
        if not providers:
            raise ServiceUnavailable("No speech provider is configured for this language.", code="speech_not_configured")
        last: UpstreamError | None = None
        for i, provider in enumerate(providers):
            try:
                return await call(provider)
            except UpstreamError as exc:
                last = exc
                if i < len(providers) - 1:
                    log.warning("speech %s via %s failed (%s); trying %s", task, provider.name, exc.code, providers[i + 1].name)
        assert last is not None
        raise last

    async def aclose(self) -> None:
        for p in self._providers:
            await p.aclose()
