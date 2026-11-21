"""Supported languages, script-based language detection and text clean-up for speech."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    asr: bool = True
    tts: bool = True


# Codes follow Bhashini/ULCA (ISO 639-1/-2). Availability flags reflect typical public models;
# the live Bhashini pipeline lookup is the source of truth and errors are surfaced to the user.
LANGUAGES: dict[str, Language] = {
    l.code: l
    for l in [
        Language("en", "English", "English"),
        Language("hi", "Hindi", "हिन्दी"),
        Language("te", "Telugu", "తెలుగు"),
        Language("ta", "Tamil", "தமிழ்"),
        Language("kn", "Kannada", "ಕನ್ನಡ"),
        Language("ml", "Malayalam", "മലയാളം"),
        Language("bn", "Bengali", "বাংলা"),
        Language("mr", "Marathi", "मराठी"),
        Language("gu", "Gujarati", "ગુજરાતી"),
        Language("pa", "Punjabi", "ਪੰਜਾਬੀ"),
        Language("or", "Odia", "ଓଡ଼ିଆ"),
        Language("as", "Assamese", "অসমীয়া"),
        Language("ur", "Urdu", "اردو", tts=False),
        Language("sa", "Sanskrit", "संस्कृतम्", tts=False),
    ]
}

DEFAULT_LANGUAGE = "en"

# Unicode block -> language code (best single guess for the script).
_SCRIPT_RANGES: list[tuple[str, int, int]] = [
    ("hi", 0x0900, 0x097F),  # Devanagari (Hindi/Marathi/Sanskrit share it; Hindi is the default guess)
    ("bn", 0x0980, 0x09FF),  # Bengali (also Assamese)
    ("pa", 0x0A00, 0x0A7F),  # Gurmukhi
    ("gu", 0x0A80, 0x0AFF),
    ("or", 0x0B00, 0x0B7F),
    ("ta", 0x0B80, 0x0BFF),
    ("te", 0x0C00, 0x0C7F),
    ("kn", 0x0C80, 0x0CFF),
    ("ml", 0x0D00, 0x0D7F),
    ("ur", 0x0600, 0x06FF),  # Arabic script
]


# Languages that share one script: detecting the script cannot tell them apart, so never "switch" within a family.
_SCRIPT_FAMILIES = [{"hi", "mr", "sa"}, {"bn", "as"}]


def same_script_family(a: str, b: str) -> bool:
    return a == b or any(a in fam and b in fam for fam in _SCRIPT_FAMILIES)


def is_supported(code: str | None) -> bool:
    return bool(code) and code in LANGUAGES


def normalise_language(code: str | None, fallback: str = DEFAULT_LANGUAGE) -> str:
    """Return a supported language code, accepting things like 'hi-IN' or 'HI'."""
    if not code:
        return fallback
    base = code.strip().lower().replace("_", "-").split("-")[0]
    return base if base in LANGUAGES else fallback


def language_name(code: str) -> str:
    lang = LANGUAGES.get(code)
    return f"{lang.name} ({lang.native_name})" if lang and lang.code != "en" else "English"


def detect_script_language(text: str, min_ratio: float = 0.3) -> str | None:
    """Detect the language from the dominant non-Latin script.

    Returns None for Latin-script text (English, or romanised Hindi/Telugu 'Hinglish'-style
    input), because the script alone cannot tell those apart. Callers then keep the
    conversation's current language, which is exactly what we want for code-mixed text.
    """
    counts: dict[str, int] = {}
    letters = 0
    for ch in text:
        if not ch.isalpha():
            continue
        letters += 1
        cp = ord(ch)
        for code, lo, hi in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
    if not letters or not counts:
        return None
    best, n = max(counts.items(), key=lambda kv: kv[1])
    return best if n / letters >= min_ratio else None


_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), " "),  # fenced code
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),  # images
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links -> text
    (re.compile(r"https?://\S+"), " "),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),
    (re.compile(r"^\s*\d+[.)]\s+", re.M), ""),
    (re.compile(r"[*_~>|]+"), ""),
]


def strip_markdown_for_speech(text: str) -> str:
    """Remove markdown so the TTS engine doesn't read out symbols."""
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE_END = re.compile(r"(?<=[.!?।॥?])\s+")


def split_for_tts(text: str, max_chars: int = 280) -> list[str]:
    """Split text into sentence-sized chunks that fit a TTS request."""
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:  # very long run-on sentence: hard split on spaces
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks
