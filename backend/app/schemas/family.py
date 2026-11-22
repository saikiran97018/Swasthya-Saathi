"""Family profiles, emergency contacts and the SOS screen."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Relation = Literal["self", "spouse", "child", "parent", "sibling", "other"]
Gender = Literal["female", "male", "other"]


def _clean_name(v: str) -> str:
    v = " ".join(v.split())
    if len(v) < 2:
        raise ValueError("name must be at least 2 characters")
    return v


# ---------------------------------------------------------------- family
class FamilyMemberIn(BaseModel):
    name: str = Field(max_length=80)
    relation: Relation = "other"
    birth_year: int | None = Field(default=None, ge=1900)
    birth_date: date | None = Field(default=None, description="Exact date of birth (optional): needed for a child's vaccination schedule")
    gender: Gender | None = None
    mobile: str | None = Field(default=None, max_length=20, description="10-digit Indian mobile; optional")
    language: str | None = Field(default=None, max_length=8)

    _name = field_validator("name")(_clean_name)

    @field_validator("birth_year")
    @classmethod
    def _not_future(cls, v: int | None) -> int | None:
        if v is not None and v > date.today().year:
            raise ValueError("birth_year cannot be in the future")
        return v


class FamilyMemberUpdate(BaseModel):
    """Partial update: only the fields that are sent change (send null to clear an optional one)."""

    name: str | None = Field(default=None, max_length=80)
    relation: Relation | None = None
    birth_year: int | None = Field(default=None, ge=1900)
    birth_date: date | None = None
    gender: Gender | None = None
    mobile: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=8)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)

    @field_validator("birth_year")
    @classmethod
    def _not_future(cls, v: int | None) -> int | None:
        if v is not None and v > date.today().year:
            raise ValueError("birth_year cannot be in the future")
        return v


class FamilyMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    relation: Relation
    birth_year: int | None
    birth_date: date | None = None
    gender: Gender | None
    mobile: str | None
    language: str | None
    created_at: datetime


class FamilyMemberRef(BaseModel):
    """What an appointment shows about the person it is for."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    relation: str


# ---------------------------------------------------------------- emergency contacts
class EmergencyContactIn(BaseModel):
    name: str = Field(max_length=80)
    phone: str = Field(max_length=20, description="10-digit Indian mobile number")
    relation: str | None = Field(default=None, max_length=40)

    _name = field_validator("name")(_clean_name)


class EmergencyContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    phone: str
    relation: str | None
    created_at: datetime


# ---------------------------------------------------------------- SOS
class SosNumber(BaseModel):
    code: str
    label: str
    description: str
    kind: Literal["emergency", "ambulance", "women", "child", "mental_health", "other"]


class SosFacility(BaseModel):
    code: str
    name: str
    kind: str
    city: str | None
    address: str | None
    phone: str | None
    teleconsultation: bool = False
    is_demo: bool = False
    lat: float | None = None
    lon: float | None = None
    distance_km: float | None = None
    source: Literal["openstreetmap", "google", "partner"] = "openstreetmap"


# ---------------------------------------------------------------- places search
class PlaceOut(BaseModel):
    id: str = Field(description="'osm:node/123' (OpenStreetMap) or 'gmaps:<id>' (Google), or the partner clinic's provider code")
    name: str
    kind: Literal["hospital", "clinic", "doctor", "phc", "pharmacy", "other"]
    specialties: list[str] = []
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    website: str | None = None
    opening_hours: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_km: float | None = None
    emergency: bool = False
    rating: float | None = Field(default=None, description="Google rating out of 5 (Google results only)")
    rating_count: int | None = None
    maps_url: str | None = Field(default=None, description="The place on Google Maps (Google results only)")
    source: Literal["openstreetmap", "google", "partner"]
    has_slots: bool = Field(description="True only for partner clinics with online appointment slots")
    provider_code: str | None = Field(default=None, description="Set for partner clinics; OpenStreetMap places are booked through place_id")


class SearchCenter(BaseModel):
    lat: float
    lon: float
    label: str | None = None


class PlacesOut(BaseModel):
    center: SearchCenter | None
    items: list[PlaceOut]
    attribution: str
    note: str | None = None


class FirstAidCard(BaseModel):
    id: str
    title: str
    steps: list[str]
    call_if: str


class SosOut(BaseModel):
    numbers: list[SosNumber]
    nearby: list[SosFacility] = Field(description="Hospitals and health centres in the requested city (empty without a city)")
    first_aid: list[FirstAidCard]
    disclaimer: str
