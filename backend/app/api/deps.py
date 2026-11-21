"""FastAPI dependencies that hand out the shared services created at startup."""
from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.services.agent_service import AgentService
from app.services.speech_service import SpeechService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


def get_speech_service(request: Request) -> SpeechService:
    return request.app.state.speech_service
