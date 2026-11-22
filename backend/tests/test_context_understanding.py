"""Context understanding: transcript validation, intent classification (rules + model) and working memory."""
import pytest

from app.services import working_memory as wm
from app.services.intent import Intent, IntentService, classify_rules, parse_llm_answer
from app.utils.transcript import check_transcript, collapse_repeats
from tests.fakes import make_wav
from tests.test_healthcare import new_user, run, say

P = "/api/v1"


def prompt_of(llm, n: int = 0) -> str:
    return llm.requests[n]["messages"][0]["content"]


def answer_prompt(llm) -> str:
    """The system prompt of the last ANSWERING model call (title and classifier calls are not streamed)."""
    return [r for r in llm.requests if r.get("stream")][-1]["messages"][0]["content"]


# ======================================================================== transcript validation
@pytest.mark.parametrize("text,reason", [
    ("", "empty"), ("   ", "empty"), ("...", "empty"), ("[music]", "empty"), ("(applause)", "empty"), ("♪", "empty"),
    ("hmm", "noise"), ("uh um", "noise"), ("a", "noise"),
    ("Thanks for watching!", "invented"), ("Subtitles by the Amara.org community", "invented"), ("please subscribe to my channel", "invented"),
])
def test_made_up_or_empty_transcripts_are_rejected(text, reason):
    r = check_transcript(text)
    assert not r.ok and r.reason == reason


@pytest.mark.parametrize("text", ["yes", "no", "haan", "नहीं", "5", "I have fever", "ok", "mujhe bukhar hai", "నాకు జ్వరం ఉంది", "book it", "thank you"])
def test_real_answers_pass_including_one_word_replies(text):
    assert check_transcript(text).ok


def test_loops_are_collapsed_but_emphasis_is_kept():
    assert collapse_repeats("I have fever I have fever I have fever I have fever I have fever") == "I have fever"
    assert collapse_repeats("no no no") == "no no no"
    assert collapse_repeats("no no no no no no") == "no"
    assert check_transcript("मुझे बुखार है " * 5).text == "मुझे बुखार है"
    assert check_transcript("(applause) I want to book an appointment").text == "I want to book an appointment"


def test_the_transcribe_route_refuses_an_invented_caption(client, bhashini):
    auth, _ = new_user(client)
    bhashini.transcript = "Thanks for watching!"
    r = client.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", make_wav(1.0), "audio/wav")}, data={"language": "en"}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unclear_speech"
    bhashini.transcript = "mujhe bukhar hai mujhe bukhar hai mujhe bukhar hai mujhe bukhar hai mujhe bukhar hai"
    ok = client.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", make_wav(1.0), "audio/wav")}, data={"language": "hi"}, headers=auth)
    assert ok.status_code == 200 and ok.json()["text"] == "mujhe bukhar hai"


