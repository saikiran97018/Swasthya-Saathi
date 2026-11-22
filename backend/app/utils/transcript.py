"""Checks a speech-to-text transcript before the assistant acts on it.

Speech recognisers invent text for silence and background noise ("Thanks for watching", "[music]"), loop on a phrase, or return
only a filler sound. Acting on that would book, cancel or advise on something nobody said. A transcript that fails these checks is
never sent to the model: the person is simply asked to say it again. Real answers, including a bare "yes", "no" or "haan", pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SOUND_TAGS = re.compile(r"\[[^\]]{0,40}\]|\([^)]{0,40}\)|\*[^*]{0,40}\*|[♪♫♬]")
_FILLERS = {"hmm", "hm", "mm", "mmm", "uh", "um", "umm", "uhh", "ah", "aah", "oh", "er", "erm", "huh", "hmmm", "ahh", "ohh"}
# Phrases speech models are known to make up out of silence (caption and video outro boilerplate).
_HALLUCINATIONS = (
    "thanks for watching", "thank you for watching", "subtitles by", "subtitled by", "amara.org", "please subscribe", "like and subscribe",
    "transcribed by", "captions by", "see you in the next video", "subscribe to the channel", "सब्सक्राइब",
)
MAX_REPEAT = 3  # a phrase repeated more times than this in a row is a recogniser loop, not speech


@dataclass(frozen=True)
class TranscriptCheck:
    ok: bool
    text: str  # cleaned text (what to use when ok)
    reason: str | None = None  # empty | noise | invented


def collapse_repeats(text: str) -> str:
    """'I have fever I have fever I have fever I have fever' -> 'I have fever'. Up to MAX_REPEAT repeats are kept as emphasis."""
    words = text.split()
    for n in range(1, 7):
        i = 0
        while i + n <= len(words):
            run = 1
            while words[i : i + n] == words[i + run * n : i + (run + 1) * n] and i + (run + 1) * n <= len(words):
                run += 1
            if run > MAX_REPEAT:
                del words[i + n : i + run * n]
            i += 1
    return " ".join(words)


def _letters(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace())


def check_transcript(text: str | None) -> TranscriptCheck:
    cleaned = " ".join(_SOUND_TAGS.sub(" ", text or "").split())
    if not any(c.isalnum() for c in cleaned):
        return TranscriptCheck(False, "", "empty")
    words = _letters(cleaned).split()
    if all(w in _FILLERS for w in words):
        return TranscriptCheck(False, "", "noise")
    if len(words) == 1 and len(words[0]) == 1 and not words[0].isdigit():
        return TranscriptCheck(False, "", "noise")  # one stray letter
    flat = " ".join(words)
    if len(words) <= 14 and any(h in flat or h in cleaned.lower() for h in _HALLUCINATIONS):
        return TranscriptCheck(False, "", "invented")
    return TranscriptCheck(True, collapse_repeats(cleaned))
