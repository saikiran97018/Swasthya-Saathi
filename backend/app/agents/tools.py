"""Modular tool system for the healthcare agent.

Design rules (security):
  * The model can only call tools registered here -- no SQL, shell or arbitrary HTTP.
  * Every call's arguments are validated by a Pydantic model before the tool runs.
  * Tools that change state in a way the user should approve set `requires_confirmation = True`;
    the orchestrator then pauses and waits for the user's explicit yes before running them.
  * Every tool is scoped to the calling user (`ctx.user`): it can never see other users' data.
  * Business rules (slots, double-booking, limits) live in services, not in the model's hands.
  * Tool output is data, never instructions (the system prompt tells the model so).
"""
from __future__ import annotations

import asyncio
import logging
import json
import time
from urllib.parse import urlencode
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, ClassVar, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import forms as forms_catalog
from app.agents import triage
from app.core.config import Settings
from app.core.errors import AppError
from app.database.models import Conversation, User
from app.database.repositories.family import FamilyRepository
from app.database.repositories.knowledge import DirectoryRepository, KnowledgeRepository
from app.database.repositories.providers import ProviderRepository
from app.database.repositories.tasks import TaskRepository
from app.services import scheduling as sched
from app.services.appointments import AppointmentService, BookingError, appointment_dict
from app.services.places import PlacesService
from app.services.webhooks import send_webhook
from app.utils.language import LANGUAGES, is_supported

MAX_RESULT_CHARS = 4000
log = logging.getLogger("app.tools")

SpecialtyName = Literal["general medicine", "pediatrics", "gynecology", "dermatology", "cardiology", "orthopedics", "ophthalmology", "ent", "dentistry", "psychiatry"]
# Shown to users in the tool card, so it must read as a plain statement (the model is told to mention it in the system prompt).
DEMO_NOTE = "These provider listings are SAMPLE (demo) data until connected to a real hospital system."


class ToolError(Exception):
    """A tool failed in a way the model can understand and recover from."""


@dataclass
class ToolContext:
    session: AsyncSession
    user: User
    conversation: Conversation
    settings: Settings
    http: httpx.AsyncClient
    places: PlacesService | None = None
    language_changed_to: str | None = None

    def appointments(self) -> AppointmentService:
        return AppointmentService(self.session, self.settings, self.http)


@dataclass
class ToolResult:
    data: dict[str, Any]
    summary: str


@dataclass
class ExecutionOutcome:
    status: Literal["success", "error"]
    data: dict[str, Any]
    summary: str
    duration_ms: int
    error: str | None = None


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[type[BaseModel]]
    requires_confirmation: ClassVar[bool] = False
    category: ClassVar[str] = "read"  # read | write | external

    def enabled(self, settings: Settings) -> bool:
        return True

    async def explain(self, args: BaseModel, ctx: ToolContext) -> str:
        return f"Run {self.name}"

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:  # pragma: no cover - interface
        raise NotImplementedError


def _clean_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _clean_schema(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_clean_schema(v) for v in node]
    return node


# Rules the model does not need to see: every tool call is validated again on our side (parse_args), and these are
# the biggest part of the schema. Sending less keeps each request small, which matters on free-tier token limits.
_VALIDATION_ONLY = {"title", "minLength", "maxLength", "minimum", "maximum", "default", "additionalProperties"}


def _compact_schema(node: Any) -> Any:
    if isinstance(node, dict):
        any_of = node.get("anyOf")
        if isinstance(any_of, list):
            # Optional[X] is {"anyOf": [X, {"type": "null"}]}. Write it as {"type": [X, "null"]}: shorter, and the model may
            # still send null for a field it does not know (Groq validates tool calls strictly and would reject null otherwise).
            real = [o for o in any_of if o.get("type") != "null"]
            if len(real) == 1 and isinstance(real[0].get("type"), str) and len(real) < len(any_of):
                merged = {**real[0], **{k: v for k, v in node.items() if k != "anyOf"}}
                merged["type"] = [real[0]["type"], "null"]
                if "enum" in merged:
                    merged["enum"] = [*merged["enum"], None]
                return _compact_schema(merged)
        out = {}
        for k, v in node.items():
            if k in _VALIDATION_ONLY:
                continue
            # "properties" maps parameter NAMES to schemas: never drop a parameter that happens to be called "title"
            out[k] = {name: _compact_schema(sub) for name, sub in v.items()} if k == "properties" and isinstance(v, dict) else _compact_schema(v)
        return out
    if isinstance(node, list):
        return [_compact_schema(v) for v in node]
    return node