def test_a_voice_message_that_is_only_noise_never_reaches_the_model(client, llm):
    auth, _ = new_user(client)
    r = client.post(f"{P}/chat", json={"message": "hmm", "input_mode": "voice"}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unclear_speech"
    assert llm.requests == []
    assert client.post(f"{P}/chat", json={"message": "hmm", "input_mode": "text"}, headers=auth).status_code == 200  # typed text is the person's own


# ======================================================================== intent: rules
@pytest.mark.parametrize("text,label", [
    ("I have chest pain", "emergency"), ("my father is unconscious", "emergency"), ("मेरी माँ को साँप ने काटा", "emergency"), ("ఛాతీ నొప్పి గా ఉంది", "emergency"),
    ("I want to kill myself", "emergency"), ("मुझे सीने में दर्द है", "emergency"),
    ("I have fever since two days", "symptoms"), ("मुझे बुखार है", "symptoms"),
    ("book an appointment for tomorrow", "book"), ("cancel my appointment", "cancel"), ("I need to reschedule", "reschedule"),
    ("when is my appointment", "my_appointments"), ("find a dentist near me", "find_care"),
    ("how do I get an Ayushman card", "scheme_info"), ("what is diabetes", "health_info"),
    ("open settings screen", "app_control"), ("hello", "smalltalk"), ("thank you", "smalltalk"),
    ("yes", "confirm_yes"), ("no", "confirm_no"), ("haan", "confirm_yes"),
    ("the weather today is nice and sunny outside", "other"),
])
def test_rules(text, label):
    assert classify_rules(text) == label


def test_emergency_beats_every_other_word():
    assert classify_rules("book an appointment, my mother has chest pain") == "emergency"


# ======================================================================== intent: model layer
def test_parse_model_answer():
    assert parse_llm_answer('{"intent": "symptoms", "query": "fever in children"}') == Intent("symptoms", "fever in children", "llm")
    assert parse_llm_answer('Sure! {"intent":"book","query":""} done').label == "book"
    assert parse_llm_answer('{"intent": "dance"}') is None and parse_llm_answer("no json") is None and parse_llm_answer(None) is None


def classify(client, text):
    svc = IntentService(client.app.state.settings, client.app.state.llm)
    return client.portal.call(svc.classify, text)


def test_other_scripts_use_one_model_call_that_also_gives_the_search_query(make_client, llm):
    c = make_client()
    llm.title = '{"intent": "health_info", "query": "child vaccination schedule"}'
    got = classify(c, "बच्चे को कौन से टीके लगते हैं")
    assert got == Intent("health_info", "child vaccination schedule", "llm") and len(llm.requests) == 1


def test_rules_that_are_sure_cost_no_model_call(make_client, llm):
    c = make_client()
    assert classify(c, "I have chest pain").emergency and classify(c, "cancel my appointment").label == "cancel"
    assert llm.requests == []


def test_a_model_failure_falls_back_to_the_rules(make_client, llm):
    c = make_client()
    llm.fail_non_streaming = 500
    assert classify(c, "मुझे बुखार है").label == "symptoms"
    llm.fail_non_streaming = None
    llm.title = "not json at all"
    assert classify(c, "मुझे बुखार है").label == "symptoms"


def test_a_vague_model_answer_does_not_override_a_concrete_rule(make_client, llm):
    c = make_client()
    llm.title = '{"intent": "other", "query": ""}'
    assert classify(c, "मुझे बुखार है").label == "symptoms"


def test_the_model_layer_can_be_switched_off(make_client, llm):
    c = make_client(intent_llm_enabled=False)
    assert classify(c, "बच्चे को कौन से टीके लगते हैं").label == "other" and llm.requests == []


# ======================================================================== intent: effect on the answer
def test_possible_emergency_puts_an_instruction_first_in_the_prompt(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Please call 112 now."}]
    say(client, auth, "my father has chest pain and is sweating")
    p = prompt_of(llm)
    assert "POSSIBLE EMERGENCY" in p and "call 112" in p
    assert p.index("POSSIBLE EMERGENCY") < p.index("REFERENCE NOTES (verified") or "REFERENCE NOTES (verified" not in p


def test_each_intent_adds_its_hint_and_the_answer_records_it(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Which city are you in?"}]
    say(client, auth, "I have fever since two days")
    assert "call assess_urgency first" in prompt_of(llm)

    async def last_meta(session):
        from sqlalchemy import select
        from app.database.models import Message
        return (await session.scalars(select(Message.meta).where(Message.role == "assistant").order_by(Message.created_at.desc()).limit(1))).first()

    assert run(client, last_meta)["intent"] == "symptoms"


def test_booking_talk_skips_retrieval_to_save_tokens(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Sure."}]
    say(client, auth, "please book an appointment for my child with a fever")  # booking wins over the fever words
    assert "REFERENCE NOTES (verified" not in prompt_of(llm)
    llm.script = [{"content": "ok"}]
    say(client, auth, "what is ABHA health id")
    assert "REFERENCE NOTES (verified" in answer_prompt(llm)


def test_the_classifier_query_replaces_the_second_translation_call(make_client, llm):
    c = make_client()
    auth, _ = new_user(c)
    llm.title = '{"intent": "health_info", "query": "snake bite first aid"}'
    llm.script = [{"content": "Go to hospital."}]
    say(c, auth, "साँप के काटने पर क्या करें")
    system = [r["messages"][0]["content"] for r in llm.requests if not r.get("stream")]
    assert sum(s.startswith("Classify") for s in system) == 1 and not any(s.startswith("Turn the user's message") for s in system)
    assert "Snakebite" in answer_prompt(llm)  # ...and the query it returned found the right note


# ======================================================================== working memory
def test_memory_follows_the_conversation_step_by_step():
    s = wm.update(None, "assess_urgency", {"symptoms": "fever for two days", "age": 30}, {"urgency": "routine", "suggested_specialty": "general medicine"})
    s = wm.update(s, "find_healthcare_providers", {"city": "Guntur", "specialty": "general medicine"},
                  {"results": [{"code": "HC-1", "name": "Alpha Clinic"}, {"code": "OSM-2", "name": "Beta Hospital"}, {"name": "no code"}]})
    text = wm.render(s)
    assert "city Guntur" in text and "fever for two days (routine, see general medicine)" in text
    assert "1) Alpha Clinic [HC-1]; 2) Beta Hospital [OSM-2]" in text and "no code" not in text
    s = wm.update(s, "check_availability", {}, {"provider": {"code": "OSM-2", "name": "Beta Hospital", "city": "Guntur"}})
    assert "currently looking at: Beta Hospital [OSM-2]" in wm.render(s)
    s = wm.update(s, "book_appointment", {"patient_name": "Ravi Kumar"}, {"ref": "AP-ABC12", "when": "Mon 23 Nov, 10:00 AM"})
    assert "patient: Ravi Kumar" in wm.render(s) and "just booked: AP-ABC12 Mon 23 Nov, 10:00 AM" in wm.render(s)


def test_a_new_list_forgets_the_old_choice_and_empty_memory_renders_nothing():
    s = {"chosen": {"code": "X", "name": "Old"}}
    s = wm.update(s, "find_healthcare_providers", {"city": "Tenali"}, {"results": [{"code": "N1", "name": "New"}]})
    assert "chosen" not in s and wm.render({}) == "" and wm.render(None) == ""


def test_an_earlier_city_is_offered_only_as_a_default_to_confirm():
    assert "city in an earlier chat: Guntur (confirm" in wm.render({}, "Guntur")
    assert "earlier chat" not in wm.render({"city": "Tenali"}, "Guntur")


def test_the_model_sees_which_clinics_it_just_listed(client, llm):
    auth, _ = new_user(client)
    llm.script = [
        {"tool_calls": [("find_healthcare_providers", {"specialty": "general medicine", "city": "Guntur"})]},
        {"content": "Here are some options."},
    ]
    first = say(client, auth, "find a clinic in Guntur")
    llm.script = [{"content": "Booking the second one."}]
    say(client, auth, "book the second one", conversation_id=first["conversation"]["id"])
    p = answer_prompt(llm)
    assert "Conversation memory" in p and "city Guntur" in p and "options just shown: 1)" in p


def test_a_city_from_an_earlier_chat_is_carried_into_a_new_one(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"tool_calls": [("find_healthcare_providers", {"specialty": "general medicine", "city": "Guntur"})]}, {"content": "ok"}]
    say(client, auth, "find a clinic in Guntur")
    llm.script = [{"content": "Which city?"}]
    say(client, auth, "I have a headache")  # no conversation_id: a brand new chat
    assert "city in an earlier chat: Guntur" in answer_prompt(llm)


def test_memory_is_private_to_each_person(client, llm):
    a, _ = new_user(client)
    b, _ = new_user(client)
    llm.script = [{"tool_calls": [("find_healthcare_providers", {"specialty": "general medicine", "city": "Guntur"})]}, {"content": "ok"}]
    say(client, a, "find a clinic in Guntur")
    llm.script = [{"content": "hi"}]
    say(client, b, "I have a headache")
    assert "Guntur" not in answer_prompt(llm)
