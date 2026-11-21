"""The assistant can control the web app on screen (open pages, switch theme); the browser carries the action out."""
import pytest

from app.agents.tools import UI_PAGES, build_registry
from tests.test_healthcare import say, tool_result

P = "/api/v1"


def run_tool(client, auth, llm, args):
    llm.script = [{"tool_calls": [("control_app", args)]}, {"content": "Done."}]
    return tool_result(say(client, auth, "please do that on screen"))


def test_open_a_page_returns_an_action_for_the_browser(client, auth, llm):
    t = run_tool(client, auth, llm, {"action": "open_page", "page": "care_plan"})
    assert t["status"] == "success" and t["requires_confirmation"] is False  # it only changes the screen: no confirm card
    assert t["result"]["ui_action"] == {"type": "open_page", "page": "care_plan", "path": "/appointments", "label": "Care Plan"}


def test_every_page_maps_to_a_known_route():
    allowed = {"/", "/chat", "/find-care", "/appointments", "/family", "/sos", "/history", "/activity", "/settings", "/settings/language", "/call"}
    assert {path for path, _ in UI_PAGES.values()} == allowed


def test_doctors_page_can_start_a_city_search(client, auth, llm):
    t = run_tool(client, auth, llm, {"action": "open_page", "page": "doctors", "city": "  Guntur  "})
    assert t["result"]["ui_action"]["path"] == "/find-care?city=Guntur"
    t = run_tool(client, auth, llm, {"action": "open_page", "page": "doctors", "city": "A&B=C /x"})
    assert t["result"]["ui_action"]["path"] == "/find-care?city=A%26B%3DC+%2Fx"  # the city is encoded, it can never add parameters or paths
    t = run_tool(client, auth, llm, {"action": "open_page", "page": "family", "city": "Guntur"})
    assert t["result"]["ui_action"]["path"] == "/family"  # a city only matters for the doctors page


def test_switch_theme(client, auth, llm):
    for theme in ("dark", "light", "system"):
        assert run_tool(client, auth, llm, {"action": "set_theme", "theme": theme})["result"]["ui_action"] == {"type": "set_theme", "theme": theme}


@pytest.mark.parametrize("args", [{"action": "open_page"}, {"action": "set_theme"}])
def test_missing_pieces_are_reported_to_the_model(client, auth, llm, args):
    t = run_tool(client, auth, llm, args)
    assert t["status"] == "error" and "ui_action" not in (t["result"] or {})


@pytest.mark.parametrize("args", [{"action": "open_page", "page": "https://evil.example.com"}, {"action": "open_page", "page": "../../etc"}, {"action": "open_page", "page": "voice"}, {"action": "delete_everything"}])
def test_nothing_outside_the_list_is_accepted(client, auth, llm, args):
    t = run_tool(client, auth, llm, args)
    assert t["status"] == "error" and "ui_action" not in (t["result"] or {})


def test_the_tool_is_registered_without_confirmation():
    tool = build_registry().get("control_app")
    assert tool is not None and tool.requires_confirmation is False and tool.category == "read"