def _parse_date(raw: str | None, field: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip()[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ToolError(f"{field} must look like YYYY-MM-DD") from exc


def _parse_slot(raw: str) -> datetime:
    try:
        return sched.parse_local_slot(raw)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


# ================================================================== triage & knowledge


class UrgencyArgs(BaseModel):
    symptoms: str = Field(min_length=3, max_length=600, description="The patient's symptoms described in ENGLISH, with duration if known")
    age: int | None = Field(default=None, ge=0, le=120, description="Patient age in years, if known")
    pregnant: bool | None = Field(default=None, description="True if the patient is pregnant")


class AssessUrgency(Tool):
    name = "assess_urgency"
    description = (
        "Check how urgent the patient's symptoms are (emergency / urgent / routine) and which kind of doctor to see. "
        "Call this FIRST whenever the user describes symptoms or asks which doctor to see. If urgency is 'emergency', "
        "tell them to call 112/108 immediately and do NOT book an appointment."
    )
    params = UrgencyArgs

    async def run(self, ctx: ToolContext, args: UrgencyArgs) -> ToolResult:
        out = triage.assess(args.symptoms, args.age, args.pregnant)
        return ToolResult(out, f"Urgency: {out['urgency']}; suggested specialty: {out['suggested_specialty']}")


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=2, max_length=200, description="Search query in ENGLISH (the knowledge base is English), e.g. 'Ayushman card eligibility'")
    top_k: int = Field(default=3, ge=1, le=5)


class SearchKnowledgeBase(Tool):
    name = "search_knowledge_base"
    description = (
        "Search the curated health knowledge base: health schemes (Ayushman Bharat, ABHA, e-Sanjeevani), pregnancy and child health, "
        "immunisation, diabetes/hypertension, TB, mental health, first aid, emergency numbers and how this service works. Write the query in English."
    )
    params = SearchKnowledgeArgs

    async def run(self, ctx: ToolContext, args: SearchKnowledgeArgs) -> ToolResult:
        hits = await KnowledgeRepository(ctx.session).search(args.query, args.top_k)
        if not hits:
            return ToolResult({"results": [], "note": "No matching knowledge base entries."}, "No knowledge base matches")
        results = [{"title": h.title, "category": h.category, "text": h.text, "source": h.source_url} for h in hits]
        return ToolResult({"results": results}, f"Found {len(results)} knowledge base entr{'y' if len(results) == 1 else 'ies'}: {hits[0].title}")


class DirectoryArgs(BaseModel):
    category: Literal["emergency", "health", "mental_health", "insurance", "digital_health"] | None = Field(default=None, description="Service category")
    query: str | None = Field(default=None, max_length=120, description="Optional keywords in English, e.g. 'ambulance' or 'tuberculosis'")


class LookupServiceDirectory(Tool):
    name = "lookup_service_directory"
    description = "Look up official health helpline numbers, portals and government health services (emergency, mental health, insurance, digital health)."
    params = DirectoryArgs

    async def run(self, ctx: ToolContext, args: DirectoryArgs) -> ToolResult:
        rows = await DirectoryRepository(ctx.session).search(category=args.category, query=args.query, state=None)
        results = [{"name": r.name, "category": r.category, "description": r.description, "phone": r.phone, "website": r.website} for r in rows]
        return ToolResult({"results": results}, f"{len(results)} directory entries")


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="Web search query (English works best)")
    max_results: int = Field(default=4, ge=1, le=6)


class WebSearch(Tool):
    name = "web_search"
    description = "Search the web for current information the knowledge base does not cover (recent advisories, news). Not for medical diagnosis."
    params = WebSearchArgs
    category = "external"

    def enabled(self, settings: Settings) -> bool:
        return settings.web_search_configured

    async def run(self, ctx: ToolContext, args: WebSearchArgs) -> ToolResult:
        s = ctx.settings
        try:
            if s.tavily_api_key:
                r = await ctx.http.post(
                    "https://api.tavily.com/search",
                    json={"query": args.query, "max_results": args.max_results, "search_depth": "basic"},
                    headers={"Authorization": f"Bearer {s.tavily_api_key}"},
                )
                r.raise_for_status()
                items = [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:400]} for x in r.json().get("results", [])]
            else:
                r = await ctx.http.get(s.searxng_url.rstrip("/") + "/search", params={"q": args.query, "format": "json"})
                r.raise_for_status()
                items = [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:400]} for x in r.json().get("results", [])[: args.max_results]]
        except httpx.HTTPError as exc:
            raise ToolError(f"Web search failed: {type(exc).__name__}") from exc
        return ToolResult({"results": items[: args.max_results]}, f"{len(items[: args.max_results])} web results for '{args.query}'")


# =================================================================== providers & booking


class FindProvidersArgs(BaseModel):
    specialty: SpecialtyName | None = Field(default=None, description="Kind of doctor; use the suggested_specialty from assess_urgency")
    city: str | None = Field(default=None, max_length=80, description="City or town, e.g. 'Guntur' or 'Bengaluru'")
    language: str | None = Field(default=None, description="Language code the doctor should speak, e.g. 'te'")
    teleconsultation: bool | None = Field(default=None, description="True to only show video/phone consultation options")
    accepts_ayushman: bool | None = Field(default=None, description="True to only show providers that accept the Ayushman Bharat card")


