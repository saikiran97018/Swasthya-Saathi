"""Response validation: replies are checked for invented facts, unsafe advice, wrong language and unspeakable text before use."""
import pytest

from app.services.response_validator import EMERGENCY_LINE, SAFE_FALLBACK, fallback_text, speakable, validate_response
from tests.test_healthcare import new_user, say

P = "/api/v1"
GROUND = "Helplines 112 and 108, 104 health advice. Clinic: Dr Rao Clinic, phone 98765 43210, fee Rs 300. Booking AP-ABC12. Dengue note: do not take aspirin or ibuprofen."


def check(text, *, language="en", voice=False, intent="other", grounding=GROUND, **kw):
    return validate_response(text, language=language, voice=voice, intent=intent, grounding=grounding, **kw)


# ======================================================================== facts must come from the material
@pytest.mark.parametrize("text", [
    "Call 112 now.", "The clinic phone is 98765 43210.", "Phone 9876543210 or 98765-43210.", "The fee is Rs 300.", "The fee is ₹300.",
    "Your booking is AP-ABC12.", "Your booking is ap-abc12.", "Visit at 10:30 on 23 November 2026.", "It takes about 120 minutes.", "Call 104 for advice.",
    "Call 14416 for mental health support.",
])
def test_grounded_facts_pass(text):
    assert check(text).ok, check(text).problems


@pytest.mark.parametrize("text,problem", [
    ("The clinic phone is 91234 56789.", "ungrounded_number"), ("Call 9123456789 now.", "ungrounded_number"), ("Dial 14999 for help.", "ungrounded_number"),
    ("The fee is Rs 500.", "ungrounded_amount"), ("It costs ₹1,250.", "ungrounded_amount"), ("Your booking is AP-ZZZ99.", "ungrounded_ref"),
])
def test_invented_facts_are_caught(text, problem):
    assert problem in check(text).problems


def test_the_phone_number_of_a_clinic_found_this_turn_is_allowed():
    assert check("Call them on 97000 11122.", grounding=GROUND + ' {"phone": "9700011122"}').ok


# ======================================================================== safety
@pytest.mark.parametrize("text,problem", [
    ("Take 500 mg twice a day.", "dose"), ("Give two tablets after food.", "dose"), ("You can take paracetamol for the fever.", "drug"),
    ("You have dengue.", "diagnosis"), ("It is definitely malaria.", "diagnosis"), ("You are suffering from diabetes.", "diagnosis"),
])
def test_unsafe_medical_advice_is_caught(text, problem):
    assert problem in check(text, grounding="plain").problems


def test_a_medicine_named_in_a_verified_note_may_be_repeated_as_a_warning():
    assert check("In dengue do not take aspirin or ibuprofen unless a doctor says so.").ok


def test_describing_a_possibility_is_not_a_diagnosis():
    assert check("Fever with chills can be dengue or malaria, so please get a blood test.").ok


@pytest.mark.parametrize("text", ["I will call find_healthcare_providers now.", "As my instructions say...", "The REFERENCE NOTES say so.", "tool_call failed"])
def test_leaks_of_instructions_and_tool_names_are_caught(text):
    assert "leak" in check(text).problems


def test_an_emergency_answer_always_names_112():
    v = check("Please stay calm and sit down.", intent="emergency")
    assert v.ok and v.text.startswith(EMERGENCY_LINE["en"]) and "emergency_line" in v.repairs
    assert check("Call 112 right away.", intent="emergency").repairs == []  # already says it
    assert check("शांत रहिए।", language="hi", intent="emergency").text.startswith(EMERGENCY_LINE["hi"])


def test_every_language_has_a_localized_emergency_and_fallback_line():
    assert set(EMERGENCY_LINE) == set(SAFE_FALLBACK) == {"en", "hi", "te", "ta", "kn", "ml", "bn", "mr", "gu", "pa"}
    assert all("112" in line and "108" in line for line in EMERGENCY_LINE.values())
    assert all("104" in line for line in SAFE_FALLBACK.values())
    assert fallback_text("te", "other") == SAFE_FALLBACK["te"] and EMERGENCY_LINE["te"] in fallback_text("te", "emergency")
    assert fallback_text("or", "other") == SAFE_FALLBACK["en"]  # no translation yet: English


# ======================================================================== relevance and speech
def test_empty_replies_are_problems():
    assert check("").problems == ["empty"] and check("  . ").problems == ["empty"]


def test_the_reply_language_must_match_the_persons_language():
    telugu = "జ్వరం కోసం సాధారణ వైద్యుడిని చూడాలి. మీరు ఏ నగరంలో ఉన్నారు, చెప్పండి."
    english = "Please visit the clinic tomorrow morning and carry your previous reports with you."
    assert "wrong_language" in check(telugu, language="en").problems  # asked in English, answered in Telugu
    assert "wrong_language" in check(telugu, language="hi").problems  # Hindi speaker, Telugu answer
    assert "wrong_language" in check(english, language="hi").problems
    assert check(telugu, language="te").ok and check("आपका स्वागत है। अगर कुछ और चाहिए, तो बताइए, मैं यहीं हूँ।", language="hi").ok
    assert check("ABHA అంటే Ayushman Bharat Health Account. ఇది free 14-digit digital health ID, మీరు ఉపయోగించవచ్చు.", language="te").ok  # code-mixed is fine
    assert "wrong_language" in check("ABHA అంటే Ayushman Bharat Health Account. ఇది free 14-digit digital health ID, మీరు ఉపయోగించవచ్చు.", language="en").problems


