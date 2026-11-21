from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.database.models import Conversation, ConversationMetadata, Message, ToolExecutionLog


class ToolExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID | None
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    summary: str | None
    explanation: str | None
    status: str
    requires_confirmation: bool
    duration_ms: int | None
    error: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    seq: int
    role: Literal["user", "assistant"]
    content: str
    language: str | None
    input_mode: Literal["text", "voice"]
    source: Literal["user", "ai", "tool"] = Field(description="'tool' when the answer used external tools/data, else 'ai'")
    tools_used: list[str] = []
    tool_executions: list[ToolExecutionOut] = []
    pending_confirmation: bool = False
    created_at: datetime

    @classmethod
    def from_model(cls, m: Message, logs: list[ToolExecutionLog] | None = None) -> "MessageOut":
        logs = logs or []
        tools_used = list(m.meta.get("tools_used", [])) if m.meta else []
        if m.role == "assistant" and not tools_used:
            tools_used = [l.tool_name for l in logs if l.status == "success"]
        source = "user" if m.role == "user" else ("tool" if tools_used else "ai")
        return cls(
            id=m.id,
            conversation_id=m.conversation_id,
            seq=m.seq,
            role=m.role,  # type: ignore[arg-type]
            content=m.content or "",
            language=m.language,
            input_mode=m.input_mode if m.input_mode in ("text", "voice") else "text",  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            tools_used=tools_used,
            tool_executions=[ToolExecutionOut.model_validate(l) for l in logs],
            pending_confirmation=any(l.status == "awaiting_confirmation" for l in logs),
            created_at=m.created_at,
        )


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    language: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    message_count: int = 0
    voice_message_count: int = 0
    summary: str | None = None

    @classmethod
    def from_model(cls, c: Conversation, meta: ConversationMetadata | None = None) -> "ConversationOut":
        return cls(
            id=c.id,
            title=c.title,
            language=c.language,
            created_at=c.created_at,
            updated_at=c.updated_at,
            last_message_at=c.last_message_at,
            message_count=meta.message_count if meta else 0,
            voice_message_count=meta.voice_message_count if meta else 0,
            summary=meta.summary if meta else None,
        )


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=8)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationPage(BaseModel):
    items: list[ConversationOut]
    total: int
    limit: int
    offset: int
