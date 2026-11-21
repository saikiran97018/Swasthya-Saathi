"""Speech pipeline: validation, language checks, chunking and caching around the active speech provider
(Sarvam or Bhashini; both expose the same small interface)."""
from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.core.errors import BadRequest, UpstreamError
from app.utils import audio as audio_utils
from app.utils.language import LANGUAGES, normalise_language, split_for_tts, strip_markdown_for_speech


class SpeechProvider(Protocol):
    name: str
    max_audio_seconds: float | None

    @property
    def configured(self) -> bool: ...

    def supports(self, language: str, task: str) -> bool: ...

    async def transcribe(self, wav_bytes: bytes, language: str, sample_rate: int = 16000) -> str: ...

    async def synthesize(self, text: str, language: str, gender: str = "female") -> bytes: ...

    async def aclose(self) -> None: ...


@dataclass
class Transcription:
    text: str
    language: str
    duration_seconds: float


class SpeechService:
    def __init__(self, settings: Settings, provider: SpeechProvider):
        self.s = settings
        self.provider = provider
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    @property
    def max_audio_seconds(self) -> float:
        """The recording limit clients must respect: the stricter of our setting and the provider's own limit."""
        return min(self.s.max_audio_seconds, self.provider.max_audio_seconds or self.s.max_audio_seconds)

    def capabilities(self, language: str) -> tuple[bool, bool]:
        """(speech recognition, speech synthesis) availability for this language with the active provider."""
        return self.provider.supports(language, "asr"), self.provider.supports(language, "tts")

    async def transcribe(self, wav_bytes: bytes, language: str) -> Transcription:
        lang = normalise_language(language)
        if not self.provider.supports(lang, "asr"):
            raise BadRequest(f"Speech recognition is not available for {LANGUAGES[lang].name}", code="language_not_supported")
        info = audio_utils.validate_upload(wav_bytes, max_bytes=self.s.max_audio_bytes, max_seconds=self.max_audio_seconds)
        text = await self.provider.transcribe(wav_bytes, lang, sample_rate=info.sample_rate)
        return Transcription(text=text, language=lang, duration_seconds=round(info.duration, 2))

    async def synthesize(self, text: str, language: str, gender: str = "female") -> bytes:
        lang = normalise_language(language)
        if not self.provider.supports(lang, "tts"):
            raise BadRequest(f"Speech synthesis is not available for {LANGUAGES[lang].name}", code="language_not_supported")
        clean = strip_markdown_for_speech(text)
        if not clean:
            raise BadRequest("Nothing to speak after removing formatting")
        if len(clean) > self.s.max_tts_chars:
            clean = clean[: self.s.max_tts_chars]

        gender = gender if gender in ("female", "male") else "female"
        key = hashlib.sha256(f"{self.provider.name}|{lang}|{gender}|{clean}".encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        chunks = split_for_tts(clean)
        # Chunks are independent requests, so run them concurrently (bounded) to cut latency.
        sem = asyncio.Semaphore(3)

        async def one(chunk: str) -> bytes:
            async with sem:
                raw = await self.provider.synthesize(chunk, lang, gender)
            try:
                return audio_utils.to_pcm16_wav(raw)  # providers differ (Bhashini sends 32-bit float): normalise once, here
            except ValueError as exc:
                raise UpstreamError(f"{self.provider.name} returned audio in an unexpected format", code=f"{self.provider.name}_error") from exc

        parts = await asyncio.gather(*(one(c) for c in chunks))
        wav = audio_utils.concat_wavs(list(parts))

        self._cache[key] = wav
        while len(self._cache) > self.s.tts_cache_items:
            self._cache.popitem(last=False)
        return wav
