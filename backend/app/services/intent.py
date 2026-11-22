"""Intent classification: what does the person want right now?

Two layers. Fast rules (English, Hinglish and the main Indian-language emergency words) answer most messages at no cost. When the
text is in another script or the rules cannot tell, ONE short model call classifies it and also returns an English search query for
the knowledge base, so retrieval does not need a second call. The result:
  * puts a one-line hint in front of the model ("call assess_urgency first"), which keeps it on the right path,
  * flags a possible emergency in code, independent of what the model decides,
  * skips retrieval for messages that need none (booking, thanks, "open settings").
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from app.core.config import Settings
from app.services.llm_service import LLMService
from app.utils.transcript import collapse_repeats  # noqa: F401  (re-exported for callers cleaning text first)
from app.utils.yesno import quick_yes_no

log = logging.getLogger("app.intent")

INTENTS = (
    "emergency", "symptoms", "find_care", "find_pharmacy", "medicine_reminder", "book", "cancel", "reschedule", "my_appointments", "feedback",
    "scheme_info", "health_info", "app_control", "confirm_yes", "confirm_no", "smalltalk", "other",
)

_EMERGENCY = re.compile(
    r"chest pain|heart attack|can'?t breathe|cannot breathe|unable to breathe|trouble breathing|difficulty (in )?breathing|not breathing|struggling to breathe"
    r"|unconscious|not responding|passed out|fainted|seizure|convulsion|\bfits\b|having a fit|stroke|face (is )?drooping|slurred speech"
    r"|severe bleeding|bleeding (heavily|a lot|badly)|won'?t stop bleeding|poison|overdose|swallowed (a |some )?\w+|snake ?bite|bitten by (a )?snake"
    r"|suicid|kill myself|end my life|want to die|choking|labou?r pain|water (has )?broke"
    r"|सीने में दर्द|साँस नहीं|सांस नहीं|सांस लेने में|बेहोश|दौरा|ज़हर|जहर|साँप ने काटा|सांप ने काटा|आत्महत्या|खून बह|हार्ट अटैक|दिल का दौरा"
    r"|ఛాతీ నొప్పి|శ్వాస తీసుకోలేక|స్పృహ తప్పి|పాము కాటు|విషం|ఆత్మహత్య"
    r"|நெஞ்சு வலி|மூச்சு விட முடியவில்லை|மயக்கம்|பாம்பு கடி|விஷம்|தற்கொலை",
    re.IGNORECASE,
)
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("cancel", re.compile(r"\bcancel\b|रद्द|cancel kar|రద్దు|ரத்து", re.I)),
    ("reschedule", re.compile(r"re-?schedule|change (my |the )?(appointment|time|date|slot)|postpone|shift (my |the )?appointment|दूसरे दिन|बदल", re.I)),
    ("my_appointments", re.compile(r"my (appointments?|bookings?|visits?)|upcoming (appointment|visit)|when is my|मेरी अपॉइंटमेंट|నా అపాయింట్‌మెంట్|எனது சந்திப்பு", re.I)),
    ("book", re.compile(r"\bbook\b|appointment|schedule (a|an)\b|fix an appointment|अपॉइंटमेंट|बुक|బుక్|అపాయింట్|புக்|முன்பதிவு", re.I)),
    ("medicine_reminder", re.compile(r"remind(er)? (me )?(to take|for)|medicine reminder|tablet reminder|pill reminder|take my (tablet|medicine|pills?)|दवा.{0,12}याद|दवाई.{0,12}याद|మందు.{0,15}గుర్తు|మాత్ర.{0,15}గుర్తు|மருந்து.{0,15}நினைவூட்ட", re.I)),
    ("find_pharmacy", re.compile(r"pharmac|chemist|medical (shop|store)|medicine (shop|store)|medicals? near|मेडिकल (स्टोर|शॉप)|दवा की दुकान|दवाई की दुकान|फार्मेसी|మెడికల్ షాప్|మందుల దుకాణం|மருந்தகம்|மருந்துக் கடை", re.I)),
    ("symptoms", re.compile(
        r"fever|temperature|\bpain\b|ache\b|cough|\bcold\b|headache|vomit|nausea|rash|diarrh|loose motion|swelling|dizz|weakness|itch|burning|sore throat|infection|"
        r"bukhar|बुखार|दर्द|खांसी|खाँसी|उल्टी|दस्त|चक्कर|జ్వరం|నొప్పి|దగ్గు|వాంతి|காய்ச்சல்|வலி|இருமல்|வாந்தி", re.I)),
    ("find_care", re.compile(r"near me|nearby|nearest|\bclinic\b|hospital|doctor|dentist|specialist|physician|डॉक्टर|अस्पताल|క్లినిక్|ఆసుపత్రి|డాక్టర్|மருத்துவர்|மருத்துவமனை", re.I)),
    ("scheme_info", re.compile(r"ayushman|abha|pm-?jay|scheme|insurance|e-?sanjeevani|jan aushadhi|yojana|health id|आयुष्मान|योजना|ఆయుష్మాన్|పథకం|ஆயுஷ்மான்|திட்டம்", re.I)),
    ("health_info", re.compile(r"what is|how (to|do|can)|why does|vaccin|diabet|blood pressure|\bbp\b|pregnan|\btb\b|tubercul|diet|first aid|sugar|टीका|मधुमेह|गर्भ|టీకా|మధుమేహం|గర్భ|தடுப்பூசி|நீரிழிவு|கர்ப்ப", re.I)),
    ("feedback", re.compile(r"feedback|\brating\b|\brate\b|review the (visit|doctor)|फीडबैक|ఫీడ్‌బ్యాక్", re.I)),
    ("app_control", re.compile(r"\b(open|show|go to|take me to|switch to|turn on|turn off)\b.*\b(screen|page|settings|sos|care plan|history|dark|light|mode|family)\b|dark mode|light mode", re.I)),
    ("smalltalk", re.compile(r"^\W*(hi|hello|hey|thanks?|thank you|bye|good (morning|evening|night|afternoon)|how are you|namaste|namaskar|ok(ay)?|नमस्ते|धन्यवाद|శుభోదయం|నమస్కారం|வணக்கம்|நன்றி)\b", re.I)),
]

_LATIN = re.compile(r"[A-Za-z]")
RETRIEVAL_INTENTS = {"emergency", "symptoms", "scheme_info", "health_info", "other"}  # the others never need the knowledge base

HINTS = {
    "emergency": "POSSIBLE EMERGENCY. First make sure whether it is happening now. If it is, tell them to call 112 (108 for an ambulance) at once, in your first sentence, and do NOT book or ask other questions.",
    "symptoms": "They describe symptoms: call assess_urgency first.",
    "find_pharmacy": "They want a medicine shop: you need their city, then call find_medical_shops.",
    "medicine_reminder": "They want a medicine reminder: ask what (their own words) and at what times, then call medicine_reminder and read it back. Never suggest a medicine.",
    "find_care": "They want a provider: you need their city, then call find_healthcare_providers.",
    "book": "They want an appointment: follow the booking steps; book_appointment needs their confirmation.",
    "cancel": "They want to cancel: call list_appointments to find the reference first.",
    "reschedule": "They want to change a booking: call list_appointments, then check_availability.",
    "my_appointments": "They ask about their bookings: use the upcoming visits above or call list_appointments.",
    "scheme_info": "A scheme or insurance question: answer from the reference notes or search_knowledge_base.",
    "health_info": "A health information question: answer from the reference notes; do not diagnose.",
    "app_control": "They want the app to do something: call control_app, then say in one short sentence what you did.",
    "feedback": "They are giving feedback: collect a 1-5 rating and a comment, then record_feedback.",
    "smalltalk": "Small talk: reply briefly and warmly; no tools.",
    "confirm_yes": "They are answering your last question with yes.",
    "confirm_no": "They are answering your last question with no.",
}

_PROMPT = (
    "Classify the user's message (any Indian language, possibly mixed). Reply with JSON only: "
    '{"intent": "<one of: ' + ", ".join(INTENTS) + '>", "query": "<short English search query if it is about a health topic, scheme or first aid, else empty>"}. '
    "emergency = a medical emergency happening now or thoughts of self-harm. symptoms = describing how they feel. find_care = looking for a doctor or clinic. "
    "book/cancel/reschedule/my_appointments = about appointments. scheme_info = government schemes and insurance. health_info = general health questions. "
    "app_control = asks the app to open a screen or change a setting. smalltalk = greeting or thanks. other = anything else."
)


@dataclass(frozen=True)
class Intent:
    label: str
    query: str | None = None  # English knowledge-base query; "" = the classifier saw no health topic; None = unknown
    source: str = "rules"  # rules | llm

    @property
    def emergency(self) -> bool:
        return self.label == "emergency"

    @property
    def wants_notes(self) -> bool:
        return self.label in RETRIEVAL_INTENTS

    @property
    def hint(self) -> str:
        return HINTS.get(self.label, "")


def mostly_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return not letters or sum(1 for c in letters if _LATIN.match(c)) / len(letters) > 0.6


def classify_rules(text: str) -> str:
    t = " ".join((text or "").split())
    if not t:
        return "other"
    if _EMERGENCY.search(t):
        return "emergency"
    found = next((label for label, pattern in _RULES if pattern.search(t)), None)
    if len(t.split()) <= 3 and found in (None, "smalltalk"):  # "cancel my appointment" is a request, not a "no"
        verdict = quick_yes_no(t)
        if verdict in ("yes", "no"):
            return f"confirm_{verdict}"
    return found or "other"


def parse_llm_answer(raw: str | None) -> Intent | None:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    label = str(data.get("intent", "")).strip().lower()
    if label not in INTENTS:
        return None
    return Intent(label, " ".join(str(data.get("query") or "").split())[:120], "llm")


class IntentService:
    def __init__(self, settings: Settings, llm: LLMService):
        self.s, self.llm = settings, llm

    async def classify(self, text: str) -> Intent:
        label = classify_rules(text)
        latin = mostly_latin(text)
        if label in ("emergency", "confirm_yes", "confirm_no") or (latin and label != "other"):
            return Intent(label, text if latin else None, "rules")
        words = len(text.split())
        if not self.s.intent_llm_enabled or not self.llm.configured or (latin and words < 4):
            return Intent(label, text if latin else None, "rules")
        try:
            raw = await asyncio.wait_for(
                self.llm.complete([{"role": "system", "content": _PROMPT}, {"role": "user", "content": text[:400]}], temperature=0, max_tokens=80),
                timeout=self.s.intent_timeout_seconds,
            )
        except Exception as exc:
            log.info("intent model call skipped: %s", type(exc).__name__)
            return Intent(label, text if latin else None, "rules")
        parsed = parse_llm_answer(raw)
        if parsed is None:
            return Intent(label, text if latin else None, "rules")
        if parsed.label == "other" and label != "other":
            return Intent(label, parsed.query, "rules")  # the rules saw something concrete: trust them over a vague "other"
        return parsed
