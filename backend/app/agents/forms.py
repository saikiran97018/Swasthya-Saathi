"""Catalog of assisted forms and their validation rules.

The agent can only fill/submit forms defined here, and every value is validated in code -- the model
never decides what counts as valid. We deliberately never collect a full Aadhaar number, bank or card
numbers: only what a health facilitator needs to call the person back and help.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.appointments import normalise_mobile


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    hint: str
    kind: str = "text"  # text | phone | int | pincode | choice | bool
    required: bool = True
    choices: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class FormSpec:
    form_id: str
    title: str
    description: str
    fields: tuple[FormField, ...]
    submit_note: str = ""


FORMS: dict[str, FormSpec] = {
    spec.form_id: spec
    for spec in [
        FormSpec(
            form_id="ayushman_card_help",
            title="Ayushman Bharat card assistance request",
            description="Ask a health facilitator (ASHA worker / Common Service Centre) to help check eligibility and get an Ayushman Bharat PM-JAY card.",
            fields=(
                FormField("applicant_name", "Applicant name", "Name of the head of the family"),
                FormField("mobile", "Mobile number", "10-digit Indian mobile number", kind="phone"),
                FormField("state", "State", "State of residence"),
                FormField("district", "District", "District of residence"),
                FormField("pincode", "PIN code", "6-digit PIN code", kind="pincode"),
                FormField("family_members", "Family members", "Number of people in the household", kind="int", min_value=1, max_value=50),
                FormField("preferred_time", "Best time to call", "morning, afternoon or evening", kind="choice", choices=("morning", "afternoon", "evening"), required=False),
            ),
            submit_note="This records your request under a reference number so a facilitator can call you back. It does not apply for the card by itself.",
        ),
        FormSpec(
            form_id="abha_creation_help",
            title="ABHA health ID assistance request",
            description="Ask for help creating an ABHA (Ayushman Bharat Health Account) digital health ID.",
            fields=(
                FormField("full_name", "Full name", "Name as on your ID"),
                FormField("mobile", "Mobile number", "10-digit Indian mobile number", kind="phone"),
                FormField("state", "State", "State of residence"),
                FormField("district", "District", "District of residence"),
                FormField("mobile_linked_to_aadhaar", "Mobile linked to Aadhaar?", "yes or no", kind="bool"),
                FormField("preferred_time", "Best time to call", "morning, afternoon or evening", kind="choice", choices=("morning", "afternoon", "evening"), required=False),
            ),
            submit_note="This records your request under a reference number so a facilitator can call you back and help create the ABHA ID.",
        ),
    ]
}

_PIN = re.compile(r"^[1-9]\d{5}$")
_TRUE = {"yes", "y", "true", "1", "haan", "ha", "avunu", "aam", "hoon", "हाँ", "हां", "అవును", "ஆம்", "ಹೌದು", "അതെ", "হ্যাঁ"}
_FALSE = {"no", "n", "false", "0", "nahi", "nahin", "kadu", "illai", "नहीं", "కాదు", "இல்லை", "ಇಲ್ಲ", "അല്ല", "না"}


def _validate(field_: FormField, raw: object) -> tuple[object | None, str | None]:
    text = str(raw).strip()
    if not text:
        return None, "is empty"
    k = field_.kind
    try:
        if k == "phone":
            phone = normalise_mobile(text)
            return (phone, None) if phone else (None, "must be a 10-digit mobile number starting with 6-9")
        if k == "pincode":
            digits = re.sub(r"\s", "", text)
            return (digits, None) if _PIN.match(digits) else (None, "must be a 6-digit PIN code")
        if k == "int":
            num = int(float(text))
            if field_.min_value is not None and num < field_.min_value:
                return None, f"must be at least {field_.min_value:g}"
            if field_.max_value is not None and num > field_.max_value:
                return None, f"must be at most {field_.max_value:g}"
            return num, None
        if k == "choice":
            v = text.lower()
            return (v, None) if v in field_.choices else (None, f"must be one of: {', '.join(field_.choices)}")
        if k == "bool":
            v = text.lower()
            if v in _TRUE:
                return True, None
            if v in _FALSE:
                return False, None
            return None, "must be yes or no"
    except (ValueError, TypeError):
        return None, f"is not a valid {k}"
    if len(text) > 300:
        return None, "is too long"
    return text, None


@dataclass
class FormCheck:
    form_id: str
    cleaned: dict[str, object] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    missing: list[FormField] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors and not self.missing


def check_form(form_id: str, values: dict[str, object]) -> FormCheck:
    spec = FORMS[form_id]
    result = FormCheck(form_id=form_id)
    known = {f.name: f for f in spec.fields}
    for name, raw in values.items():
        f = known.get(name)
        if f is None or raw is None or str(raw).strip() == "":
            continue  # unknown or blank fields are simply ignored
        cleaned, err = _validate(f, raw)
        if err:
            result.errors[name] = f"{f.label} {err}"
        else:
            result.cleaned[name] = cleaned
    for f in spec.fields:
        if f.required and f.name not in result.cleaned and f.name not in result.errors:
            result.missing.append(f)
    return result


def form_catalog() -> list[dict]:
    return [{"form_id": s.form_id, "title": s.title, "description": s.description, "fields": [f.name for f in s.fields]} for s in FORMS.values()]
