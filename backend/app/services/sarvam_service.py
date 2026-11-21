"""Sarvam AI speech client: speech-to-text (Saaras) and text-to-speech (Bulbul).

STT: POST /speech-to-text   multipart: file, model, mode, language_code   header: api-subscription-key
TTS: POST /text-to-speech   JSON: text, language_code, model, speaker, ...  -> {"audios": [base64 WAV]}
Both use BCP-47 style codes ("te-IN"); Odia is "od-IN". REST speech-to-text accepts at most 30 s of audio.
"""
from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, UpstreamError

log = logging.getLogger("app.sarvam")

# our code -> Sarvam code
_STT_CODES = {
    "en": "en-IN", "hi": "hi-IN", "bn": "bn-IN", "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN", "or": "od-IN", "pa": "pa-IN",
    "ta": "ta-IN", "te": "te-IN", "gu": "gu-IN", "as": "as-IN", "ur": "ur-IN", "sa": "sa-IN",
}
# Bulbul speaks 11 languages
_TTS_CODES = {k: v for k, v in _STT_CODES.items() if k in ("en", "hi", "bn", "kn", "ml", "mr", "or", "pa", "ta", "te", "gu")}


class SarvamService:
    name = "sarvam"
    max_audio_seconds: float | None = 30.0  # Sarvam REST STT limit

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client or httpx.AsyncClient(timeout=settings.sarvam_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def configured(self) -> bool:
        return self.s.sarvam_configured

    def supports(self, language: str, task: str) -> bool:
        return language in (_STT_CODES if task == "asr" else _TTS_CODES)

    def _require(self) -> None:
        if not self.configured:
            raise ServiceUnavailable("Sarvam is not configured. Set SARVAM_API_KEY in the backend .env file.", code="sarvam_not_configured")

    def _headers(self) -> dict[str, str]:
        return {"api-subscription-key": self.s.sarvam_api_key}

    # ---- speech to text ---------------------------------------------------------------------------
    async def transcribe(self, wav_bytes: bytes, language: str, sample_rate: int = 16000) -> str:
        self._require()
        code = _STT_CODES.get(language)
        if code is None:
            raise UpstreamError(f"Sarvam has no speech recognition for '{language}'", code="sarvam_no_model")
        data = {"model": self.s.sarvam_stt_model, "mode": self.s.sarvam_stt_mode, "language_code": code}
        files = {"file": ("speech.wav", wav_bytes, "audio/wav")}
        body = await self._post(self.s.sarvam_stt_url, what="speech recognition", data=data, files=files)
        try:
            return (body.get("transcript") or "").strip()
        except AttributeError as exc:
            raise UpstreamError("Unexpected response from Sarvam speech recognition", code="sarvam_error") from exc

    # ---- text to speech ---------------------------------------------------------------------------
    async def synthesize(self, text: str, language: str, gender: str = "female") -> bytes:
        """WAV bytes for one short piece of text (callers chunk long text; Sarvam allows 2,500 characters)."""
        self._require()
        code = _TTS_CODES.get(language)
        if code is None:
            raise UpstreamError(f"Sarvam has no text-to-speech for '{language}'", code="sarvam_no_model")
        speaker = self.s.sarvam_tts_speaker_male if gender == "male" else self.s.sarvam_tts_speaker_female
        payload = {
            "text": text,
            "language_code": code,
            "model": self.s.sarvam_tts_model,
            "speaker": speaker,  # always explicit: a speaker must belong to the chosen model
            "speech_sample_rate": self.s.sarvam_tts_sample_rate,
            "output_audio_codec": "wav",
            "enable_preprocessing": True,  # reads numbers / dates / mixed-script text naturally
        }
        body = await self._post(self.s.sarvam_tts_url, what="speech synthesis", json=payload)
        try:
            return base64.b64decode(body["audios"][0])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise UpstreamError("Unexpected response from Sarvam speech synthesis", code="sarvam_error") from exc

    # ---- http ---------------------------------------------------------------------------------------
    async def _post(self, url: str, *, what: str, **kwargs) -> dict:
        try:
            resp = await self._client.post(url, headers=self._headers(), **kwargs)
        except httpx.TimeoutException as exc:
            raise UpstreamError(f"Sarvam {what} timed out", retryable=True, code="sarvam_timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Could not reach Sarvam for {what}", retryable=True, code="sarvam_unreachable") from exc

        if resp.status_code >= 400:
            detail = _error_message(resp)
            log.warning("Sarvam %s failed: HTTP %s %s", what, resp.status_code, detail)
            if resp.status_code in (401, 403):
                raise UpstreamError("Sarvam rejected the API key (check SARVAM_API_KEY)", code="sarvam_auth_failed")
            if resp.status_code == 402:
                raise UpstreamError("Sarvam account is out of credits", code="sarvam_no_credits")
            if resp.status_code == 429:
                raise UpstreamError(f"Sarvam {what} is rate limited, please retry shortly", retryable=True, code="sarvam_rate_limited")
            raise UpstreamError(
                f"Sarvam {what} failed (HTTP {resp.status_code}){': ' + detail if resp.status_code == 400 and detail else ''}",
                retryable=resp.status_code >= 500, code="sarvam_error",
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise UpstreamError(f"Sarvam {what} returned invalid JSON", code="sarvam_error") from exc


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message", ""))[:200]
        return str(data.get("detail", ""))[:200]
    except (ValueError, AttributeError):
        return ""
