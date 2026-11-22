"""Auth, chat, voice, agents, tasks, preferences and dashboard schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.conversation import ConversationOut, MessageOut, ToolExecutionOut
from app.schemas.family import FamilyMemberRef


# ---------------------------------------------------------------- auth
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    display_name: str
    is_guest: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GuestIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


# ---------------------------------------------------------------- chat
class ChatIn(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=4000, description="Omit when regenerate=true")
    input_mode: Literal["text", "voice"] = "text"
    language: str | None = Field(default=None, max_length=8, description="Language code; defaults to the conversation's language")
    voice_output: bool = False
    regenerate: bool = False


class ChatOut(BaseModel):
    conversation: ConversationOut
    user_message: MessageOut | None
    assistant_message: MessageOut | None
    messages: list[MessageOut] = Field(description="Every message produced in this turn, in order")
    tool_executions: list[ToolExecutionOut] = Field(default=[], description="Every tool execution touched in this turn (latest state). After a confirm call this holds the outcome of the confirmed action.")
    pending_confirmation: ToolExecutionOut | None = None
    language: str
    execution_id: uuid.UUID | None


class ConfirmIn(BaseModel):
    approve: bool


# ---------------------------------------------------------------- voice
class TranscribeOut(BaseModel):
    text: str
    language: str
    duration_seconds: float


class SynthesizeIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="en", max_length=8)
    gender: Literal["female", "male"] | None = None


# ---------------------------------------------------------------- agents
class AgentToolInfo(BaseModel):
    name: str
    description: str
    category: str
    requires_confirmation: bool
    enabled: bool


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str
    model: str
    tools: list[AgentToolInfo]


class ExecutionOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_title: str | None = None
    status: str
    intent: str | None
    model: str | None
    steps: int
    latency_ms: int | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    tool_executions: list[ToolExecutionOut]


class ExecutionPage(BaseModel):
    items: list[ExecutionOut]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------- tasks
class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ref: str
    kind: str
    title: str
    description: str | None
    status: str
    due_at: datetime | None
    payload: dict[str, Any]
    conversation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int


class TaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "done", "cancelled"]


# ---------------------------------------------------------------- preferences & languages
class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Literal["system", "light", "dark"]
    voice_output_enabled: bool
    auto_play_responses: bool
    auto_send_voice: bool
    auto_detect_language: bool
    tts_gender: Literal["female", "male"]
    show_tool_details: bool
    silence_timeout_ms: int
    symptom_checkins: bool = True
    sms_reminders: bool = False
    sms_available: bool = False  # whether this server can send texts at all (set from the server's settings, not stored)
    primary_language: str = "en"
    secondary_languages: list[str] = []


class PreferencesUpdate(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    voice_output_enabled: bool | None = None
    auto_play_responses: bool | None = None
    auto_send_voice: bool | None = None
    sms_reminders: bool | None = None
    symptom_checkins: bool | None = None
    auto_detect_language: bool | None = None
    tts_gender: Literal["female", "male"] | None = None
    show_tool_details: bool | None = None
    silence_timeout_ms: int | None = Field(default=None, ge=500, le=5000)
    primary_language: str | None = Field(default=None, max_length=8)
    secondary_languages: list[str] | None = None


class LanguageOut(BaseModel):
    code: str
    name: str
    native_name: str
    asr: bool
    tts: bool


# ---------------------------------------------------------------- providers & appointments
class ProviderOut(BaseModel):
    code: str
    name: str
    kind: str
    doctor_name: str | None
    specialties: list[str]
    city: str
    state: str
    address: str | None
    phone: str | None
    languages: list[str]
    fee_inr: int
    accepts_ayushman: bool
    teleconsultation: bool
    is_demo: bool
    next_available: dict[str, str] | None = None
    rating_avg: float | None = Field(default=None, description="Average of real patient ratings; null until feedback exists")
    rating_count: int = 0
    source: Literal["partner", "osm", "demo"] = Field(default="partner", description="'osm' = a real place from OpenStreetMap with no online slots")
    lat: float | None = None
    lon: float | None = None
    website: str | None = None
    opening_hours: str | None = None


class SlotsOut(BaseModel):
    provider: ProviderOut
    timezone: str = "Asia/Kolkata"
    slot_minutes: int
    open_slots: dict[str, list[str]] = Field(description="local date (YYYY-MM-DD) -> open start times (HH:MM, IST)")


class ReminderInfo(BaseModel):
    kind: str
    due_at: datetime
    status: str


class AppointmentOut(BaseModel):
    id: uuid.UUID
    ref: str
    status: Literal["booked", "cancelled", "completed"]
    mode: str
    starts_at: datetime
    ends_at: datetime
    patient_name: str
    patient_mobile: str = Field(description="masked, e.g. 98XXXXXX10")
    reason: str
    language: str
    provider: ProviderOut
    reschedule_count: int
    feedback_rating: int | None
    feedback_comment: str | None
    conversation_id: uuid.UUID | None
    clinic_confirmed: bool = Field(default=True, description="False = a visit the user PLANNED at a real place; the clinic has not confirmed it, so the user should phone to confirm")
    family_member: FamilyMemberRef | None = Field(default=None, description="Set when the visit is for a saved family member")
    reminders: list[ReminderInfo] = []
    created_at: datetime


class AppointmentPage(BaseModel):
    items: list[AppointmentOut]
    total: int
    limit: int
    offset: int


class BookIn(BaseModel):
    provider_code: str | None = Field(default=None, min_length=3, max_length=24, description="A partner clinic with online slots (see /providers). Send this OR place_id")
    place_id: str | None = Field(default=None, max_length=40, description="A real place from /places/search (e.g. 'osm:node/123'): the visit is only PLANNED, the clinic does not confirm it")
    slot_start: str = Field(description="Partner clinic: IST slot exactly as returned by availability. Real place: any IST time at least 2 hours ahead. Format 'YYYY-MM-DD HH:MM'")
    patient_name: str = Field(min_length=2, max_length=80)
    patient_mobile: str = Field(min_length=10, max_length=16)
    reason: str = Field(min_length=3, max_length=300)
    mode: Literal["in_person", "teleconsultation"] = "in_person"
    language: str | None = Field(default=None, max_length=8, description="Language code for reminders; defaults to the user's primary language")
    family_member_id: uuid.UUID | None = Field(default=None, description="Book for one of the user's saved family members (see /family)")


    @model_validator(mode="after")
    def _one_target(self) -> "BookIn":
        if bool(self.provider_code) == bool(self.place_id):
            raise ValueError("send exactly one of provider_code or place_id")
        return self


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: Literal["appointment_reminder", "follow_up", "feedback_request", "medicine", "symptom_checkin", "vaccine"]
    title: str
    message: str = Field(description="Text in the user's language when translation was available")
    language: str
    appointment_ref: str | None
    conversation_id: uuid.UUID | None
    delivered_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int


# ---------------------------------------------------------------- dashboard / health
class DashboardOut(BaseModel):
    conversations: int
    messages: int
    voice_messages: int
    tool_runs: int
    open_tasks: int
    submitted_requests: int
    appointments_total: int
    unread_notifications: int
    upcoming_appointments: list[AppointmentOut]
    tool_usage: list[dict[str, Any]]
    recent_conversations: list[ConversationOut]
    recent_executions: list[ExecutionOut]


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    speech_provider: Literal["sarvam", "bhashini"] = Field(description="Main speech-to-text / text-to-speech provider")
    speech_fallback_provider: Literal["sarvam", "bhashini"] | None = Field(default=None, description="Backup speech provider used automatically if the main one fails")
    speech_configured: bool = Field(description="True when the active speech provider has credentials")
    max_audio_seconds: float = Field(description="Longest recording the speech provider accepts; clients must stop recording before this")
    bhashini_configured: bool
    sarvam_configured: bool
    llm_configured: bool
    llm_model: str
    llm_fallback_model: str | None = Field(default=None, description="Model used automatically when the primary model fails")
    web_search_configured: bool
    demo_mode: bool = Field(description="True when demo helpers (simulate visit / remind now) and sample provider data are enabled")
    version: str

