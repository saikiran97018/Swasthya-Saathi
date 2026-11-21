"""Understand a spoken "yes" or "no" in the app's languages (used to confirm actions during a live voice call)."""
from __future__ import annotations

import re
from typing import Literal

Verdict = Literal["yes", "no", "other"]

_WORD = re.compile(r"[\wऀ-෿]+")  # \w alone drops Indic vowel signs, which would split words apart

YES = {
    # English / romanised
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "correct", "right", "proceed", "agreed", "definitely",
    "haan", "han", "ha", "haa", "ji", "theek", "thik", "sahi", "avunu", "avnu", "aavunu", "sare", "sari", "sheri", "houdu", "hoon", "aam", "aama", "athe", "ho", "hoy", "aagali",
    # native scripts
    "हाँ", "हां", "जी", "ठीक", "सही", "हो", "होय", "అవును", "సరే", "ஆமாம்", "ஆம்", "சரி", "ಹೌದು", "ಸರಿ", "അതെ", "ശരി", "হ্যাঁ", "হ্যা", "ঠিক", "હા", "ਹਾਂ", "ਹਾਂਜੀ", "ਠੀਕ", "ହଁ",
}
NO = {
    "no", "nope", "nah", "cancel", "stop", "dont", "don", "not", "never", "wrong", "nahi", "nahin", "mat", "kadu", "vaddu", "vadhu", "illa", "illai", "beda", "venda", "vendam", "alla",
    "नहीं", "नही", "मत", "नको", "नाही", "కాదు", "వద్దు", "வேண்டாம்", "இல்லை", "ಇಲ್ಲ", "ಬೇಡ", "ಅಲ್ಲ", "ഇല്ല", "വേണ്ട", "না", "নয়", "না।", "ના", "નહીં", "ਨਹੀਂ", "ਨਾ", "ନା",
}
YES_PHRASES = ("go ahead", "do it", "book it", "kar do", "kar dijiye", "chalega", "of course")
NO_PHRASES = ("do not", "don't", "not now", "rehne do", "chhod do")


def quick_yes_no(text: str) -> Verdict:
    """Fast, local judgement. 'other' when it is unclear or the person said both (then ask an LLM or ask again)."""
    low = (text or "").lower().replace("’", "'")
    words = set(_WORD.findall(low))
    no = bool(words & NO) or any(p in low for p in NO_PHRASES)
    # a yes-PHRASE ("book it") means nothing next to a no ("don't book it"); a plain yes WORD next to a no stays unclear ("yes but no")
    yes = bool(words & YES) or (not no and any(p in low for p in YES_PHRASES))
    if yes and not no:
        return "yes"
    if no and not yes:
        return "no"
    return "other"