class FindHealthcareProviders(Tool):
    name = "find_healthcare_providers"
    description = (
        "Find clinics, hospitals, health centres and teleconsultation services by specialty, city, doctor language, or Ayushman acceptance. "
        "Returns provider codes (use them with check_availability and book_appointment), fees and the next free slot. "
        "Ask the user for their city first if you do not know it."
    )
    params = FindProvidersArgs

    async def run(self, ctx: ToolContext, args: FindProvidersArgs) -> ToolResult:
        repo, svc = ProviderRepository(ctx.session), ctx.appointments()
        found = await repo.search(specialty=args.specialty, city=args.city, language=args.language, teleconsultation=args.teleconsultation, accepts_ayushman=args.accepts_ayushman)
        results: list[dict[str, Any]] = []

        async def partner_entry(p) -> dict[str, Any]:  # a partner clinic runs its own online slots
            slots = await svc.open_slots(p, days=7)
            nxt = next(iter(slots.items()), None)
            return {
                "code": p.code, "name": p.name, "doctor": p.doctor_name, "type": p.kind, "specialties": p.specialties, "city": p.city,
                "languages": p.languages, "fee_inr": p.fee_inr, "accepts_ayushman": p.accepts_ayushman, "teleconsultation": p.teleconsultation,
                "next_available": {"date": nxt[0], "time": nxt[1][0]} if nxt else None, "bookable_online": True, "is_demo_listing": p.is_demo,
            }

        for p in found:
            results.append(await partner_entry(p))
        data: dict[str, Any] = {"results": results}
        notes: list[str] = []

        if args.city and ctx.places is not None and not args.teleconsultation:
            try:
                nearby = (await ctx.places.search(city=args.city, specialty=args.specialty, radius_km=8, limit=5)).places
            except AppError as exc:
                nearby = []
                notes.append(f"Could not look up real places near {args.city} right now ({exc.message}). Tell the user and offer to try again.")
            for place in nearby[: max(0, 5 - len(results))]:
                provider = await repo.get_or_create_from_place(place, fallback_city=args.city)
                results.append({
                    "code": provider.code, "name": place.name, "type": place.kind, "specialties": place.specialties, "address": place.address,
                    "phone": place.phone, "distance_km": place.distance_km, "opening_hours": place.opening_hours, "bookable_online": False,
                })
            if any(not r.get("bookable_online") for r in results):
                notes.append(
                    "Places without bookable_online come from OpenStreetMap (community-edited): phone numbers and hours may be missing or out of date, "
                    "and they have NO online booking. Never invent fees, doctors or slots for them. A visit there is only PLANNED: the user must phone to confirm."
                )
        if args.city and not results:  # nothing in person: any registered teleconsultation service works from anywhere in India
            tele = await repo.search(specialty=args.specialty, language=args.language, teleconsultation=True)
            for p in tele:
                results.append(await partner_entry(p))
            if tele:
                notes.append(f"No in-person place found in {args.city}; showing teleconsultation options that work from anywhere in India.")
            elif args.teleconsultation:
                notes.append("No teleconsultation service is registered; point the user to e-Sanjeevani from lookup_service_directory.")
        if not args.city and not found:
            notes.append("Ask the user for their city or town first.")
        if not results:
            data["available_cities"] = await repo.cities()
            notes.append("Nothing matched. Try another specialty, a larger nearby town, or a different spelling.")
        if any(p.is_demo for p in found):
            data["data_source_notice"] = DEMO_NOTE
        if notes:
            data["note"] = " ".join(notes)
        return ToolResult(data, f"{len(results)} place(s): " + ", ".join(r["name"] for r in results[:3]) if results else "No places found")


class AvailabilityArgs(BaseModel):
    provider_code: str = Field(min_length=3, max_length=24, description="Provider code from find_healthcare_providers, e.g. HC-GNT-01")
    from_date: str | None = Field(default=None, description="First date to check, YYYY-MM-DD (default: earliest possible)")
    days: int = Field(default=3, ge=1, le=7, description="How many days to show")


