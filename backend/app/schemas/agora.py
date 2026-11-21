"""Live voice calls (Agora Conversational AI + Murf Falcon)."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class CallLanguageOut(BaseModel):
    code: str
    name: str
    native_name: str
    voice: str = Field(description="Murf Falcon voice used for this language")


class AgoraStatus(BaseModel):
    configured: bool = Field(description="True when Agora and Murf credentials are present")
    murf_configured: bool
    mode: Literal["tools", "chat_only", "unconfigured"]
    languages: list[CallLanguageOut]
    note: str | None = None


class CallStartIn(BaseModel):
    language: str | None = Field(default=None, max_length=8, description="One of the languages from /agora/status; defaults to English")
    conversation_id: uuid.UUID | None = Field(default=None, description="Continue an existing conversation; otherwise a new one is created")


class CallVoice(BaseModel):
    vendor: Literal["murf"] = "murf"
    voice_id: str
    locale: str


class CallStartOut(BaseModel):
    app_id: str
    channel: str
    token: str = Field(description="Short-lived RTC token for THIS channel and uid only")
    uid: int
    agent_uid: int
    agent_id: str
    conversation_id: uuid.UUID
    language: str
    mode: Literal["tools", "chat_only"]
    expires_in: int
    greeting: str
    voice: CallVoice