def test_a_word_mixing_two_scripts_is_a_garbled_reply():
    assert "wrong_language" in check("क्या आप अभी ज్वर के लिए किसी डॉक्टर को दिखाना चाहते हैं? अपना शहर बताइए।", language="hi").problems
    assert check("क्या आप अभी बुखार के लिए किसी डॉक्टर को दिखाना चाहते हैं? अपना शहर बताइए।", language="hi").ok
    assert check("Guntur-లో మంచి doctor ఉన్నారా, చెప్పండి మీ నగరం ఏదో మాకు.", language="te").ok  # English and Telugu words side by side are fine


def test_the_wrong_language_is_caught_but_names_and_short_replies_are_not():
    long_english = "Please visit the clinic tomorrow morning and carry your previous reports with you."
    assert "wrong_language" in check(long_english, language="te").problems
    assert check("సరే, Dr Rao Clinic కి వెళ్ళండి.", language="te").ok
    assert check("OK", language="te").ok
    assert check(long_english, language="en").ok


def test_voice_replies_lose_markdown_links_and_emoji_and_stay_short():
    assert speakable("**Hello** see https://x.com now 😀\n- one\n- two") == "Hello see now one two"
    v = check("**Book** it 😀 https://x.com", voice=True)
    assert v.text == "Book it" and "speakable" in v.repairs or v.text == "Book it"
    long = " ".join(["This is a sentence about your health."] * 40)
    out = check(long, voice=True)
    assert len(out.text) <= 620 and out.text.endswith(".") and "trimmed" in out.repairs
    assert "**" in check("**bold** text", voice=False).text  # typed replies keep their formatting


# ======================================================================== in the live pipeline
def last_meta(client):
    from sqlalchemy import select

    from app.database.models import Message
    from tests.test_healthcare import run

    async def go(session):
        return (await session.scalars(select(Message.meta).where(Message.role == "assistant").order_by(Message.created_at.desc()).limit(1))).first()

    return run(client, go)


def test_an_invented_phone_number_never_reaches_the_user(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "You can call the clinic on 91234 56789."}]
    llm.title = "I am not able to share a number I am sure of. Please check the clinic's own listing."  # the one rewrite
    out = say(client, auth, "what is the clinic number")
    assert "91234" not in out["assistant_message"]["content"] and "not able to share" in out["assistant_message"]["content"]
    meta = last_meta(client)["validation"]
    assert meta["problems"] == ["ungrounded_number"] and meta["action"] == "rewritten"


def test_if_the_rewrite_is_bad_too_the_safe_fallback_is_used(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Take paracetamol 500 mg."}]
    llm.title = "Take paracetamol 500 mg then."
    out = say(client, auth, "I have a headache")
    assert out["assistant_message"]["content"] == SAFE_FALLBACK["en"]
    assert last_meta(client)["validation"]["action"] == "fallback"


def test_without_retry_a_real_problem_goes_straight_to_the_fallback(make_client, llm):
    c = make_client(response_validation_retry=False)
    auth, _ = new_user(c)
    llm.script = [{"content": "You have dengue."}]
    assert say(c, auth, "I have fever")["assistant_message"]["content"] == SAFE_FALLBACK["en"]
    assert [r for r in llm.requests if not r.get("stream") and r["messages"][0]["content"].startswith("Your last draft")] == []


def test_a_clean_reply_is_untouched_and_costs_no_extra_call(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Fever can come from many things. Please drink water and see a doctor if it lasts."}]
    out = say(client, auth, "I have fever")
    assert out["assistant_message"]["content"].startswith("Fever can come")
    assert "validation" not in (last_meta(client) or {})
    assert not any("Your last draft" in str(r["messages"]) for r in llm.requests)


def test_an_emergency_reply_gets_the_112_line_added(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Please sit down and stay calm."}]
    out = say(client, auth, "my father has chest pain")
    assert out["assistant_message"]["content"].startswith(EMERGENCY_LINE["en"])
    assert last_meta(client)["validation"]["repairs"] == ["emergency_line"]


def test_the_check_can_be_switched_off(make_client, llm):
    c = make_client(response_validation_enabled=False)
    auth, _ = new_user(c)
    llm.script = [{"content": "Call 91234 56789."}]
    assert "91234" in say(c, auth, "number please")["assistant_message"]["content"]


def test_a_spoken_reply_is_held_until_checked(client, llm):
    """Voice: the invented number is never streamed to the speaker, only the checked text is."""
    auth, _ = new_user(client)
    llm.script = [{"content": "Call 91234 56789 now."}]
    llm.title = "Please check the clinic listing for its number."
    r = client.post(f"{P}/chat", json={"message": "number please", "voice_output": True}, headers=auth)
    assert r.status_code == 200 and "91234" not in r.text and "clinic listing" in r.json()["assistant_message"]["content"]