class CheckAvailability(Tool):
    name = "check_availability"
    description = "Show the open appointment times of one provider (Indian Standard Time). Always call this before booking so you offer only real free slots."
    params = AvailabilityArgs

    async def run(self, ctx: ToolContext, args: AvailabilityArgs) -> ToolResult:
        provider = await ProviderRepository(ctx.session).get_by_code(args.provider_code)
        if provider is None:
            raise ToolError(f"No provider with code {args.provider_code}. Use find_healthcare_providers to get valid codes.")
        if provider.source == "osm":  # a real place: there is no slot list to show
            earliest = ctx.appointments().earliest_visit_time()
            return ToolResult(
                {
                    "provider": {"code": provider.code, "name": provider.name, "city": provider.city, "phone": provider.phone, "address": provider.address},
                    "bookable_online": False, "opening_hours": provider.opening_hours,
                    "earliest_visit_time_ist": earliest.strftime("%Y-%m-%d %H:%M"),
                    "note": (
                        f"{provider.name} has no online slots. Ask the user for the date and time they prefer; it must be {earliest.strftime('%Y-%m-%d %H:%M')} "
                        "(Indian time) or later, never earlier, so offer that exact time if they want to go as soon as possible. Then call book_appointment with that slot_start: "
                        "it saves a PLANNED visit that the clinic has NOT confirmed. "
                        "Tell the user to phone the clinic to confirm" + (f" on {provider.phone}." if provider.phone else " (no phone number is listed).")
                    ),
                },
                f"{provider.name} has no online slots (planned visit only)",
            )
        slots = await ctx.appointments().open_slots(provider, from_date=_parse_date(args.from_date, "from_date"), days=args.days)
        trimmed = {d: (t if len(t) <= 14 else t[:14] + [f"... (+{len(t) - 14} more)"]) for d, t in slots.items()}
        data = {
            "provider": {"code": provider.code, "name": provider.name, "doctor": provider.doctor_name, "city": provider.city},
            "slot_minutes": provider.slot_minutes, "fee_inr": provider.fee_inr, "timezone": "IST (Indian Standard Time)",
            "open_slots": trimmed,
        }
        if not slots:
            data["note"] = "No open slots in this period. Try later dates or another provider."
        return ToolResult(data, f"{sum(len(t) for t in slots.values())} open slots over {len(slots)} day(s) at {provider.name}")


class BookArgs(BaseModel):
    provider_code: str = Field(min_length=3, max_length=24)
    slot_start: str = Field(description="Indian time 'YYYY-MM-DD HH:MM': a slot exactly as returned by check_availability, or for a place without online slots the user's chosen time, e.g. '2026-11-23 10:20'")
    patient_name: str = Field(min_length=2, max_length=80, description="Full name of the patient")
    patient_mobile: str = Field(min_length=10, max_length=16, description="10-digit Indian mobile number of the patient")
    reason: str = Field(min_length=3, max_length=300, description="Short reason for the visit")
    mode: Literal["in_person", "teleconsultation"] = "in_person"


class BookAppointment(Tool):
    name = "book_appointment"
    description = (
        "Book a doctor appointment in a free slot. Needs the patient's name, mobile number and reason, and a slot from check_availability. "
        "Reminders and a feedback request are scheduled automatically. The user must confirm before this runs: first read the details back "
        "(provider, date, time, patient) and tell them what you are about to do."
    )
    params = BookArgs
    requires_confirmation = True
    category = "write"

    async def explain(self, args: BookArgs, ctx: ToolContext) -> str:
        provider = await ProviderRepository(ctx.session).get_by_code(args.provider_code)
        try:
            when = sched.describe(sched.parse_local_slot(args.slot_start))["display"]
        except ValueError:
            when = args.slot_start
        where = f"{provider.name} ({provider.city})" if provider else args.provider_code
        mode = " by teleconsultation" if args.mode == "teleconsultation" else ""
        if provider is not None and provider.source == "osm":
            return (
                f"Save a PLANNED visit at {where} on {when} for {args.patient_name} (mobile {args.patient_mobile}). Reason: {args.reason}. "
                "The clinic has NOT confirmed this time: you will need to phone them"
            )
        return f"Book an appointment{mode} at {where} on {when} for {args.patient_name} (mobile {args.patient_mobile}). Reason: {args.reason}"

    async def run(self, ctx: ToolContext, args: BookArgs) -> ToolResult:
        provider = await ProviderRepository(ctx.session).get_by_code(args.provider_code)
        if provider is None:
            raise ToolError(f"No provider with code {args.provider_code}.")
        svc = ctx.appointments()
        # Booking for someone saved under Family? A name that matches a profile links the visit to that person.
        member = await FamilyRepository(ctx.session).find_by_name(ctx.user.id, args.patient_name)
        try:
            appt = await svc.book(
                user=ctx.user, conversation_id=ctx.conversation.id, provider=provider, starts_at=_parse_slot(args.slot_start),
                patient_name=args.patient_name, patient_mobile=args.patient_mobile, reason=args.reason, mode=args.mode, language=ctx.conversation.language,
                family_member_id=member.id if member else None,
            )
        except BookingError as exc:
            raise ToolError(exc.message) from exc
        data = {**appointment_dict(appt), "reminders_scheduled": await svc.reminder_times(appt)}
        if provider.source != "osm":
            data["fee_inr"] = provider.fee_inr
        if provider.is_demo:
            data["data_source_notice"] = DEMO_NOTE
        verb = "Booked" if appt.clinic_confirmed else "Saved planned visit"
        return ToolResult(data, f"{verb} {appt.ref} with {provider.name} on {data['when']}")


class ListAppointmentsArgs(BaseModel):
    scope: Literal["upcoming", "past", "all"] = "upcoming"


class ListAppointments(Tool):
    name = "list_appointments"
    description = "List the user's appointments with reference codes, provider, date/time and status. Use it before cancelling, rescheduling or giving feedback."
    params = ListAppointmentsArgs

    async def run(self, ctx: ToolContext, args: ListAppointmentsArgs) -> ToolResult:
        rows, total = await ctx.appointments().appts.list_for_user(ctx.user.id, scope=args.scope, limit=15)
        return ToolResult({"total": total, "appointments": [appointment_dict(a) for a in rows]}, f"{total} appointment(s) ({args.scope})")


