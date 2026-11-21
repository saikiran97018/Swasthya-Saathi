"""SQLAlchemy models.

Portable types only (Uuid, JSON, timezone-aware DateTime) so the same schema runs on
PostgreSQL in production and SQLite in the test-suite.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always store UTC and always return timezone-aware datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- users


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Guest")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(20), default="user")

    preferences: Mapped["UserPreference | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    languages: Mapped[list["LanguagePreference"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserPreference(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    theme: Mapped[str] = mapped_column(String(10), default="system")
    voice_output_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_play_responses: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_send_voice: Mapped[bool] = mapped_column(Boolean, default=True)  # speaking is enough: no extra Send tap (can be turned off in Settings)
    auto_detect_language: Mapped[bool] = mapped_column(Boolean, default=True)
    tts_gender: Mapped[str] = mapped_column(String(10), default="female")
    show_tool_details: Mapped[bool] = mapped_column(Boolean, default=True)
    silence_timeout_ms: Mapped[int] = mapped_column(Integer, default=1500)

    user: Mapped[User] = relationship(back_populates="preferences")


class LanguagePreference(IdMixin, TimestampMixin, Base):
    __tablename__ = "language_preferences"
    __table_args__ = (UniqueConstraint("user_id", "language_code", name="uq_language_pref_user_code"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    language_code: Mapped[str] = mapped_column(String(8))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="languages")


# ------------------------------------------------------------------- conversations


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_last_message", "user_id", "last_message_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    title_is_auto: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.seq"
    )
    meta: Mapped["ConversationMetadata | None"] = relationship(
        back_populates="conversation", uselist=False, cascade="all, delete-orphan"
    )


class ConversationMetadata(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversation_metadata"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), unique=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    voice_message_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summarized_until_seq: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="meta")


class Message(IdMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
        CheckConstraint("role in ('user','assistant','tool','system')", name="ck_messages_role"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    input_mode: Mapped[str] = mapped_column(String(8), default="text")  # text | voice
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# --------------------------------------------------------------------- agent runs


class AgentExecution(IdMixin, Base):
    __tablename__ = "agent_executions"
    __table_args__ = (Index("ix_agent_exec_user_started", "user_id", "started_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    tool_logs: Mapped[list["ToolExecutionLog"]] = relationship(back_populates="execution", cascade="all, delete-orphan")


class ToolExecutionLog(IdMixin, Base):
    __tablename__ = "tool_execution_logs"
    __table_args__ = (Index("ix_tool_logs_user_created", "user_id", "created_at"),)

    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_executions.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_call_id: Mapped[str] = mapped_column(String(80))
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # running | success | error | awaiting_confirmation | denied | cancelled
    status: Mapped[str] = mapped_column(String(24), default="running")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=func.now())

    execution: Mapped[AgentExecution] = relationship(back_populates="tool_logs")


# ---------------------------------------------------------------- tasks & requests


class Task(IdMixin, TimestampMixin, Base):
    """A to-do item OR a submitted service request (kind), each with a short human reference."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    ref: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="task")  # task | service_request
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|in_progress|done|cancelled|submitted
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ------------------------------------------------- healthcare: providers & appointments


class Provider(IdMixin, TimestampMixin, Base):
    """A clinic / hospital / health centre / teleconsultation service that can take appointments."""

    __tablename__ = "providers"
    __table_args__ = (Index("ix_providers_city", "city"),)

    code: Mapped[str] = mapped_column(String(24), unique=True)  # short, speakable id, e.g. HC-GNT-01
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="clinic")  # hospital | clinic | phc | telemedicine
    doctor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    specialties: Mapped[list[str]] = mapped_column(JSON, default=list)
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    # weekly opening windows (IST): [{"days":[0,1,2,3,4], "start":"10:00", "end":"13:00"}], Monday = 0
    schedule: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=20)
    fee_inr: Mapped[int] = mapped_column(Integer, default=0)
    accepts_ayushman: Mapped[bool] = mapped_column(Boolean, default=False)
    teleconsultation: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)  # sample data until connected to a real system
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Where the listing comes from: "partner" (a clinic that registered its own schedule), "osm" (a real place found on
    # OpenStreetMap: no online slots, visits are only PLANNED) or "demo" (invented sample data).
    source: Mapped[str] = mapped_column(String(12), default="partner")
    osm_id: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)  # e.g. "node/123456"
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(String(300), nullable=True)


class FamilyMember(IdMixin, TimestampMixin, Base):
    """Someone the account holder books care for (a parent, a child ...). Deleting one keeps their past appointments."""

    __tablename__ = "family_members"
    __table_args__ = (Index("ix_family_members_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    relation: Mapped[str] = mapped_column(String(16), default="other")  # self|spouse|child|parent|sibling|other
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)  # female|male|other
    mobile: Mapped[str | None] = mapped_column(String(15), nullable=True)  # normalised 10-digit Indian mobile
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)


class EmergencyContact(IdMixin, TimestampMixin, Base):
    """A person the user wants one tap away on the SOS screen. The app never calls or messages them by itself."""

    __tablename__ = "emergency_contacts"
    __table_args__ = (Index("ix_emergency_contacts_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(15))  # normalised 10-digit Indian mobile
    relation: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Appointment(IdMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # The database itself refuses two *active, clinic-confirmed* bookings of the same provider slot (race-proof
        # double-booking guard). A PLANNED visit (clinic_confirmed = false) is only the user's own note, so it never blocks anyone.
        Index(
            "uq_appointments_active_slot", "provider_id", "starts_at", unique=True,
            sqlite_where=text("status = 'booked' AND clinic_confirmed"), postgresql_where=text("status = 'booked' AND clinic_confirmed"),
        ),
        Index("ix_appointments_user_start", "user_id", "starts_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("providers.id", ondelete="RESTRICT"))
    ref: Mapped[str] = mapped_column(String(24), unique=True)  # AP-XXXXX
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="booked")  # booked | cancelled | completed
    mode: Mapped[str] = mapped_column(String(16), default="in_person")  # in_person | teleconsultation
    patient_name: Mapped[str] = mapped_column(String(120))
    patient_mobile: Mapped[str] = mapped_column(String(15))
    reason: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_member_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True)
    # True: a slot the clinic itself offers and holds. False: a visit the user PLANNED at a real place that has no online
    # booking; the clinic has not confirmed it and the user is told to phone them.
    clinic_confirmed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)

    provider: Mapped[Provider] = relationship()
    family_member: Mapped["FamilyMember | None"] = relationship()


class Reminder(IdMixin, TimestampMixin, Base):
    """Scheduled in-app notification: appointment reminders, follow-up visits, feedback requests."""

    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_status_due", "status", "due_at"),
        Index("ix_reminders_user_delivered", "user_id", "delivered_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(24))  # appointment_reminder | follow_up | feedback_request
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)  # English source text
    language: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | delivered | cancelled
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delivered_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # text in the user's language
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ------------------------------------------------------------- knowledge & directory


class KnowledgeDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), default="general")
    language: Mapped[str] = mapped_column(String(8), default="en")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(IdMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class ServiceDirectoryEntry(IdMixin, TimestampMixin, Base):
    """Helplines and national/state services the agent may look up (read-only for the agent)."""

    __tablename__ = "service_directory"
    __table_args__ = (Index("ix_service_directory_category", "category"),)

    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)  # null => national
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
