"""Rule-based urgency check and specialty suggestion.

Deliberately NOT left to the language model: red-flag detection must be deterministic, auditable and
conservative. It is a safety net that tells people to call emergency services, not a diagnosis.
"""
from __future__ import annotations

import re
from typing import Any

EMERGENCY_NUMBERS = {"unified_emergency": "112", "ambulance": "108", "mental_health_crisis_tele_manas": "14416"}

_EMERGENCY: list[tuple[str, str]] = [
    (r"chest (pain|tightness|pressure)|pain in (the )?chest", "chest pain"),
    (r"(difficulty|trouble|struggling|hard) (in |to )?breath|can'?t breathe|cannot breathe|gasping|severe breathless", "difficulty breathing"),
    (r"unconscious|unresponsive|not waking|passed out|collapsed", "loss of consciousness"),
    (r"seizure|convulsion|\bfits\b|fitting", "seizure"),
    (r"face (is )?droop|slurred speech|can'?t speak|sudden (numbness|weakness)|weakness (on|of) (one|the left|the right)", "possible stroke signs"),
    (r"(severe|heavy|profuse|uncontrolled) bleeding|bleeding (won'?t|will not|does not) stop|vomit(ing)? blood|cough(ing)? (up )?blood", "severe bleeding"),
    (r"poison|overdose|swallowed (acid|pesticide|phenyl|kerosene|tablets)|pesticide", "poisoning or overdose"),
    (r"snake ?bite|bitten by (a )?snake", "snake bite"),
    (r"suicid|want to die|kill myself|end my life|self[- ]?harm|hurt myself", "thoughts of self-harm"),
    (r"severe burn|burn(s|ed)? (over|on) (a )?large", "severe burns"),
    (r"head injury.*(vomit|drows|unconscious|confus)|(vomit|drows|confus).*head injury", "serious head injury"),
    (r"baby (is )?(not breathing|blue)|newborn.*(blue|not feeding|not breathing)", "newborn in danger"),
    (r"stiff neck.*fever|fever.*stiff neck", "fever with stiff neck"),
]

_PREGNANCY_EMERGENCY = r"bleeding|severe (abdominal |stomach )?pain|no (baby )?movement|not moving|leaking (fluid|water)|fits|blurred vision|severe headache"

_URGENT: list[tuple[str, str]] = [
    (r"high fever|10[345] ?(f|degrees)|fever (for|since) (more than )?(3|three|4|four|5|five|6|six|7|seven|a week)|fever.*(3|4|5|6|7) days", "high or long-lasting fever"),
    (r"persistent vomiting|vomiting (for|since)|can'?t keep (food|water|anything) down", "persistent vomiting"),
    (r"blood in (the )?(stool|urine|motion)|black stool", "blood in stool or urine"),
    (r"dehydrat|not passing urine|very little urine", "possible dehydration"),
    (r"severe (pain|headache)|worst headache", "severe pain"),
    (r"fracture|broken bone|deep cut|wound.*(pus|swelling|red)", "injury needing care"),
    (r"diarrh(o)?ea.*(days|since|blood|dehydrat)|loose motions.*(days|since)", "ongoing diarrhoea"),
]

_SPECIALTY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pediatrics": ("child", "baby", "infant", "toddler", "newborn", "kid", "my son", "my daughter"),
    "gynecology": ("pregnan", "period", "menstru", "pcos", "white discharge", "antenatal", "delivery", "breast", "uterus", "gynae", "gynec"),
    "dermatology": ("skin", "rash", "itch", "acne", "pimple", "hair fall", "eczema", "fungal", "psoriasis", "allergy on"),
    "cardiology": ("heart", "palpitation", "blood pressure", "hypertension", "chest"),
    "orthopedics": ("bone", "joint", "knee", "back pain", "fracture", "shoulder", "neck pain", "sprain", "arthritis"),
    "ophthalmology": ("eye", "vision", "cataract", "blurred"),
    "ent": ("ear", "nose", "throat", "sinus", "tonsil", "hearing", "voice"),
    "dentistry": ("tooth", "teeth", "dental", "gum", "toothache", "cavity"),
    "psychiatry": ("anxiety", "depress", "stress", "panic", "mental", "addiction", "can't sleep", "insomnia", "mood"),
}


def _matches(patterns: list[tuple[str, str]], text: str) -> list[str]:
    return [label for pat, label in patterns if re.search(pat, text)]


def suggest_specialty(text: str, age: int | None = None) -> str:
    text = text.lower()
    scores = {sp: sum(1 for kw in kws if kw in text) for sp, kws in _SPECIALTY_KEYWORDS.items()}
    if age is not None and age < 14:
        scores["pediatrics"] += 2
    best, score = max(scores.items(), key=lambda kv: kv[1])
    return best if score > 0 else "general medicine"


def assess(symptoms: str, age: int | None = None, pregnant: bool | None = None) -> dict[str, Any]:
    text = " ".join(symptoms.lower().split())
    emergency = _matches(_EMERGENCY, text)
    if pregnant and re.search(_PREGNANCY_EMERGENCY, text):
        emergency.append("warning sign in pregnancy")
    urgent = _matches(_URGENT, text)
    if age is not None and age < 1 and "fever" in text:
        urgent.append("fever in an infant")
    if pregnant and re.search(r"headache|swelling|swollen|reduced movement|less movement", text):
        urgent.append("symptom that needs a check-up in pregnancy")

    specialty = suggest_specialty(text, age)
    base = {
        "suggested_specialty": specialty,
        "emergency_numbers": EMERGENCY_NUMBERS,
        "disclaimer": "General guidance only, not a diagnosis. A doctor must examine the patient.",
    }
    if emergency:
        return {
            **base, "urgency": "emergency", "matched_signs": emergency,
            "advice": "This may be an emergency. Call 112 (or 108 for an ambulance) right now or go to the nearest hospital. Do not wait for an appointment.",
        }
    if urgent:
        return {
            **base, "urgency": "urgent", "matched_signs": urgent,
            "advice": "See a doctor today: visit the nearest clinic, health centre or hospital, or use a teleconsultation. Go to emergency care if it gets worse.",
        }
    return {
        **base, "urgency": "routine", "matched_signs": [],
        "advice": "A routine appointment is suitable. Rest, drink fluids, and see a doctor sooner if symptoms get worse or new warning signs appear.",
    }
