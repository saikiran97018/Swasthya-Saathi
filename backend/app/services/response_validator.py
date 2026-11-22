"""Response validation: the last check before a reply is spoken or shown (relevance, factual grounding, safety).

Pipeline:  speech -> STT -> transcript check -> intent + context -> LLM + RAG + tools -> **this check** -> TTS

Everything here is deterministic and cheap. A reply is checked against what the assistant actually had in front of it this turn
(its instructions, the knowledge-base notes, tool results and what the person said):
  * facts: phone numbers, amounts and appointment references that appear nowhere in that material are invented,
  * safety: medicine doses or names, "you have <disease>" diagnoses, an emergency answered without 112,
  * relevance: empty replies, the wrong language, leaked instructions or tool names,
  * speech: markdown, links and emoji are removed for voice, and long replies are cut at a sentence.
Fixable problems are repaired in place. Real problems get ONE rewrite from the model; if that fails too, a safe localized
fallback is used instead. The person never hears an unchecked invented fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_LATIN = re.compile(r"[A-Za-z]")

KNOWN_HELPLINES = {"112", "108", "102", "104", "100", "101", "181", "1098", "14416", "14567", "1091", "1930", "1075", "14555"}

EMERGENCY_LINE = {
    "en": "If this is happening now, call 112 immediately (108 for an ambulance).",
    "hi": "अगर यह अभी हो रहा है, तो तुरंत 112 पर कॉल करें (एम्बुलेंस के लिए 108)।",
    "te": "ఇది ఇప్పుడే జరుగుతుంటే, వెంటనే 112కు కాల్ చేయండి (అంబులెన్స్ కోసం 108).",
    "ta": "இது இப்போது நடந்தால், உடனே 112-ஐ அழைக்கவும் (ஆம்புலன்சுக்கு 108).",
    "kn": "ಇದು ಈಗ ನಡೆಯುತ್ತಿದ್ದರೆ, ತಕ್ಷಣ 112ಕ್ಕೆ ಕರೆ ಮಾಡಿ (ಆಂಬುಲೆನ್ಸ್‌ಗೆ 108).",
    "ml": "ഇത് ഇപ്പോൾ സംഭവിക്കുന്നുണ്ടെങ്കിൽ ഉടൻ 112-ൽ വിളിക്കുക (ആംബുലൻസിന് 108).",
    "bn": "এটি এখন ঘটলে সঙ্গে সঙ্গে 112-এ কল করুন (অ্যাম্বুলেন্সের জন্য 108)।",
    "mr": "हे आत्ता घडत असेल तर लगेच 112 वर कॉल करा (रुग्णवाहिकेसाठी 108).",
    "gu": "જો આ હમણાં થઈ રહ્યું હોય, તો તરત 112 પર કૉલ કરો (એમ્બ્યુલન્સ માટે 108).",
    "pa": "ਜੇ ਇਹ ਹੁਣ ਹੋ ਰਿਹਾ ਹੈ, ਤਾਂ ਤੁਰੰਤ 112 'ਤੇ ਕਾਲ ਕਰੋ (ਐਂਬੂਲੈਂਸ ਲਈ 108)।",
}
SAFE_FALLBACK = {
    "en": "I am not fully sure about that, so I do not want to guess. Please ask a doctor, or call 104 for health advice.",
    "hi": "मुझे पक्का नहीं पता, इसलिए अंदाज़ा लगाना ठीक नहीं। कृपया डॉक्टर से पूछें, या सलाह के लिए 104 पर कॉल करें।",
    "te": "దీని గురించి నాకు ఖచ్చితంగా తెలియదు, అందుకే ఊహించి చెప్పను. దయచేసి డాక్టర్‌ను అడగండి, లేదా ఆరోగ్య సలహా కోసం 104కు కాల్ చేయండి.",
    "ta": "இதைப் பற்றி எனக்கு உறுதியாகத் தெரியவில்லை, அதனால் ஊகித்துச் சொல்ல மாட்டேன். தயவுசெய்து மருத்துவரிடம் கேளுங்கள், அல்லது சுகாதார ஆலோசனைக்கு 104-ஐ அழைக்கவும்.",
    "kn": "ಇದರ ಬಗ್ಗೆ ನನಗೆ ಖಚಿತವಿಲ್ಲ, ಆದ್ದರಿಂದ ಊಹಿಸಿ ಹೇಳುವುದಿಲ್ಲ. ದಯವಿಟ್ಟು ವೈದ್ಯರನ್ನು ಕೇಳಿ, ಅಥವಾ ಆರೋಗ್ಯ ಸಲಹೆಗಾಗಿ 104ಗೆ ಕರೆ ಮಾಡಿ.",
    "ml": "ഇതിനെക്കുറിച്ച് എനിക്ക് ഉറപ്പില്ല, അതിനാൽ ഊഹിച്ച് പറയുന്നില്ല. ദയവായി ഡോക്ടറോട് ചോദിക്കുക, അല്ലെങ്കിൽ ആരോഗ്യ ഉപദേശത്തിന് 104-ൽ വിളിക്കുക.",
    "bn": "এ বিষয়ে আমি নিশ্চিত নই, তাই অনুমান করে বলব না। অনুগ্রহ করে ডাক্তারকে জিজ্ঞাসা করুন, অথবা স্বাস্থ্য পরামর্শের জন্য 104-এ কল করুন।",
    "mr": "याबद्दल मला खात्री नाही, म्हणून अंदाजाने सांगणार नाही. कृपया डॉक्टरांना विचारा, किंवा आरोग्य सल्ल्यासाठी 104 वर कॉल करा.",
    "gu": "આ વિશે મને ખાતરી નથી, એટલે અંદાજે નહીં કહું. કૃપા કરીને ડૉક્ટરને પૂછો, અથવા આરોગ્ય સલાહ માટે 104 પર કૉલ કરો.",
    "pa": "ਇਸ ਬਾਰੇ ਮੈਨੂੰ ਪੱਕਾ ਪਤਾ ਨਹੀਂ, ਇਸ ਲਈ ਅੰਦਾਜ਼ਾ ਨਹੀਂ ਲਾਵਾਂਗਾ। ਕਿਰਪਾ ਕਰਕੇ ਡਾਕਟਰ ਨੂੰ ਪੁੱਛੋ, ਜਾਂ ਸਿਹਤ ਸਲਾਹ ਲਈ 104 'ਤੇ ਕਾਲ ਕਰੋ।",
}

_TOOL_NAMES = r"assess_urgency|find_healthcare_providers|check_availability|book_appointment|cancel_appointment|reschedule_appointment|list_appointments|search_knowledge_base|lookup_service_directory|control_app|form_assistant|submit_service_request|schedule_follow_up|record_feedback|set_language|web_search"
_LEAK = re.compile(rf"system prompt|reference notes|conversation memory|my instructions|tool_call|\b(?:{_TOOL_NAMES})\b", re.I)
_DOSE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|ml|gm|grams?)\b|\b(?:\d+|one|two|three|four|five|six|half)\s(?:tablets?|capsules?|pills?|drops|teaspoons?|spoons?)\b", re.I)
_DRUGS = ("paracetamol", "acetaminophen", "ibuprofen", "aspirin", "diclofenac", "amoxicillin", "azithromycin", "ciprofloxacin", "metformin", "insulin", "dolo", "crocin", "combiflam", "cetirizine", "omeprazole", "pantoprazole")
_DISEASES = r"dengue|malaria|typhoid|diabetes|tuberculosis|tb|cancer|covid|pneumonia|heart attack|stroke|jaundice|hepatitis|hiv|asthma|appendicitis|cholera"
_DIAGNOSIS = re.compile(rf"\byou (?:definitely |certainly |surely )?(?:have|has|are suffering from|are having) (?:a |an )?(?:{_DISEASES})\b|\bit(?: is|'s) (?:definitely |certainly |surely )?(?:{_DISEASES})\b", re.I)
_PHONE_GROUPS = re.compile(r"\d{2,5}(?:[\s-]\d{2,5})+")
_DIGITS = re.compile(r"\d+")
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s?(\d[\d,]*)", re.I)
_REF = re.compile(r"\bAP-[A-Z0-9]{4,6}\b", re.I)
_URL = re.compile(r"https?://\S+|www\.\S+")
_MARKDOWN = re.compile(r"[*_#`>]+")
_BULLET = re.compile(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")
VOICE_MAX_CHARS = 700
VOICE_CUT_AT = 600
HARD = {"empty", "leak", "dose", "drug", "diagnosis", "ungrounded_number", "ungrounded_amount", "ungrounded_ref", "wrong_language"}


@dataclass
class Verdict:
    text: str  # the reply to use (repaired)
    problems: list[str] = field(default_factory=list)  # real problems: the reply needs rewriting
    repairs: list[str] = field(default_factory=list)  # things fixed in place

    @property
    def ok(self) -> bool:
        return not self.problems


def _digits_only(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def _phone_key(digits: str) -> str:
    return digits[-10:] if len(digits) >= 10 else digits


def _grounded_numbers(grounding: str) -> tuple[set[str], str]:
    """Every digit run in the source material (and the same with spaces and hyphens removed inside phone-like groups)."""
    keys = {m for m in _DIGITS.findall(grounding)}
    for m in _PHONE_GROUPS.finditer(grounding):
        keys.add(_digits_only(m.group(0)))
    return {_phone_key(k) for k in keys if len(k) >= 8} | {k for k in keys if k.isdigit()}, grounding


# The writing system each language is spoken in, as Unicode ranges. A reply in another system than the person's language is a wrong answer.
_SCRIPTS = {"latin": ((0x41, 0x5A), (0x61, 0x7A)), "devanagari": ((0x900, 0x97F),), "bengali": ((0x980, 0x9FF),), "gurmukhi": ((0xA00, 0xA7F),), "gujarati": ((0xA80, 0xAFF),),
            "odia": ((0xB00, 0xB7F),), "tamil": ((0xB80, 0xBFF),), "telugu": ((0xC00, 0xC7F),), "kannada": ((0xC80, 0xCFF),), "malayalam": ((0xD00, 0xD7F),), "arabic": ((0x600, 0x6FF),)}
_LANG_SCRIPT = {"en": "latin", "hi": "devanagari", "mr": "devanagari", "sa": "devanagari", "bn": "bengali", "as": "bengali", "pa": "gurmukhi", "gu": "gujarati", "or": "odia",
                "ta": "tamil", "te": "telugu", "kn": "kannada", "ml": "malayalam", "ur": "arabic"}


def script_shares(text: str) -> dict[str, float]:
    letters = [ord(c) for c in text if c.isalpha()]
    if not letters:
        return {}
    counts = {name: sum(1 for o in letters if any(lo <= o <= hi for lo, hi in ranges)) for name, ranges in _SCRIPTS.items()}
    return {name: n / len(letters) for name, n in counts.items() if n}


def garbled_words(text: str) -> list[str]:
    """Words that mix two Indian writing systems inside ONE word (a model glitch such as Devanagari letters with a Telugu letter)."""
    indic = [(name, ranges) for name, ranges in _SCRIPTS.items() if name not in ("latin", "arabic")]
    bad = []
    for word in text.split():
        used = {name for name, ranges in indic if any(any(lo <= ord(c) <= hi for lo, hi in ranges) for c in word if ord(c) >= 0x900)}  # marks (such as a virama) count too
        if len(used) > 1:
            bad.append(word)
    return bad


def wrong_script(text: str, language: str) -> bool:
    """True when a reply of any real length is mostly in another writing system than `language` (code-mixed replies pass)."""
    expected = _LANG_SCRIPT.get(language)
    shares = script_shares(text)
    if expected is None or sum(1 for c in text if c.isalpha()) < 25:
        return False
    share = shares.get(expected, 0.0)
    return (1 - share) > 0.15 if expected == "latin" else share < 0.2


def speakable(text: str) -> str:
    """Strip what a voice cannot say: links, markdown, bullets, emoji."""
    t = _URL.sub("", text)
    t = _BULLET.sub("", t)
    t = _MARKDOWN.sub("", t)
    t = _EMOJI.sub("", t)
    return " ".join(t.split())


def _trim(text: str) -> str:
    cut = max(text.rfind(p, 0, VOICE_CUT_AT) for p in (". ", "। ", "? ", "! "))
    return text[: cut + 1].strip() if cut > 120 else text[:VOICE_CUT_AT].rsplit(" ", 1)[0] + "."


def validate_response(text: str, *, language: str, voice: bool, intent: str, grounding: str, allow_dose_words: bool = False) -> Verdict:
    t = " ".join((text or "").split()) if voice else (text or "").strip()
    v = Verdict(text=t)
    if len(re.sub(r"\W", "", t)) < 2:
        v.problems.append("empty")
        return v

    if voice:
        cleaned = speakable(t)
        if cleaned != t:
            v.repairs.append("speakable")
            t = cleaned
        if len(t) > VOICE_MAX_CHARS:
            t = _trim(t)
            v.repairs.append("trimmed")

    low_ground = grounding.lower()
    if _LEAK.search(t):
        v.problems.append("leak")
    if _DIAGNOSIS.search(t):
        v.problems.append("diagnosis")
    if not allow_dose_words:
        if _DOSE.search(t) and not any(m.group(0).lower() in low_ground for m in _DOSE.finditer(t)):
            v.problems.append("dose")
        if any(d in t.lower() and d not in low_ground for d in _DRUGS):
            v.problems.append("drug")  # a medicine name that no verified note mentions

    known, _ = _grounded_numbers(grounding)
    invented = False
    for m in _PHONE_GROUPS.finditer(t):  # numbers read out in groups ("98765 43210")
        d = _digits_only(m.group(0))
        if len(d) >= 8 and _phone_key(d) not in known:
            invented = True
    for d in _DIGITS.findall(t):  # one run of digits: a helpline or a phone number
        if len(d) >= 8 and _phone_key(d) not in known:
            invented = True
        elif len(d) == 5 and d.startswith("14") and d not in KNOWN_HELPLINES and d not in known:
            invented = True  # a made-up 14xxx national helpline (short numbers such as minutes, rupees or years are left alone)
    if invented:
        v.problems.append("ungrounded_number")
    for m in _AMOUNT.finditer(t):
        value = m.group(1).replace(",", "")
        if value not in known:
            v.problems.append("ungrounded_amount")
            break
    if any(ref.group(0).upper() not in grounding.upper() for ref in _REF.finditer(t)):
        v.problems.append("ungrounded_ref")

    if wrong_script(t, language) or garbled_words(t):
        v.problems.append("wrong_language")

    if intent == "emergency" and not re.search(r"\b(?:112|108)\b|112|108", t):
        t = f"{EMERGENCY_LINE.get(language, EMERGENCY_LINE['en'])} {t}"
        v.repairs.append("emergency_line")
    v.text = t
    return v


def fallback_text(language: str, intent: str) -> str:
    base = SAFE_FALLBACK.get(language, SAFE_FALLBACK["en"])
    return f"{EMERGENCY_LINE.get(language, EMERGENCY_LINE['en'])} {base}" if intent == "emergency" else base


REWRITE_NOTE = (
    "Your last draft was rejected for: {problems}. Write the reply again, in {lang}, using only facts from your instructions, the reference notes and tool results. "
    "Never invent phone numbers, fees or references; no medicine names or doses; no diagnosis. If you do not know, say so briefly and suggest a doctor or 104. "
    "Do not mention this note."
)
