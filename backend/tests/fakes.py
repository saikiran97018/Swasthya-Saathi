"""Fake HTTP backends for tests: a scripted OpenAI-compatible LLM, Bhashini, and tool APIs."""
from __future__ import annotations

import base64
import io
import json
import struct
import wave
from typing import Any

import httpx

BHASHINI_CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
BHASHINI_COMPUTE_URL = "https://dhruva.test/services/inference/pipeline"


def make_wav(seconds: float = 1.0, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels if width == 2 else b"\x01" * int(rate * seconds) * channels)
    return buf.getvalue()


def make_float_wav(seconds: float = 0.1, rate: int = 8000, value: float = 0.5) -> bytes:
    """32-bit IEEE-float mono WAV with a fact chunk: exactly what the real Bhashini TTS returns."""
    n = int(rate * seconds)
    data = struct.pack(f"<{n}f", *([value] * n))
    fmt = struct.pack("<HHIIHHH", 3, 1, rate, rate * 4, 4, 32, 0)  # 18-byte fmt chunk (cbSize = 0)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"fact" + struct.pack("<II", 4, n) + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _sse(data: dict | str) -> str:
    return "data: " + (data if isinstance(data, str) else json.dumps(data)) + "\n\n"


class FakeLLM:
    """Scripted chat-completions server. Each streaming call consumes one script step:

    {"content": "text"}                       -> plain answer (streamed in two chunks)
    {"content": "..", "tool_calls": [(name, args_dict), ...]}  -> ask for tools
    {"error": 500}                            -> HTTP error
    Non-streaming calls (titles / summaries) always return `title`.
    """

    def __init__(self, script: list[dict[str, Any]] | None = None, title: str = "Test Title"):
        self.script = list(script or [])
        self.title = title
        self.requests: list[dict[str, Any]] = []
        self.auth_headers: list[str | None] = []
        self.fail_non_streaming: int | None = None  # make title/summary/translation calls fail with this status
        self._n = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.requests.append(payload)
        self.auth_headers.append(request.headers.get("authorization"))
        if not payload.get("stream") and self.fail_non_streaming:
            return httpx.Response(self.fail_non_streaming, text="non-streaming failure")
        if not payload.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"content": self.title}}]})
        step = self.script.pop(0) if self.script else {"content": "(script exhausted)"}
        if "error" in step:
            return httpx.Response(step["error"], text=step.get("body", "upstream failure"))
        if "stream_error" in step:  # some providers report a failure inside an HTTP 200 stream
            return httpx.Response(200, content=(_sse({"error": step["stream_error"]}) + _sse("[DONE]")).encode(), headers={"content-type": "text/event-stream"})

        parts: list[str] = []
        content = step.get("content", "")
        if content:
            mid = max(1, len(content) // 2)
            for piece in (content[:mid], content[mid:]):
                if piece:
                    parts.append(_sse({"choices": [{"delta": {"content": piece}}]}))
        for i, (name, args) in enumerate(step.get("tool_calls", [])):
            self._n += 1
            raw = args if isinstance(args, str) else json.dumps(args)
            half = max(1, len(raw) // 2)  # split arguments across chunks like a real stream
            parts.append(_sse({"choices": [{"delta": {"tool_calls": [{"index": i, "id": f"call_{self._n}", "function": {"name": name, "arguments": raw[:half]}}]}}]}))
            parts.append(_sse({"choices": [{"delta": {"tool_calls": [{"index": i, "function": {"arguments": raw[half:]}}]}}]}))
        parts.append(_sse({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 42}}))
        parts.append(_sse("[DONE]"))
        return httpx.Response(200, content="".join(parts).encode(), headers={"content-type": "text/event-stream"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    # helpers for assertions
    def last_messages(self) -> list[dict[str, Any]]:
        streaming = [r for r in self.requests if r.get("stream")]
        return streaming[-1]["messages"]

    @property
    def streaming_calls(self) -> int:
        return len([r for r in self.requests if r.get("stream")])


class FakeBhashini:
    def __init__(self, transcript: str = "namaste", no_model_for: set[str] | None = None):
        self.transcript = transcript
        self.no_model_for = no_model_for or set()
        self.config_calls = 0
        self.compute_calls: list[dict[str, Any]] = []
        self.tts_texts: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        url = str(request.url)
        if url == BHASHINI_CONFIG_URL:
            assert request.headers["userID"] and request.headers["ulcaApiKey"]
            self.config_calls += 1
            task = body["pipelineTasks"][0]["taskType"]
            lang = body["pipelineTasks"][0]["config"]["language"]["sourceLanguage"]
            if lang in self.no_model_for:
                return httpx.Response(200, json={"pipelineResponseConfig": []})
            return httpx.Response(
                200,
                json={
                    "pipelineResponseConfig": [{"taskType": task, "config": [{"serviceId": f"svc-{task}-{lang}", "language": {"sourceLanguage": lang}}]}],
                    "pipelineInferenceAPIEndPoint": {"callbackUrl": BHASHINI_COMPUTE_URL, "inferenceApiKey": {"name": "Authorization", "value": "inference-token"}},
                },
            )
        if url == BHASHINI_COMPUTE_URL:
            assert request.headers["Authorization"] == "inference-token"
            self.compute_calls.append(body)
            task = body["pipelineTasks"][0]["taskType"]
            if task == "asr":
                assert base64.b64decode(body["inputData"]["audio"][0]["audioContent"])[:4] == b"RIFF"
                return httpx.Response(200, json={"pipelineResponse": [{"taskType": "asr", "output": [{"source": self.transcript}]}]})
            if task == "tts":
                self.tts_texts.append(body["inputData"]["input"][0]["source"])
                audio = base64.b64encode(make_float_wav(0.1, 8000)).decode()  # like the real service: float32, not PCM16
                return httpx.Response(200, json={"pipelineResponse": [{"taskType": "tts", "audio": [{"audioContent": audio}]}]})
        return httpx.Response(404, text="unexpected url " + url)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


class FakeSarvam:
    """Sarvam speech API: records what was sent and answers like the documented API."""

    def __init__(self, transcript: str = "నాకు డాక్టర్ కావాలి", status: int | None = None, error_message: str | None = None):
        self.transcript = transcript
        self.status = status  # force an HTTP error status on every call
        self.error_message = error_message
        self.stt_calls: list[dict[str, Any]] = []
        self.tts_calls: list[dict[str, Any]] = []

    @staticmethod
    def _form(request: httpx.Request) -> dict[str, str]:
        import re

        raw = request.content.decode("latin-1")
        return {m.group(1): m.group(2) for m in re.finditer(r'name="(\w+)"\r\n\r\n(.*?)\r\n--', raw, re.S)}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert request.headers.get("api-subscription-key"), "Sarvam needs the api-subscription-key header"
        if self.status:
            body = {"error": {"message": self.error_message or "boom", "code": "x"}}
            return httpx.Response(self.status, json=body)
        if url == SARVAM_STT_URL:
            assert request.headers["content-type"].startswith("multipart/form-data")
            fields = self._form(request)
            assert b"RIFF" in request.content, "the WAV file must be uploaded in the `file` part"
            self.stt_calls.append(fields)
            return httpx.Response(200, json={"request_id": "r1", "transcript": self.transcript, "language_code": fields.get("language_code")})
        if url == SARVAM_TTS_URL:
            body = json.loads(request.content)
            self.tts_calls.append(body)
            return httpx.Response(200, json={"request_id": "r2", "audios": [base64.b64encode(make_wav(0.1, body["speech_sample_rate"])).decode()]})
        return httpx.Response(404, text="unexpected " + url)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class Recorder:
    """HTTP client for tools/webhooks: records every request and answers 200 (or a configured status)."""

    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": True})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def events(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.content]


OSM_ELEMENTS = [
    {"type": "node", "id": 1001, "lat": 16.3100, "lon": 80.4400, "tags": {
        "name": "Guntur General Hospital", "amenity": "hospital", "emergency": "yes", "phone": "+91 863 2222222; +91 98480 12345",
        "addr:street": "Brodipet", "addr:city": "Guntur", "website": "gghguntur.example.org"}},
    {"type": "way", "id": 2002, "center": {"lat": 16.3000, "lon": 80.4300}, "tags": {
        "name": "Sri Skin & Care Clinic", "amenity": "clinic", "healthcare:speciality": "dermatology", "opening_hours": "Mo-Sa 10:00-13:00",
        "phone": "08632111111"}},
    {"type": "node", "id": 3003, "lat": 16.3200, "lon": 80.4500, "tags": {"name": "Dr. Rao Family Clinic", "amenity": "doctors"}},
    {"type": "node", "id": 4004, "lat": 16.3300, "lon": 80.4600, "tags": {"amenity": "clinic"}},  # no name: must be skipped
    {"type": "node", "id": 5005, "lat": 16.2900, "lon": 80.4200, "tags": {"name": "Primary Health Centre Tenali Road", "amenity": "clinic"}},
]


class FakeOSM:
    """Stand-in for Nominatim (city -> coordinates) and Overpass (places around a point). Counts the calls it receives."""

    CITIES = {"guntur": {"lat": "16.3067", "lon": "80.4365", "display_name": "Guntur, Andhra Pradesh, India"}}

    @staticmethod
    def _row(el: dict) -> dict:
        """An OpenStreetMap element as Nominatim reports it (jsonv2 with addressdetails, extratags and namedetails)."""
        tags = dict(el.get("tags", {}))
        centre = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        address = {k: tags.pop(f"addr:{k}") for k in ("street", "city") if f"addr:{k}" in tags}
        if "street" in address:
            address["road"] = address.pop("street")
        name, amenity = tags.pop("name", None), tags.pop("amenity", None)
        row = {
            "osm_type": el["type"], "osm_id": el["id"], "lat": str(centre["lat"]), "lon": str(centre["lon"]), "category": "amenity", "type": amenity,
            "name": name or "", "namedetails": {"name": name} if name else {}, "extratags": tags, "address": address,
        }
        return row

    def __init__(self, elements: list[dict] | None = None, down: bool = False, overpass_down: bool = False):
        self.elements = OSM_ELEMENTS if elements is None else elements
        self.down = down
        self.overpass_down = overpass_down
        self.geocodes = 0
        self.lookups = 0
        self.place_searches = 0
        self.overpass_calls = 0
        self.queries: list[str] = []
        self.user_agents: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.user_agents.append(request.headers.get("user-agent", ""))
        url = str(request.url)
        if self.down:
            return httpx.Response(503, text="busy")
        if "nominatim" in url:
            params = request.url.params
            if url.split("?")[0].endswith("/lookup"):  # one object by id, e.g. osm_ids=N1001
                self.lookups += 1
                want = params.get("osm_ids", "")
                kinds = {"N": "node", "W": "way", "R": "relation"}
                rows = [self._row(e) for e in self.elements if want and kinds.get(want[0]) == e["type"] and str(e["id"]) == want[1:]]
                return httpx.Response(200, json=rows)
            if params.get("viewbox"):  # a place list: q is the OpenStreetMap amenity word (hospital / clinic / doctors)
                self.place_searches += 1
                self.queries.append(str(request.url))
                amenity = params.get("q", "")
                return httpx.Response(200, json=[self._row(e) for e in self.elements if e.get("tags", {}).get("amenity") == amenity])
            self.geocodes += 1
            q = params.get("q", "").strip().lower()
            hit = self.CITIES.get(q)
            return httpx.Response(200, json=[hit] if hit else [])
        if "overpass" in url:
            self.overpass_calls += 1
            if self.overpass_down:
                return httpx.Response(504, text="timeout")
            body = request.content.decode()
            self.queries.append(body)
            import re
            from urllib.parse import parse_qs

            query = parse_qs(body).get("data", [""])[0]
            one = re.search(r"(node|way|relation)\((\d+)\);out", query)  # a lookup of a single place by id
            if one and "around" not in query:
                found = [e for e in self.elements if e["type"] == one.group(1) and e["id"] == int(one.group(2))]
                return httpx.Response(200, json={"elements": found})
            return httpx.Response(200, json={"elements": self.elements})
        return httpx.Response(404, text="unexpected " + url)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def fake_tools_client() -> httpx.AsyncClient:
    """Default tools/webhook client: nothing is configured to be called, so any request is a test failure (404)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(404, text="unexpected " + str(req.url))))
