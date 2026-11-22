"""Working memory: what the assistant is in the middle of, kept as a few facts so it never loses the thread.

"Book the second one", "is it open today?", "for my mother" only make sense if the assistant still knows which three clinics it just
listed, which city and which symptoms were discussed. Those used to live only in raw tool messages that scroll out of the history
window. Now each tool result updates a small state (no extra model call, nothing guessed from free text) that is shown to the model
on every turn. A city mentioned in an earlier chat is offered as a default, to be confirmed.
"""
from __future__ import annotations

from typing import Any

KEY = "working_memory"
MAX_OPTIONS = 5


def _clip(value: Any, n: int) -> str:
    return " ".join(str(value or "").split())[:n]


def update(state: dict[str, Any] | None, tool: str, args: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """The new state after a tool ran successfully. Pure: returns a new dict."""
    s = dict(state or {})
    if tool == "find_healthcare_providers":
        if args.get("city"):
            s["city"] = _clip(args["city"], 60)
        if args.get("specialty"):
            s["specialty"] = _clip(args["specialty"], 40)
        options = [{"n": i, "code": r.get("code"), "name": _clip(r.get("name"), 60)} for i, r in enumerate((data.get("results") or [])[:MAX_OPTIONS], 1) if r.get("code")]
        if options:
            s["options"] = options
            s.pop("chosen", None)  # a new list: the old choice no longer applies
    elif tool == "assess_urgency":
        s["symptoms"] = _clip(args.get("symptoms"), 100)
        if data.get("urgency"):
            s["urgency"] = _clip(data["urgency"], 20)
        if data.get("suggested_specialty"):
            s["specialty"] = _clip(data["suggested_specialty"], 40)
        if args.get("age") is not None:
            s["age"] = args["age"]
    elif tool == "check_availability":
        prov = data.get("provider") or {}
        if prov.get("code"):
            s["chosen"] = {"code": prov["code"], "name": _clip(prov.get("name"), 60)}
            if prov.get("city"):
                s.setdefault("city", _clip(prov["city"], 60))
    elif tool == "book_appointment":
        if args.get("patient_name"):
            s["patient"] = _clip(args["patient_name"], 60)
        if data.get("ref"):
            s["booked"] = f"{data['ref']} {_clip(data.get('when'), 40)}".strip()
    return {k: v for k, v in s.items() if v not in (None, "", [])}


def render(state: dict[str, Any] | None, earlier_city: str | None = None) -> str:
    """One compact block for the system prompt ('' when there is nothing to remember)."""
    s = state or {}
    parts: list[str] = []
    if s.get("city"):
        parts.append(f"city {s['city']}")
    elif earlier_city:
        parts.append(f"city in an earlier chat: {earlier_city} (confirm it before using it)")
    if s.get("symptoms"):
        extra = ", ".join(x for x in (s.get("urgency"), f"see {s['specialty']}" if s.get("specialty") else None) if x)
        parts.append(f"symptoms: {s['symptoms']}" + (f" ({extra})" if extra else ""))
    elif s.get("specialty"):
        parts.append(f"looking for: {s['specialty']}")
    if s.get("options"):
        parts.append("options just shown: " + "; ".join(f"{o['n']}) {o['name']} [{o['code']}]" for o in s["options"]))
    if s.get("chosen"):
        parts.append(f"currently looking at: {s['chosen']['name']} [{s['chosen']['code']}]")
    if s.get("patient"):
        parts.append(f"patient: {s['patient']}")
    if s.get("booked"):
        parts.append(f"just booked: {s['booked']}")
    if not parts:
        return ""
    return "Conversation memory (use it to resolve \"it\", \"the second one\", \"there\", \"same as before\"): " + "; ".join(parts) + "."
