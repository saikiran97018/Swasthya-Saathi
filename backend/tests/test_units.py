"""Pure unit tests: language utils, audio helpers, forms, security helpers, rate limiter."""
import io
import wave

import pytest

from app.agents import forms, triage
from app.core.errors import BadRequest, PayloadTooLarge, UnsupportedMedia
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.database.repositories.knowledge import chunk_text, tokenize
from app.middleware.rate_limit import SlidingWindow
from app.utils import audio
from app.utils.language import (
    detect_script_language,
    normalise_language,
    same_script_family,
    split_for_tts,
    strip_markdown_for_speech,
)
from tests.fakes import make_wav


# ---------------------------------------------------------------- language
@pytest.mark.parametrize(
    "text,expected",
    [
        ("నమస్కారం ఎలా ఉన్నారు", "te"),
        ("வணக்கம் எப்படி இருக்கிறீர்கள்", "ta"),
        ("ನಮಸ್ಕಾರ ಹೇಗಿದ್ದೀರಿ", "kn"),
        ("നമസ്കാരം", "ml"),
        ("নমস্কার কেমন আছেন", "bn"),
        ("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "pa"),
        ("मुझे PM-KISAN के बारे में बताओ", "hi"),
        ("hello how are you", None),
        ("mujhe ration card chahiye", None),  # romanised Hindi: script can't tell, so keep current language
        ("", None),
        ("12345 !!!", None),
    ],
)
def test_detect_script_language(text, expected):
    assert detect_script_language(text) == expected


def test_code_mixed_text_uses_dominant_script():
    # Mostly Telugu with an English word -> Telugu
    assert detect_script_language("నాకు bank account కావాలి") == "te"


def test_normalise_language():
    assert normalise_language("hi-IN") == "hi"
    assert normalise_language("TE") == "te"
    assert normalise_language("xx") == "en"
    assert normalise_language(None, "ta") == "ta"


def test_script_families_prevent_marathi_hindi_flip():
    assert same_script_family("hi", "mr")
    assert same_script_family("bn", "as")
    assert not same_script_family("hi", "te")


def test_strip_markdown_for_speech():
    out = strip_markdown_for_speech("## Title\n- **Bold** item\n[link](https://x.y) and `code`\n```py\nprint(1)\n```")
    assert "#" not in out and "*" not in out and "http" not in out and "print" not in out
    assert "Bold item" in out and "link" in out


def test_split_for_tts_respects_limit_and_sentences():
    text = "First sentence. Second sentence! " + ("word " * 100) + "Last one."
    chunks = split_for_tts(text, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert chunks[0].startswith("First sentence.")
    assert " ".join(chunks).count("word") == 100


def test_split_handles_devanagari_danda():
    assert len(split_for_tts("नमस्ते। आप कैसे हैं। मैं ठीक हूँ।", max_chars=15)) >= 2


# ---------------------------------------------------------------- audio
def test_validate_upload_accepts_good_wav():
    info = audio.validate_upload(make_wav(1.0), max_bytes=10**6, max_seconds=30)
    assert info.sample_rate == 16000 and round(info.duration) == 1


def test_validate_upload_rejections():
    with pytest.raises(BadRequest):
        audio.validate_upload(b"", max_bytes=10**6, max_seconds=30)
    with pytest.raises(UnsupportedMedia):
        audio.validate_upload(b"not a wav file at all", max_bytes=10**6, max_seconds=30)
    with pytest.raises(PayloadTooLarge):
        audio.validate_upload(make_wav(1.0), max_bytes=100, max_seconds=30)
    with pytest.raises(PayloadTooLarge):
        audio.validate_upload(make_wav(3.0), max_bytes=10**6, max_seconds=2)
    with pytest.raises(UnsupportedMedia):
        audio.validate_upload(make_wav(1.0, channels=2), max_bytes=10**6, max_seconds=30)
    with pytest.raises(BadRequest):
        audio.validate_upload(make_wav(0.05), max_bytes=10**6, max_seconds=30)


def test_concat_wavs():
    joined = audio.concat_wavs([make_wav(0.5, 8000), make_wav(0.5, 8000)])
    with wave.open(io.BytesIO(joined)) as w:
        assert w.getnframes() == 8000


# ---------------------------------------------------------------- audio normalisation (providers send different WAV flavours)
def _wav(tag, channels, rate, bits, payload: bytes, extensible=False, declared_len=None) -> bytes:
    import struct

    if extensible:
        fmt = struct.pack("<HHIIHHHHI", 0xFFFE, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits, 22, bits, 0) + struct.pack("<H", tag) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    else:
        fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits)
    size = len(payload) if declared_len is None else declared_len
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", size) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _samples(wav_bytes: bytes):
    import struct

    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
        return w.getnchannels(), w.getframerate(), list(struct.unpack(f"<{len(raw) // 2}h", raw))


def test_float32_wav_becomes_pcm16_with_clipping():
    import struct

    floats = struct.pack("<5f", 0.5, -0.5, 1.5, -2.0, 0.0)
    ch, rate, s = _samples(audio.to_pcm16_wav(_wav(3, 1, 8000, 32, floats)))
    assert (ch, rate) == (1, 8000) and s == [16383, -16383, 32767, -32768, 0]  # out-of-range values clip, never wrap


def test_other_pcm_widths_and_float64():
    import struct

    assert _samples(audio.to_pcm16_wav(_wav(1, 1, 16000, 8, bytes([128, 255, 0]))))[2] == [0, 32512, -32768]
    assert _samples(audio.to_pcm16_wav(_wav(1, 1, 16000, 24, (0x7FFFFF).to_bytes(3, "little") + (-0x800000).to_bytes(3, "little", signed=True))))[2] == [32767, -32768]
    assert _samples(audio.to_pcm16_wav(_wav(1, 1, 16000, 32, struct.pack("<2i", 2**30, -(2**30)))))[2] == [16384, -16384]
    assert _samples(audio.to_pcm16_wav(_wav(3, 1, 22050, 64, struct.pack("<2d", 0.25, -0.25))))[2] == [8191, -8191]


def test_pcm16_passes_through_untouched_and_stereo_is_preserved():
    import struct

    pcm = _wav(1, 1, 16000, 16, struct.pack("<3h", 1, 2, 3))
    assert audio.to_pcm16_wav(pcm) == pcm
    ch, rate, s = _samples(audio.to_pcm16_wav(_wav(3, 2, 44100, 32, struct.pack("<4f", 0.5, -0.5, 0.25, -0.25))))
    assert (ch, rate, len(s)) == (2, 44100, 4)


def test_extensible_header_and_truncated_data_chunk_are_handled():
    import struct

    floats = struct.pack("<4f", 0.5, 0.5, 0.5, 0.5)
    assert _samples(audio.to_pcm16_wav(_wav(3, 1, 8000, 32, floats, extensible=True)))[2] == [16383] * 4
    # a streamed WAV may declare a data size larger than what was actually sent
    assert len(_samples(audio.to_pcm16_wav(_wav(3, 1, 8000, 32, floats, declared_len=0xFFFFFFFF)))[2]) == 4
    # a partial trailing sample is dropped instead of crashing
    assert len(_samples(audio.to_pcm16_wav(_wav(3, 1, 8000, 32, floats + b"\x00\x00")))[2]) == 4


def test_unusable_audio_raises_value_error():
    with pytest.raises(ValueError):
        audio.to_pcm16_wav(b"not a wav at all")
    with pytest.raises(ValueError):
        audio.to_pcm16_wav(_wav(2, 1, 8000, 4, b"\x00\x00"))  # ADPCM: unsupported
    with pytest.raises(ValueError):
        audio.to_pcm16_wav(b"RIFF\x04\x00\x00\x00WAVE")  # no fmt/data chunks


# ---------------------------------------------------------------- forms
ABHA_OK = {"full_name": "Ravi Kumar", "mobile": "+91 98765 43210", "state": "Telangana", "district": "Hyderabad", "mobile_linked_to_aadhaar": "yes"}


def test_form_validation_happy_path():
    check = forms.check_form("abha_creation_help", ABHA_OK)
    assert check.ready, (check.errors, check.missing)
    assert check.cleaned["mobile"] == "9876543210" and check.cleaned["mobile_linked_to_aadhaar"] is True


def test_form_reports_missing_and_errors():
    check = forms.check_form("abha_creation_help", {"full_name": "Ravi", "mobile": "12345"})
    assert not check.ready and "mobile" in check.errors
    assert {f.name for f in check.missing} == {"state", "district", "mobile_linked_to_aadhaar"}


@pytest.mark.parametrize("raw,expected", [("yes", True), ("haan", True), ("nahi", False), ("అవును", True), ("maybe", None)])
def test_bool_field(raw, expected):
    check = forms.check_form("abha_creation_help", {**ABHA_OK, "mobile_linked_to_aadhaar": raw})
    if expected is None:
        assert "mobile_linked_to_aadhaar" in check.errors
    else:
        assert check.cleaned["mobile_linked_to_aadhaar"] is expected and check.ready


def test_pincode_ranges_and_choices():
    base = {"applicant_name": "A", "mobile": "9876543210", "state": "AP", "district": "G"}
    assert "pincode" in forms.check_form("ayushman_card_help", {**base, "pincode": "012345", "family_members": "4"}).errors
    assert "family_members" in forms.check_form("ayushman_card_help", {**base, "pincode": "522001", "family_members": "0"}).errors
    assert "preferred_time" in forms.check_form("ayushman_card_help", {**base, "pincode": "522001", "family_members": "4", "preferred_time": "midnight"}).errors
    assert forms.check_form("ayushman_card_help", {**base, "pincode": "522001", "family_members": "4", "preferred_time": "Morning"}).ready


@pytest.mark.parametrize("raw,ok", [("9876543210", True), ("+91-98765-43210", True), ("919876543210", True), ("5876543210", False), ("98765", False), ("", False)])
def test_normalise_mobile(raw, ok):
    from app.services.appointments import normalise_mobile

    assert (normalise_mobile(raw) == "9876543210") is ok


# ---------------------------------------------------------------- triage
@pytest.mark.parametrize(
    "text,urgency",
    [
        ("I have severe chest pain spreading to my arm", "emergency"),
        ("my father cannot breathe properly", "emergency"),
        ("she is unconscious and not waking up", "emergency"),
        ("his face is drooping and speech is slurred", "emergency"),
        ("I want to die", "emergency"),
        ("swallowed pesticide by mistake", "emergency"),
        ("fever for 5 days with body ache", "urgent"),
        ("persistent vomiting since yesterday", "urgent"),
        ("blood in stool", "urgent"),
        ("mild cold and cough since two days", "routine"),
        ("skin itching on my arms", "routine"),
    ],
)
def test_triage_urgency_levels(text, urgency):
    assert triage.assess(text)["urgency"] == urgency


def test_triage_pregnancy_and_infant_rules():
    assert triage.assess("some bleeding", pregnant=True)["urgency"] == "emergency"
    assert triage.assess("some bleeding", pregnant=False)["urgency"] != "emergency"
    assert triage.assess("fever", age=0)["urgency"] == "urgent"
    assert triage.assess("fever", age=30)["urgency"] == "routine"


@pytest.mark.parametrize(
    "text,age,specialty",
    [
        ("itchy rash on skin", 30, "dermatology"), ("tooth pain and swollen gum", 30, "dentistry"), ("knee and joint pain", 60, "orthopedics"),
        ("blurred vision in my eye", 50, "ophthalmology"), ("anxiety and panic, cannot sleep", 25, "psychiatry"),
        ("irregular periods", 28, "gynecology"), ("cough and cold", 6, "pediatrics"), ("cough and cold", 35, "general medicine"),
    ],
)
def test_triage_specialty(text, age, specialty):
    assert triage.assess(text, age)["suggested_specialty"] == specialty


def test_triage_emergency_includes_numbers_and_never_advises_waiting():
    out = triage.assess("chest pain")
    assert out["emergency_numbers"]["unified_emergency"] == "112" and "112" in out["advice"] and "Do not wait" in out["advice"]


# ---------------------------------------------------------------- log hygiene
def test_log_filter_redacts_websocket_tokens():
    import logging

    from app.core.logging import RedactTokens

    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc-DEF_123"
    # uvicorn logs: '%s - "WebSocket %s" [accepted]' % (addr, path)
    rec = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s" [accepted]', ("127.0.0.1:5", f"/api/v1/ws/chat?token={jwt_like}&x=1"), None)
    assert RedactTokens().filter(rec)
    out = rec.getMessage()
    assert jwt_like not in out and "token=REDACTED&x=1" in out
    plain = logging.LogRecord("app", logging.INFO, "", 0, f"GET /x?token={jwt_like}", None, None)
    RedactTokens().filter(plain)
    assert jwt_like not in plain.getMessage()


# ---------------------------------------------------------------- scheduling
def test_slot_generation_and_grid():
    from datetime import date

    from app.services import scheduling as s

    hours = [{"days": [0, 1, 2, 3, 4, 5], "start": "10:00", "end": "11:00"}]
    monday, sunday = date(2026, 11, 23), date(2026, 11, 22)
    assert [x.strftime("%H:%M") for x in s.slots_on(hours, 20, monday)] == ["10:00", "10:20", "10:40"]
    assert s.slots_on(hours, 20, sunday) == []
    assert s.is_on_grid(hours, 20, s.parse_local_slot("2026-11-23 10:20"))
    assert not s.is_on_grid(hours, 20, s.parse_local_slot("2026-11-23 10:30"))
    assert not s.is_on_grid(hours, 20, s.parse_local_slot("2026-11-23 11:00"))  # window end is exclusive


def test_parse_slot_formats_and_errors():
    from app.services import scheduling as s

    a = s.parse_local_slot("2026-11-23 10:20")
    assert a == s.parse_local_slot("2026-11-23T10:20") == s.parse_local_slot("2026-11-23T04:50:00+00:00")
    assert s.describe(a)["display"] == "Monday, 23 November 2026, 10:20 AM"
    with pytest.raises(ValueError):
        s.parse_local_slot("tomorrow morning")


def test_city_aliases():
    from app.services.scheduling import normalise_city

    assert normalise_city("Bangalore") == "bengaluru" and normalise_city(" Vizag ") == "visakhapatnam" and normalise_city("") is None

# ---------------------------------------------------------------- knowledge helpers
def test_tokenize_and_chunk():
    assert "the" not in tokenize("the farmer and the loan")
    assert tokenize("కిసాన్ పథకం") == ["కిసాన్", "పథకం"]
    chunks = chunk_text("a" * 500 + "\n\n" + "b" * 500 + "\n\n" + "c" * 100, max_chars=700)
    assert len(chunks) == 2


# ---------------------------------------------------------------- security helpers
def test_password_hash_roundtrip():
    h = hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", None)


def test_jwt_roundtrip_and_tamper():
    import uuid

    from app.core.errors import Unauthorized

    uid = uuid.uuid4()
    token = create_access_token(uid)
    assert decode_access_token(token) == uid
    with pytest.raises(Unauthorized):
        decode_access_token(token[:-3] + "abc")
    with pytest.raises(Unauthorized):
        decode_access_token("garbage")


def test_sliding_window_limits_then_recovers(monkeypatch):
    from app.middleware import rate_limit

    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    w = SlidingWindow()
    assert all(w.check("k", 3) is None for _ in range(3))
    assert w.check("k", 3) is not None
    assert w.check("other", 3) is None  # separate key
    now[0] += 61
    assert w.check("k", 3) is None

