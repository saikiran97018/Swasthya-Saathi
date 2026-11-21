"""Application settings, loaded from environment variables / a .env file.

Every secret (API keys, DB password, JWT secret) lives here and is read from the
environment. Nothing sensitive is hardcoded anywhere else in the codebase.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app -----------------------------------------------------------------
    app_name: str = "Swasthya Saathi"
    environment: str = "development"  # development | test | production
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Folder holding the built web app (frontend/dist). When set, this server also serves the web app, so one service
    # (one address, no CORS, WebSockets on the same origin) is the whole product. The Docker image sets it.
    static_dir: str = ""

    # --- database ------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/voiceagent"
    # Create tables from the models on startup. Only for tests/quick demos; use Alembic otherwise.
    auto_create_tables: bool = False
    # Seed the knowledge base + service directory when they are empty.
    auto_seed: bool = True

    # --- auth ----------------------------------------------------------------
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24 * 7

    # --- Bhashini (STT / TTS) ------------------------------------------------
    bhashini_user_id: str = ""
    bhashini_ulca_api_key: str = ""
    bhashini_pipeline_id: str = "64392f96daac500b55c543cd"
    bhashini_config_url: str = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
    bhashini_tts_sampling_rate: int = 8000
    bhashini_timeout_seconds: float = 30.0
    bhashini_config_cache_seconds: int = 3600

    # --- Sarvam AI (speech + optional LLM) -------------------------------------
    sarvam_api_key: str = ""
    sarvam_stt_url: str = "https://api.sarvam.ai/speech-to-text"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_stt_mode: str = "transcribe"  # transcribe | codemix | verbatim ...
    sarvam_tts_url: str = "https://api.sarvam.ai/text-to-speech"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker_female: str = "priya"  # speakers are model-specific; these two belong to bulbul:v3
    sarvam_tts_speaker_male: str = "shubh"
    sarvam_tts_sample_rate: int = 22050
    sarvam_timeout_seconds: float = 30.0

    # --- speech provider: auto = Sarvam when SARVAM_API_KEY is set, otherwise Bhashini -----
    speech_provider: str = "auto"  # auto | sarvam | bhashini
    # Backup used automatically when the main speech provider fails. auto = the other provider if it has credentials.
    speech_fallback_provider: str = "auto"  # auto | none | sarvam | bhashini

    # --- LLM (any OpenAI-compatible endpoint serving an open-source model) ---
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    llm_extra_body: str = ""  # optional JSON merged into every request, e.g. {"reasoning_effort":"low"}
    llm_temperature: float = 0.3
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 60.0

    # Optional second LLM used automatically when the primary fails (rate limit, outage, timeout).
    # Example: Sarvam  https://api.sarvam.ai/v1  +  sarvam-105b-conversations
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    llm_fallback_extra_body: str = ""

    # --- optional tools ------------------------------------------------------
    tavily_api_key: str = ""  # enables web_search
    searxng_url: str = ""  # alternative: self-hosted SearXNG, e.g. http://localhost:8080
    # Outbound integration: booked/cancelled appointments, reminders and service requests are POSTed here
    # (HMAC-SHA256 signed in X-Signature) so a real hospital / HMIS / SMS gateway can act on them.
    webhook_url: str = ""
    webhook_secret: str = ""

    # --- healthcare behaviour ------------------------------------------------
    reminder_poll_seconds: int = 30  # 0 disables the background reminder loop (tests call it directly)
    demo_mode: bool = False  # enables demo helpers (simulate a completed visit / send a reminder now)
    # Sample clinics with invented schedules, for demos and tests only. OFF by default: real places come from OpenStreetMap.
    seed_demo_providers: bool = False
    booking_horizon_days: int = 14
    max_active_appointments: int = 5
    # A "planned visit" at a real place (no online slots): at least this far ahead and at most this many days out.
    planned_visit_min_lead_minutes: int = 120
    planned_visit_horizon_days: int = 60

    # --- live voice calls: Agora Conversational AI (real-time voice agent) + Murf Falcon (text to speech) ------
    agora_app_id: str = ""
    agora_app_certificate: str = ""  # used to sign tokens; with it no Customer ID / Secret is needed
    agora_customer_id: str = ""  # optional alternative to token auth for the REST calls (Basic auth)
    agora_customer_secret: str = ""
    agora_api_base: str = "https://api.agora.io/api/conversational-ai-agent"
    # Public https base URL where AGORA'S CLOUD can reach this server (a tunnel such as ngrok or cloudflared, or a deployment).
    # Set: the voice agent talks through this server, so it can use every tool (find clinics, plan visits ...).
    # Empty: the agent talks to Groq directly and can chat but cannot take actions.
    agora_public_url: str = ""
    agora_asr_vendor: str = "ares"  # ares (Agora's own, many Indian languages) | sarvam (uses SARVAM_API_KEY)
    agora_idle_timeout_seconds: int = 120
    agora_session_minutes: int = 60
    murf_api_key: str = ""
    murf_model: str = "FALCON"  # Falcon 2.1; Murf also accepts "falcon-2.1"
    murf_ws_url: str = "wss://global.api.murf.ai/v1/speech/stream-input"
    murf_sample_rate: int = 24000
    murf_voices: str = ""  # optional JSON object {"te": "Anisha", "hi": "Ayushi"} to override the default voice per language

    # --- real places (OpenStreetMap: Nominatim to find a city, Overpass to list hospitals and clinics) ------
    places_enabled: bool = True
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    # Nominatim is the main source (fast and reliable). Overpass is OPTIONAL and more complete for big cities; the public
    # servers are often overloaded, so it is off unless you set a URL, e.g. https://overpass-api.de/api/interpreter
    overpass_url: str = ""
    overpass_fallback_url: str = ""
    places_timeout_seconds: float = 12.0
    places_cache_seconds: int = 6 * 3600
    places_request_gap_seconds: float = 1.1  # Nominatim's usage policy: at most one request per second

    # --- agent behaviour -----------------------------------------------------
    agent_max_steps: int = 5
    history_message_limit: int = 30
    summary_trigger_messages: int = 24
    tool_timeout_seconds: float = 20.0

    # --- limits --------------------------------------------------------------
    max_audio_bytes: int = 10 * 1024 * 1024
    max_audio_seconds: float = 60.0
    max_message_chars: int = 4000
    max_tts_chars: int = 3000
    tts_cache_items: int = 64
    rate_limit_per_minute: int = 240
    rate_limit_ai_per_minute: int = 40
    trust_proxy_headers: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret == _DEFAULT_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set to a strong random value in production")
        if self.speech_provider not in ("auto", "sarvam", "bhashini"):
            raise ValueError("SPEECH_PROVIDER must be auto, sarvam or bhashini")
        if self.speech_fallback_provider not in ("auto", "none", "sarvam", "bhashini"):
            raise ValueError("SPEECH_FALLBACK_PROVIDER must be auto, none, sarvam or bhashini")
        for name in ("llm_extra_body", "llm_fallback_extra_body"):
            raw = getattr(self, name)
            if raw.strip():
                try:
                    if not isinstance(json.loads(raw), dict):
                        raise ValueError
                except ValueError as exc:
                    raise ValueError(f"{name.upper()} must be a JSON object, e.g. {{\"reasoning_effort\": \"low\"}}") from exc
        if self.agora_asr_vendor not in ("ares", "sarvam"):
            raise ValueError("AGORA_ASR_VENDOR must be ares or sarvam")
        if self.murf_voices.strip():
            try:
                voices = json.loads(self.murf_voices)
                if not isinstance(voices, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in voices.items()):
                    raise ValueError
            except ValueError as exc:
                raise ValueError('MURF_VOICES must be a JSON object of language code to Murf voice id, e.g. {"te": "Anisha"}') from exc
        if not self.agora_public_url and os.environ.get("RENDER_EXTERNAL_URL"):
            # On Render the service already has a public https address (RENDER_EXTERNAL_URL): no tunnel needed for live calls.
            self.agora_public_url = os.environ["RENDER_EXTERNAL_URL"].strip().rstrip("/")
        if self.agora_public_url and not self.agora_public_url.startswith("https://"):
            raise ValueError("AGORA_PUBLIC_URL must start with https:// (Agora only calls HTTPS endpoints)")
        return self

    @property
    def agora_configured(self) -> bool:
        return bool(self.agora_app_id and self.agora_app_certificate)

    @property
    def murf_configured(self) -> bool:
        return bool(self.murf_api_key)

    @property
    def agora_mode(self) -> str:
        """tools = the agent talks through this server (all tools); chat_only = straight to the LLM; unconfigured."""
        if not (self.agora_configured and self.murf_configured):
            return "unconfigured"
        return "tools" if self.agora_public_url else "chat_only"

    @property
    def sarvam_configured(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def resolved_speech_provider(self) -> str:
        if self.speech_provider == "auto":
            return "sarvam" if self.sarvam_configured else "bhashini"
        return self.speech_provider

    @property
    def resolved_speech_fallback(self) -> str | None:
        """Name of the backup speech provider, or None (also None when the backup has no credentials)."""
        primary = self.resolved_speech_provider
        choice = self.speech_fallback_provider
        if choice == "none":
            return None
        name = ("bhashini" if primary == "sarvam" else "sarvam") if choice == "auto" else choice
        if name == primary:
            return None
        return name if (self.sarvam_configured if name == "sarvam" else self.bhashini_configured) else None

    @property
    def llm_fallback_configured(self) -> bool:
        local = "localhost" in self.llm_fallback_base_url or "127.0.0.1" in self.llm_fallback_base_url
        return bool(self.llm_fallback_base_url and self.llm_fallback_model and (self.llm_fallback_api_key or local))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bhashini_configured(self) -> bool:
        return bool(self.bhashini_user_id and self.bhashini_ulca_api_key)

    @property
    def llm_primary_configured(self) -> bool:
        # Local servers (Ollama, vLLM) often need no key, so accept a localhost base URL as configured.
        return bool(self.llm_api_key) or "localhost" in self.llm_base_url or "127.0.0.1" in self.llm_base_url

    @property
    def llm_configured(self) -> bool:
        return self.llm_primary_configured or self.llm_fallback_configured

    @property
    def web_search_configured(self) -> bool:
        return bool(self.tavily_api_key or self.searxng_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