class CancelArgs(BaseModel):
    reference: str = Field(min_length=4, max_length=24, description="Appointment reference such as AP-7K3QX")
    reason: str | None = Field(default=None, max_length=300)


class CancelAppointment(Tool):
    name = "cancel_appointment"
    description = "Cancel one of the user's upcoming appointments by reference. The user must confirm first; tell them which appointment you will cancel."
    params = CancelArgs
    requires_confirmation = True
    category = "write"

    async def explain(self, args: CancelArgs, ctx: ToolContext) -> str:
        appt = await ctx.appointments().appts.get_by_ref(ctx.user.id, args.reference)
        if appt is None:
            return f"Cancel appointment {args.reference}"
        return f"Cancel appointment {appt.ref} at {appt.provider.name} on {appointment_dict(appt)['when']} for {appt.patient_name}"

    async def run(self, ctx: ToolContext, args: CancelArgs) -> ToolResult:
        svc = ctx.appointments()
        appt = await svc.appts.get_by_ref(ctx.user.id, args.reference)
        if appt is None:
            raise ToolError(f"No appointment {args.reference} found. Use list_appointments to see valid references.")
        try:
            await svc.cancel(appt, args.reason)
        except BookingError as exc:
            raise ToolError(exc.message) from exc
        return ToolResult({"reference": appt.ref, "status": appt.status}, f"Cancelled {appt.ref}")


class RescheduleArgs(BaseModel):
    reference: str = Field(min_length=4, max_length=24)
    new_slot_start: str = Field(description="New slot as 'YYYY-MM-DD HH:MM' (Indian time) from check_availability for the same provider")


class RescheduleAppointment(Tool):
    name = "reschedule_appointment"
    description = "Move an upcoming appointment to another free slot of the same provider. Check availability first. The user must confirm before this runs."
    params = RescheduleArgs
    requires_confirmation = True
    category = "write"

    async def explain(self, args: RescheduleArgs, ctx: ToolContext) -> str:
        appt = await ctx.appointments().appts.get_by_ref(ctx.user.id, args.reference)
        try:
            new = sched.describe(sched.parse_local_slot(args.new_slot_start))["display"]
        except ValueError:
            new = args.new_slot_start
        if appt is None:
            return f"Reschedule appointment {args.reference} to {new}"
        return f"Move appointment {appt.ref} at {appt.provider.name} from {appointment_dict(appt)['when']} to {new}"

    async def run(self, ctx: ToolContext, args: RescheduleArgs) -> ToolResult:
        svc = ctx.appointments()
        appt = await svc.appts.get_by_ref(ctx.user.id, args.reference)
        if appt is None:
            raise ToolError(f"No appointment {args.reference} found.")
        try:
            await svc.reschedule(appt, _parse_slot(args.new_slot_start))
        except BookingError as exc:
            raise ToolError(exc.message) from exc
        data = {**appointment_dict(appt), "reminders_scheduled": await svc.reminder_times(appt)}
        return ToolResult(data, f"Rescheduled {appt.ref} to {data['when']}")


class FollowUpArgs(BaseModel):
    appointment_reference: str = Field(min_length=4, max_length=24)
    follow_up_date: str = Field(description="Date the follow-up visit is due, YYYY-MM-DD (a future date)")
    note: str | None = Field(default=None, max_length=300, description="What to check at the follow-up, e.g. 'repeat blood test'")


class ScheduleFollowUp(Tool):
    name = "schedule_follow_up"
    description = "Set a follow-up reminder for after a visit (the user gets a notification on that date to book the next visit). Use when the doctor or user mentions a follow-up or review."
    params = FollowUpArgs
    category = "write"

    async def run(self, ctx: ToolContext, args: FollowUpArgs) -> ToolResult:
        svc = ctx.appointments()
        appt = await svc.appts.get_by_ref(ctx.user.id, args.appointment_reference)
        if appt is None:
            raise ToolError(f"No appointment {args.appointment_reference} found.")
        due = _parse_date(args.follow_up_date, "follow_up_date")
        try:
            r = await svc.schedule_follow_up(appt, due, args.note)  # type: ignore[arg-type]
        except BookingError as exc:
            raise ToolError(exc.message) from exc
        return ToolResult({"appointment": appt.ref, "reminder_on": sched.describe(r.due_at)["display"], "note": args.note}, f"Follow-up reminder set for {args.follow_up_date}")


class FeedbackArgs(BaseModel):
    appointment_reference: str = Field(min_length=4, max_length=24)
    rating: int = Field(ge=1, le=5, description="1 (poor) to 5 (excellent)")
    comment: str | None = Field(default=None, max_length=500, description="The user's comment, in their own words")


