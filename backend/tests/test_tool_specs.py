"""The tool definitions sent to the model must stay small and complete (free-tier models limit tokens per minute)."""
import json

from app.agents.prompts import build_system_prompt
from app.agents.tools import build_registry
from app.core.config import Settings

S = Settings(_env_file=None)


def specs():
    return {s["function"]["name"]: s["function"] for s in build_registry().specs(S)}


def test_every_required_parameter_is_still_described():
    for name, fn in specs().items():
        params = fn["parameters"]
        for req in params.get("required", []):
            assert req in params["properties"], f"{name}: required '{req}' missing from properties"


def test_parameter_named_title_survives_cleaning():
    assert "title" in specs()["create_task"]["parameters"]["properties"]


def test_validation_noise_is_not_sent_but_still_enforced():
    blob = json.dumps(list(specs().values()))
    for noise in ("minLength", "maxLength", '"minimum"', '"maximum"', '"anyOf"', '"default"'):
        assert noise not in blob, noise
    # the server still rejects bad arguments, whatever the model was told
    reg = build_registry()
    from app.agents.tools import ToolError

    try:
        reg.parse_args(reg.get("book_appointment"), json.dumps({"provider_code": "X", "slot_start": "2026-01-01 10:00", "patient_name": "A", "patient_mobile": "1", "reason": "x"}))
    except ToolError:
        pass
    else:
        raise AssertionError("short mobile number / name should still be rejected")


def test_optional_parameters_stay_nullable():
    # Groq validates tool calls strictly: a model that sends "age": null must not be rejected
    age = specs()["assess_urgency"]["parameters"]["properties"]["age"]
    assert age["type"] == ["integer", "null"]
    specialty = specs()["find_healthcare_providers"]["parameters"]["properties"]["specialty"]
    assert "null" in specialty["type"] and None in specialty["enum"]


def test_every_tool_has_a_short_model_description():
    for name, fn in specs().items():
        assert 10 < len(fn["description"]) <= 200, name


def test_request_overhead_stays_small():
    tools_chars = len(json.dumps(list(specs().values())))
    prompt_chars = len(build_system_prompt(language="te", summary=None, voice=False, display_name=None))
    assert tools_chars < 9500, tools_chars  # was 11.5k before slimming; 9.0k before the medicine-shop and medicine-reminder tools
    assert prompt_chars < 4000, prompt_chars  # was 4.4k before slimming
