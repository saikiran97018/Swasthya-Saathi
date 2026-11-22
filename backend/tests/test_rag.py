"""Retrieval (RAG): matching verified notes and the person's own bookings are put in front of the model on every turn."""
import pytest

from app.database.repositories.knowledge import KnowledgeRepository
from app.services.rag import RagService, mostly_latin
from tests.test_booking_api import book as rest_book
from tests.test_healthcare import first_slot, new_user, run, say

P = "/api/v1"


def notes(client, *texts: str) -> str:
    rag = RagService(client.app.state.settings, client.app.state.llm)
    return run(client, lambda s: rag.reference_notes(s, list(texts)))


def system_prompt(llm, n: int = 0) -> str:
    return llm.requests[n]["messages"][0]["content"]


@pytest.mark.parametrize("question,title", [
    ("how do I get an Ayushman card", "Ayushman Bharat"),
    ("my child has loose motions", "ORS"),
    ("where can I get cheap medicines", "Jan Aushadhi"),
    ("baby vaccine schedule", "immunisation"),
    ("my sugar is high", "Diabetes"),
    ("cough for 3 weeks", "Tuberculosis"),
    ("feeling very stressed and sad", "Mental health"),
    ("how to call an ambulance", "Emergency"),
    ("what is ABHA health id", "ABHA"),
    ("my mother was bitten by a snake", "Snakebite"),
    ("hot water burned my hand", "Burns"),
    ("dengue symptoms", "Dengue"),
    ("I feel very tired and pale", "Anaemia"),
    ("what is JSY", "Maternity"),
    ("free delivery in a government hospital", "Pregnancy"),
    ("helpline for women", "helpline"),
])
def test_the_right_note_comes_first(client, question, title):
    out = notes(client, question)
    assert out.startswith("REFERENCE NOTES"), question
    assert title.lower() in out.split("[1]")[1].split(":")[0].lower(), out[:400]  # the title of the first note


@pytest.mark.parametrize("question", ["best restaurant in Guntur", "who won the cricket match", "hello how are you", "thank you"])
def test_unrelated_talk_gets_no_notes(client, question):
    assert notes(client, question) == ""


def test_a_short_follow_up_keeps_the_earlier_topic(client):
    out = notes(client, "what is ABHA", "and how do I get it?")
    assert "ABHA" in out.split("[1]")[1][:60]


def test_other_languages_are_turned_into_an_english_query_first(make_client, llm):
    c = make_client()
    llm.title = "snake bite first aid"  # what the model's one-line translation returns
    out = notes(c, "मुझे साँप ने काटा है")
    assert "Snakebite" in out.split("[1]")[1][:60]
    assert any("MESSAGE" not in str(r) and r["messages"][0]["content"].startswith("Turn the user's message") for r in llm.requests)


def test_a_non_health_message_in_another_language_gets_no_notes(make_client, llm):
    c = make_client()
    llm.title = "NONE"
    assert notes(c, "आज मौसम कैसा है") == ""


def test_translation_failure_does_not_break_anything(make_client, llm):
    c = make_client()
    llm.fail_non_streaming = 500
    assert notes(c, "मुझे साँप ने काटा है") == ""


def test_script_detection():
    assert mostly_latin("my sugar is high") and mostly_latin("bukhar hai") and not mostly_latin("मुझे बुखार है") and not mostly_latin("నాకు జ్వరం")


def test_the_model_is_handed_the_notes_before_it_answers(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Give ORS in small sips."}]
    say(client, auth, "my child has loose motions")
    prompt = system_prompt(llm)
    assert "REFERENCE NOTES (verified" in prompt and "ORS" in prompt and "not from memory" in prompt


def test_small_talk_costs_no_extra_tokens(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Hello!"}]
    say(client, auth, "hello")
    assert "REFERENCE NOTES (verified" not in system_prompt(llm)


def test_the_model_knows_what_is_already_booked(client, llm):
    auth, _ = new_user(client)
    appt = rest_book(client, auth, first_slot(client, auth, days_ahead=3)).json()
    llm.script = [{"content": "You have a visit."}]
    say(client, auth, "when is my appointment?")
    assert f"Upcoming visits: {appt['ref']}" in system_prompt(llm)


def test_nothing_booked_adds_no_visit_line(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"content": "Hi."}]
    say(client, auth, "hello")
    assert "Upcoming visits" not in system_prompt(llm)


def test_retrieval_can_be_switched_off(make_client, llm):
    c = make_client(rag_enabled=False)
    auth, _ = new_user(c)
    llm.script = [{"content": "ok"}]
    say(c, auth, "my child has loose motions")
    assert "REFERENCE NOTES (verified" not in system_prompt(llm)


def test_a_retrieval_failure_never_breaks_the_chat(client, llm, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(KnowledgeRepository, "search", boom)
    auth, _ = new_user(client)
    llm.script = [{"content": "Still here."}]
    assert say(client, auth, "my child has loose motions")["assistant_message"]["content"] == "Still here."


def test_new_documents_reach_an_existing_database(client):
    titles = run(client, lambda s: KnowledgeRepository(s).titles())
    assert {"Snakebite first aid", "Burns first aid", "Maternity benefits: JSY, JSSK and PMMVY"} <= titles