class RecordFeedback(Tool):
    name = "record_feedback"
    description = "Save the user's rating (1-5) and comment about a completed appointment. Ask for the rating if they only gave a comment."
    params = FeedbackArgs
    category = "write"

    async def run(self, ctx: ToolContext, args: FeedbackArgs) -> ToolResult:
        svc = ctx.appointments()
        appt = await svc.appts.get_by_ref(ctx.user.id, args.appointment_reference)
        if appt is None:
            raise ToolError(f"No appointment {args.appointment_reference} found.")
        try:
            await svc.record_feedback(appt, args.rating, args.comment)
        except BookingError as exc:
            raise ToolError(exc.message) from exc
        return ToolResult({"appointment": appt.ref, "rating": args.rating}, f"Saved feedback {args.rating}/5 for {appt.ref}")


# ======================================================================= forms (facilitator help)

_FormId = Literal["ayushman_card_help", "abha_creation_help"]


class FormAssistArgs(BaseModel):
    form_id: _FormId
    fields: dict[str, str] = Field(default_factory=dict, description="Values the user has given so far, keyed by field name. Pass ALL known values every time.")


class FormAssistant(Tool):
    name = "form_assistant"
    description = (
        "Help the user fill a supported request form step by step: 'ayushman_card_help' (Ayushman Bharat card) or 'abha_creation_help' (ABHA health ID). "
        "Pass every value collected so far; the tool validates them and returns what is still missing or wrong. Ask for missing fields one or two at a time."
    )
    params = FormAssistArgs

    async def run(self, ctx: ToolContext, args: FormAssistArgs) -> ToolResult:
        spec = forms_catalog.FORMS[args.form_id]
        check = forms_catalog.check_form(args.form_id, dict(args.fields))
        out: dict[str, Any] = {
            "form": spec.title, "validated_values": check.cleaned, "errors": check.errors,
            "missing": [{"field": f.name, "label": f.label, "hint": f.hint} for f in check.missing],
            "ready_to_submit": check.ready,
        }
        if check.ready:
            out["next_step"] = "Read the details back to the user, then call submit_service_request after they agree."
        return ToolResult(out, "Form complete and valid" if check.ready else f"{len(check.missing)} field(s) missing, {len(check.errors)} error(s)")


class SubmitRequestArgs(BaseModel):
    form_id: _FormId
    fields: dict[str, str] = Field(description="Complete set of form values")


class SubmitServiceRequest(Tool):
    name = "submit_service_request"
    description = (
        "Submit a completed, validated assistance form and get a reference number so a facilitator can call the user back. "
        "Only call after form_assistant reported ready_to_submit and you read the details back. The user must confirm before this runs."
    )
    params = SubmitRequestArgs
    requires_confirmation = True
    category = "write"

    async def explain(self, args: SubmitRequestArgs, ctx: ToolContext) -> str:
        spec = forms_catalog.FORMS[args.form_id]
        return f"Submit '{spec.title}' with: " + "; ".join(f"{k}: {v}" for k, v in args.fields.items())

    async def run(self, ctx: ToolContext, args: SubmitRequestArgs) -> ToolResult:
        spec = forms_catalog.FORMS[args.form_id]
        check = forms_catalog.check_form(args.form_id, dict(args.fields))
        if not check.ready:  # re-validate: never trust that the model checked first
            problems = list(check.errors.values()) + [f"{f.label} is missing" for f in check.missing]
            raise ToolError("Form is not valid: " + "; ".join(problems))
        task = await TaskRepository(ctx.session).create(
            user_id=ctx.user.id, conversation_id=ctx.conversation.id, title=spec.title, description=spec.submit_note,
            kind="service_request", status="submitted", payload={"form_id": args.form_id, "fields": check.cleaned, "language": ctx.conversation.language},
        )
        forwarded = await send_webhook(ctx.http, ctx.settings, "service_request.submitted", {"reference": task.ref, "form_id": args.form_id, "fields": check.cleaned})
        task.payload = {**task.payload, "webhook": forwarded}
        data = {"reference": task.ref, "status": task.status, "form": spec.title, "note": spec.submit_note, "forwarded_to_external_system": forwarded.get("ok", False)}
        return ToolResult(data, f"Submitted {spec.title}: reference {task.ref}")


# ============================================================================== tasks


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    due_date: str | None = Field(default=None, description="Optional due date, YYYY-MM-DD")

    @field_validator("due_date")
    @classmethod
    def _check_date(cls, v: str | None) -> str | None:
        if v:
            datetime.strptime(v[:10], "%Y-%m-%d")
        return v[:10] if v else v


class CreateTask(Tool):
    name = "create_task"
    description = "Create a personal health to-do for the user (e.g. 'get blood test before the visit', 'bring previous reports'). Returns a short reference code."
    params = CreateTaskArgs
    category = "write"

    async def run(self, ctx: ToolContext, args: CreateTaskArgs) -> ToolResult:
        due = datetime.strptime(args.due_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.due_date else None
        task = await TaskRepository(ctx.session).create(user_id=ctx.user.id, conversation_id=ctx.conversation.id, title=args.title, description=args.description, due_at=due)
        return ToolResult({"reference": task.ref, "title": task.title, "due_date": args.due_date, "status": task.status}, f"Created task {task.ref}: {task.title}")


class ListTasksArgs(BaseModel):
    status: Literal["open", "in_progress", "done", "cancelled", "submitted"] | None = None
    kind: Literal["task", "service_request"] | None = None


class ListTasks(Tool):
    name = "list_tasks"
    description = "List the user's to-dos and submitted assistance requests with their status, optionally filtered."
    params = ListTasksArgs

    async def run(self, ctx: ToolContext, args: ListTasksArgs) -> ToolResult:
        rows, total = await TaskRepository(ctx.session).list_for_user(ctx.user.id, status=args.status, kind=args.kind, limit=20)
        items = [{"reference": t.ref, "kind": t.kind, "title": t.title, "status": t.status, "due": t.due_at.date().isoformat() if t.due_at else None} for t in rows]
        return ToolResult({"total": total, "items": items}, f"{total} item(s)")


class UpdateTaskArgs(BaseModel):
    reference: str = Field(min_length=3, max_length=32, description="Task reference such as T-AB3XK")
    status: Literal["open", "in_progress", "done", "cancelled"]


class UpdateTaskStatus(Tool):
    name = "update_task_status"
    description = "Change the status of one of the user's to-dos (open, in_progress, done, cancelled) using its reference code."
    params = UpdateTaskArgs
    category = "write"

    async def run(self, ctx: ToolContext, args: UpdateTaskArgs) -> ToolResult:
        task = await TaskRepository(ctx.session).get_by_ref(ctx.user.id, args.reference)
        if task is None:
            raise ToolError(f"No task with reference {args.reference}. Use list_tasks to see valid references.")
        if task.kind == "service_request":
            raise ToolError("Submitted requests cannot be edited here.")
        task.status = args.status
        return ToolResult({"reference": task.ref, "status": task.status}, f"{task.ref} is now {task.status}")


# ============================================================================= language


# Screens the assistant can open for the user. The browser validates this list again and never navigates anywhere else.
UI_PAGES: dict[str, tuple[str, str]] = {
    "home": ("/", "Home"), "chat": ("/chat", "AI Consult"), "doctors": ("/find-care", "Doctors"), "care_plan": ("/appointments", "Care Plan"),
    "family": ("/family", "Family"), "sos": ("/sos", "SOS"), "history": ("/history", "History"), "activity": ("/activity", "Activity"),
    "settings": ("/settings", "Settings"), "language_settings": ("/settings/language", "Language settings"), "live_call": ("/call", "Live call"),
}


class ControlAppArgs(BaseModel):
    action: Literal["open_page", "set_theme"]
    page: Literal["home", "chat", "doctors", "care_plan", "family", "sos", "history", "activity", "settings", "language_settings", "live_call"] | None = Field(
        default=None, description="For open_page: the screen to open"
    )
    city: str | None = Field(default=None, max_length=80, description="For the doctors screen: a city to search straight away")
    theme: Literal["light", "dark", "system"] | None = Field(default=None, description="For set_theme")


class ControlApp(Tool):
    name = "control_app"
    description = (
        "Control the app on the user's screen: open one of its pages (home, AI chat, doctors, care plan, family, SOS, history, activity, settings, "
        "language settings, live call; for doctors an optional city starts the search) or switch light/dark theme. Use it when the user asks "
        "to open, show or go to a screen or to change the look. It only changes what is on screen; it never books or changes any data."
    )
    params = ControlAppArgs
    category = "read"

    async def run(self, ctx: ToolContext, args: ControlAppArgs) -> ToolResult:
        if args.action == "set_theme":
            if not args.theme:
                raise ToolError("theme is required for set_theme: light, dark or system")
            return ToolResult({"ui_action": {"type": "set_theme", "theme": args.theme}, "done": f"The {args.theme} theme is now on the user's screen."}, f"Switched to the {args.theme} theme")
        if not args.page:
            raise ToolError("page is required for open_page")
        path, label = UI_PAGES[args.page]
        city = " ".join((args.city or "").split())
        if args.page == "doctors" and city:
            path += "?" + urlencode({"city": city[:80]})
        return ToolResult({"ui_action": {"type": "open_page", "page": args.page, "path": path, "label": label}, "done": f"{label} is now open on the user's screen."}, f"Opened {label}")


class SetLanguageArgs(BaseModel):
    language_code: str = Field(description="One of: " + ", ".join(LANGUAGES))


class SetLanguage(Tool):
    name = "set_language"
    description = "Switch the language of this conversation. Call ONLY when the user explicitly asks to change language (e.g. 'speak in Telugu')."
    params = SetLanguageArgs
    category = "write"

    async def run(self, ctx: ToolContext, args: SetLanguageArgs) -> ToolResult:
        code = args.language_code.strip().lower()
        if not is_supported(code):
            raise ToolError(f"Unsupported language '{code}'. Supported: {', '.join(LANGUAGES)}")
        ctx.conversation.language = code
        ctx.language_changed_to = code
        return ToolResult({"language": code, "name": LANGUAGES[code].name}, f"Language set to {LANGUAGES[code].name}")


# ============================================================================ registry


# What the MODEL reads about each tool (kept short: it is sent with every request). The fuller `description` on each
# tool class is for people (Agents screen, docs). The behavioural rules (when to call what, confirmation) live in prompts.py.
MODEL_DESCRIPTIONS = {
    "assess_urgency": "Rate urgency (emergency/urgent/routine) and suggest a doctor type. Call FIRST for any symptoms. If emergency: tell them to call 112/108 and never book.",
    "find_healthcare_providers": "Find real hospitals and clinics near a city or town (OpenStreetMap), plus partner clinics with online slots. Returns codes, address, phone, distance. Ask the city first.",
    "check_availability": "Open slots of one provider (IST). For a real place it says there are no online slots. Always call before booking.",
    "book_appointment": "Book a partner slot from check_availability, or save a PLANNED visit (clinic not confirmed) at a real place at the user's chosen time. User confirms first; read the details back.",
    "list_appointments": "List the user's appointments (reference, provider, time, status).",
    "reschedule_appointment": "Move an upcoming appointment to another free slot of the same provider (check availability first). User confirms first.",
    "cancel_appointment": "Cancel an upcoming appointment by reference. User confirms first.",
    "schedule_follow_up": "Set a follow-up reminder for a future date.",
    "record_feedback": "Save a 1-5 rating and comment for a completed appointment.",
    "search_knowledge_base": "Search health knowledge: schemes, pregnancy, child health, vaccines, diabetes, TB, mental health, first aid. Query in English.",
    "lookup_service_directory": "Official health helplines, portals and government health services.",
    "form_assistant": "Fill a request form step by step ('ayushman_card_help' or 'abha_creation_help'). Pass every value collected so far.",
    "submit_service_request": "Submit a validated form after form_assistant says ready_to_submit. User confirms first.",
    "create_task": "Create a personal health to-do.",
    "list_tasks": "List the user's to-dos and service requests.",
    "update_task_status": "Set a to-do's status by reference.",
    "set_language": "Switch the conversation language. Only when the user explicitly asks.",
    "control_app": "Open an app page (doctors, care plan, family, SOS, settings, live call ...) or switch light/dark theme on the user's screen. Only when asked.",
}


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def enabled_tools(self, settings: Settings) -> list[Tool]:
        return [t for t in self._tools.values() if t.enabled(settings)]

    def specs(self, settings: Settings) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": t.name, "description": MODEL_DESCRIPTIONS.get(t.name, t.description), "parameters": _compact_schema(t.params.model_json_schema())}}
            for t in self.enabled_tools(settings)
        ]

    def parse_args(self, tool: Tool, raw: str) -> BaseModel:
        """Parse + validate the model's JSON arguments. Raises ToolError with a model-readable message."""
        try:
            payload = json.loads(raw) if raw and raw.strip() else {}
            if not isinstance(payload, dict):
                raise ValueError("arguments must be a JSON object")
            return tool.params.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            if isinstance(exc, ValidationError):
                msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            else:
                msg = str(exc)
            raise ToolError(f"Invalid arguments for {tool.name}: {msg}") from exc

    async def execute(self, tool: Tool, args: BaseModel, ctx: ToolContext) -> ExecutionOutcome:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(tool.run(ctx, args), timeout=ctx.settings.tool_timeout_seconds)
            data, summary, status, error = result.data, result.summary, "success", None
        except ToolError as exc:
            data, summary, status, error = {"error": str(exc)}, str(exc), "error", str(exc)
        except asyncio.TimeoutError:
            msg = f"{tool.name} timed out"
            data, summary, status, error = {"error": msg}, msg, "error", msg
        except Exception as exc:  # never let a tool bug crash the conversation
            msg = f"{tool.name} failed unexpectedly"
            log.exception("tool %s crashed", tool.name)
            data, summary, status, error = {"error": msg}, msg, "error", f"{msg}: {type(exc).__name__}"
        encoded = json.dumps(data, ensure_ascii=False, default=str)
        if len(encoded) > MAX_RESULT_CHARS:
            data = {"truncated": True, "partial": encoded[:MAX_RESULT_CHARS]}
        return ExecutionOutcome(status, data, summary, int((time.perf_counter() - started) * 1000), error)


def build_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            AssessUrgency(),
            FindHealthcareProviders(),
            CheckAvailability(),
            BookAppointment(),
            ListAppointments(),
            RescheduleAppointment(),
            CancelAppointment(),
            ScheduleFollowUp(),
            RecordFeedback(),
            SearchKnowledgeBase(),
            LookupServiceDirectory(),
            FormAssistant(),
            SubmitServiceRequest(),
            CreateTask(),
            ListTasks(),
            UpdateTaskStatus(),
            WebSearch(),
            SetLanguage(),
            ControlApp(),
        ]
    )
