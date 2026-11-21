"""Live voice calls with Agora Conversational AI + Murf Falcon.

How it fits together
    browser <-- RTC audio --> Agora channel <--> Agora's cloud voice agent
    agent: speech-to-text (Agora ARES or Sarvam) -> LLM -> Murf Falcon text-to-speech

* mode "tools": the agent's LLM URL is THIS server (`/agora/llm/chat/completions`, OpenAI-compatible). Every spoken turn runs
  through the same assistant, tools and confirmation rules as the text chat, so it can find clinics, plan visits and so on.
  Needs AGORA_PUBLIC_URL, because Agora's cloud must be able to reach this server.
* mode "chat_only": without a public URL the agent talks to the LLM provider directly. It can converse, not act.

This module builds the requests; it holds no state. Keys come from settings and are never logged or returned to the browser
(only the short-lived RTC token for the caller's own channel is).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from agora_agent.agentkit.token import generate_client_token, generate_convo_ai_token

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, Unauthorized, UpstreamError

log = logging.getLogger("app.agora")


@dataclass(frozen=True)
class CallLanguage:
    code: str
    name: str
    native_name: str
    locale: str  # BCP-47 tag used by both speech-to-text and Murf
    voice: str  # default Murf Falcon 2.1 voice that lists this locale (override with MURF_VOICES)
    greeting: str
    failure: str
    confirm_ask: str


# Voices are taken from Murf's Falcon 2.1 voice table (each is listed for its locale). Murf does not list Odia, Assamese or
# Urdu for Falcon, so those languages are not offered for live calls.
LANGUAGES: dict[str, CallLanguage] = {l.code: l for l in [
    CallLanguage("en", "English", "English", "en-IN", "Priya",
                 "Hello, I'm Swasthya Saathi. How can I help you with your health today?",
                 "Sorry, I had trouble with that. Please say it again.",
                 "Please say yes to confirm, or no to cancel."),
    CallLanguage("hi", "Hindi", "हिन्दी", "hi-IN", "Ayushi",
                 "नमस्ते, मैं स्वास्थ्य साथी हूँ। आज मैं आपकी सेहत में कैसे मदद कर सकती हूँ?",
                 "माफ़ कीजिए, कुछ गड़बड़ हुई। कृपया दोबारा बोलिए।",
                 "पुष्टि के लिए हाँ कहिए, या रद्द करने के लिए नहीं कहिए।"),
    CallLanguage("te", "Telugu", "తెలుగు", "te-IN", "Anisha",
                 "నమస్కారం, నేను స్వాస్థ్య సాథీని. ఈ రోజు మీ ఆరోగ్యం విషయంలో నేను ఎలా సహాయం చేయగలను?",
                 "క్షమించండి, ఏదో సమస్య వచ్చింది. దయచేసి మళ్ళీ చెప్పండి.",
                 "నిర్ధారించడానికి అవును అని చెప్పండి, రద్దు చేయడానికి కాదు అని చెప్పండి."),
    CallLanguage("ta", "Tamil", "தமிழ்", "ta-IN", "Anisha",
                 "வணக்கம், நான் ஸ்வாஸ்த்ய சாத்தி. இன்று உங்கள் உடல்நலத்தில் நான் எப்படி உதவலாம்?",
                 "மன்னிக்கவும், ஒரு சிக்கல் ஏற்பட்டது. தயவுசெய்து மீண்டும் சொல்லுங்கள்.",
                 "உறுதிப்படுத்த ஆமாம் என்றும், ரத்து செய்ய இல்லை என்றும் சொல்லுங்கள்."),
    CallLanguage("kn", "Kannada", "ಕನ್ನಡ", "kn-IN", "Harshitha",
                 "ನಮಸ್ಕಾರ, ನಾನು ಸ್ವಾಸ್ಥ್ಯ ಸಾಥಿ. ಇಂದು ನಿಮ್ಮ ಆರೋಗ್ಯದ ಬಗ್ಗೆ ನಾನು ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?",
                 "ಕ್ಷಮಿಸಿ, ಏನೋ ತೊಂದರೆಯಾಯಿತು. ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ.",
                 "ದೃಢೀಕರಿಸಲು ಹೌದು ಎಂದು, ರದ್ದುಮಾಡಲು ಇಲ್ಲ ಎಂದು ಹೇಳಿ."),
    CallLanguage("ml", "Malayalam", "മലയാളം", "ml-IN", "Nimisha",
                 "നമസ്കാരം, ഞാൻ സ്വാസ്ഥ്യ സാഥി. ഇന്ന് നിങ്ങളുടെ ആരോഗ്യത്തിൽ ഞാൻ എങ്ങനെ സഹായിക്കാം?",
                 "ക്ഷമിക്കണം, എന്തോ പ്രശ്നം ഉണ്ടായി. ദയവായി ഒന്നുകൂടി പറയൂ.",
                 "സ്ഥിരീകരിക്കാൻ അതെ എന്നും, റദ്ദാക്കാൻ ഇല്ല എന്നും പറയൂ."),
    CallLanguage("bn", "Bengali", "বাংলা", "bn-IN", "Debarati",
                 "নমস্কার, আমি স্বাস্থ্য সাথী। আজ আপনার স্বাস্থ্যের ব্যাপারে আমি কীভাবে সাহায্য করতে পারি?",
                 "দুঃখিত, কিছু সমস্যা হয়েছে। অনুগ্রহ করে আবার বলুন।",
                 "নিশ্চিত করতে হ্যাঁ বলুন, বাতিল করতে না বলুন।"),
    CallLanguage("mr", "Marathi", "मराठी", "mr-IN", "Prajakta",
                 "नमस्कार, मी स्वास्थ्य साथी आहे. आज तुमच्या आरोग्यासाठी मी कशी मदत करू शकते?",
                 "माफ करा, काहीतरी अडचण आली. कृपया पुन्हा सांगा.",
                 "पुष्टी करण्यासाठी हो म्हणा, रद्द करण्यासाठी नाही म्हणा."),
    CallLanguage("gu", "Gujarati", "ગુજરાતી", "gu-IN", "Diya",
                 "નમસ્તે, હું સ્વાસ્થ્ય સાથી છું. આજે તમારા સ્વાસ્થ્ય માટે હું કેવી રીતે મદદ કરી શકું?",
                 "માફ કરશો, કંઈક સમસ્યા થઈ. કૃપા કરીને ફરી કહો.",
                 "પુષ્ટિ માટે હા કહો, રદ કરવા માટે ના કહો."),
    CallLanguage("pa", "Punjabi", "ਪੰਜਾਬੀ", "pa-IN", "Harman",
                 "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਸਵਾਸਥ ਸਾਥੀ ਹਾਂ। ਅੱਜ ਮੈਂ ਤੁਹਾਡੀ ਸਿਹਤ ਵਿੱਚ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦੀ ਹਾਂ?",
                 "ਮਾਫ਼ ਕਰਨਾ, ਕੋਈ ਸਮੱਸਿਆ ਆਈ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕਹੋ।",
                 "ਪੁਸ਼ਟੀ ਲਈ ਹਾਂ ਕਹੋ, ਰੱਦ ਕਰਨ ਲਈ ਨਹੀਂ ਕਹੋ।"),
]}


# Words Agora's recogniser (ARES) should favour. Place names matter most: a mis-heard city means "no clinics found".
# (ARES accepts at most 128 keywords; Sarvam has no such list.)
ASR_KEYWORDS = [
    "Swasthya Saathi", "Guntur", "Tenali", "Vijayawada", "Visakhapatnam", "Tirupati", "Nellore", "Kurnool", "Kakinada", "Rajahmundry", "Ongole",
    "Hyderabad", "Warangal", "Karimnagar", "Nizamabad", "Khammam", "Secunderabad", "Bengaluru", "Bangalore", "Mysuru", "Mysore", "Mangaluru", "Hubballi",
    "Belagavi", "Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tirunelveli", "Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur",
    "Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad", "Delhi", "Gurugram", "Noida", "Ghaziabad", "Lucknow", "Kanpur", "Varanasi", "Agra", "Jaipur",
    "Jodhpur", "Udaipur", "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Kolkata", "Howrah", "Bhubaneswar", "Cuttack", "Patna", "Ranchi", "Guwahati",
    "Chandigarh", "Ludhiana", "Amritsar", "Bhopal", "Indore", "Raipur", "Dehradun", "Shimla", "Panaji", "Ayushman Bharat", "ABHA", "dermatologist",
    "pediatrician", "gynecologist", "cardiologist", "orthopedic", "ophthalmologist", "dentist", "paracetamol",
]


def language_for(settings: Settings, code: str | None) -> CallLanguage:
    from app.core.errors import BadRequest

    code = (code or "en").strip().lower()
    if code not in LANGUAGES:
        raise BadRequest(f"Live calls support: {', '.join(LANGUAGES)}. '{code}' is not available yet.", code="unsupported_language")
    return LANGUAGES[code]


def voice_for(settings: Settings, lang: CallLanguage) -> str:
    overrides = json.loads(settings.murf_voices) if settings.murf_voices.strip() else {}
    return overrides.get(lang.code) or lang.voice


# ------------------------------------------------------------------------------------------ the token Agora's cloud uses to call us
def _llm_key(settings: Settings) -> bytes:
    # Derived from the JWT secret but different from it, so this token can never be used as a normal login token.
    return hashlib.sha256((settings.jwt_secret + "|agora-llm").encode()).digest()


def make_llm_token(settings: Settings, *, user_id: str, conversation_id: str, language: str) -> str:
    now = int(time.time())
    payload = {"typ": "agora_llm", "sub": user_id, "cid": conversation_id, "lang": language, "iat": now, "exp": now + settings.agora_session_minutes * 60 + 900}
    return jwt.encode(payload, _llm_key(settings), algorithm="HS256")


def read_llm_token(settings: Settings, token: str | None) -> dict[str, str]:
    try:
        payload = jwt.decode(token or "", _llm_key(settings), algorithms=["HS256"])
        if payload.get("typ") != "agora_llm":
            raise jwt.InvalidTokenError("wrong token type")
        return {"user_id": payload["sub"], "conversation_id": payload["cid"], "language": payload["lang"]}
    except (jwt.PyJWTError, KeyError) as exc:
        raise Unauthorized("Invalid or expired call token") from exc


# ------------------------------------------------------------------------------------------ the REST client
class AgoraService:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.s, self.http = settings, http

    def _require(self) -> None:
        if not self.s.agora_configured:
            raise ServiceUnavailable("Live calls need AGORA_APP_ID and AGORA_APP_CERTIFICATE in backend/.env.", code="agora_not_configured")
        if not self.s.murf_configured:
            raise ServiceUnavailable("Live calls need MURF_API_KEY in backend/.env (Murf Falcon speaks the replies).", code="murf_not_configured")

    # ---- tokens
    def client_token(self, channel: str, uid: int) -> str:
        """For the caller's browser: join this channel as a speaker (RTC)."""
        return generate_client_token(self.s.agora_app_id, self.s.agora_app_certificate, channel, uid, token_expire=self.s.agora_session_minutes * 60 + 60)

    def agent_token(self, channel: str, uid: int) -> str:
        """For the cloud agent (RTC + ConvoAI); also authenticates the REST calls."""
        secs = self.s.agora_session_minutes * 60 + 600
        return generate_convo_ai_token(self.s.agora_app_id, self.s.agora_app_certificate, channel, uid, token_expire=secs, privilege_expire=secs)

    def _auth(self, token: str) -> dict[str, str]:
        if self.s.agora_customer_id and self.s.agora_customer_secret:
            import base64

            raw = base64.b64encode(f"{self.s.agora_customer_id}:{self.s.agora_customer_secret}".encode()).decode()
            return {"Authorization": f"Basic {raw}"}
        return {"Authorization": f"agora token={token}"}

    # ---- the agent configuration
    def build_join_body(
        self, *, lang: CallLanguage, channel: str, agent_uid: int, user_uid: int, token: str, llm: dict[str, Any], name: str,
    ) -> dict[str, Any]:
        if self.s.agora_asr_vendor == "sarvam" and self.s.sarvam_api_key:
            asr: dict[str, Any] = {"vendor": "sarvam", "language": lang.locale, "params": {"api_key": self.s.sarvam_api_key, "language": lang.locale}}
        else:  # ARES takes a comma separated list: the chosen language plus Indian English (people mix them)
            asr = {"vendor": "ares", "language": lang.locale if lang.code == "en" else f"{lang.locale},en-IN", "keywords": ASR_KEYWORDS[:128]}
        return {
            "name": name,
            "properties": {
                "channel": channel,
                "token": token,
                "agent_rtc_uid": str(agent_uid),
                "remote_rtc_uids": [str(user_uid)],
                "enable_string_uid": False,
                "idle_timeout": self.s.agora_idle_timeout_seconds,
                "asr": asr,
                "llm": llm,
                "tts": {
                    "vendor": "murf",
                    "params": {
                        "api_key": self.s.murf_api_key, "base_url": self.s.murf_ws_url, "voiceId": voice_for(self.s, lang), "locale": lang.locale,
                        "model": self.s.murf_model, "sample_rate": self.s.murf_sample_rate,
                    },
                },
            },
        }

    def llm_config(self, *, lang: CallLanguage, system_prompt: str, session_token: str) -> tuple[dict[str, Any], str]:
        """(llm block, mode). With a public URL Agora calls this server; otherwise it calls the LLM provider directly."""
        common = {"style": "openai", "vendor": "custom", "greeting_message": lang.greeting, "failure_message": lang.failure, "input_modalities": ["text"], "output_modalities": ["text"]}
        if self.s.agora_public_url:
            url = self.s.agora_public_url.rstrip("/") + f"{self.s.api_prefix}/agora/llm/chat/completions"
            return {**common, "url": url, "api_key": session_token, "max_history": 10, "params": {"model": "swasthya-saathi"}}, "tools"
        extra = json.loads(self.s.llm_extra_body) if self.s.llm_extra_body.strip() else {}
        params = {"model": self.s.llm_model, "max_tokens": 300, **extra}
        return {
            **common, "url": self.s.llm_base_url.rstrip("/") + "/chat/completions", "api_key": self.s.llm_api_key, "max_history": 20, "params": params,
            "system_messages": [{"role": "system", "content": system_prompt}],
        }, "chat_only"

    # ---- REST
    def _fail(self, resp: httpx.Response, what: str) -> UpstreamError:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        detail = str(body.get("detail") or body.get("message") or "")[:300]
        reason = str(body.get("reason") or "")[:60]
        log.warning("Agora %s failed: HTTP %s %s %s", what, resp.status_code, reason, detail)  # never the request: it holds keys
        if resp.status_code in (401, 403):
            return UpstreamError("Agora rejected the credentials. Check AGORA_APP_ID and AGORA_APP_CERTIFICATE (and that Conversational AI is enabled for the project).", code="agora_auth_failed")
        if resp.status_code == 429:
            return UpstreamError("Agora is rate limiting calls. Please wait a few seconds and try again.", retryable=True, code="agora_error")
        text = f"Agora could not start the call (HTTP {resp.status_code}{', ' + reason if reason else ''}){': ' + detail if detail else ''}"
        return UpstreamError(text, retryable=resp.status_code >= 500, code="agora_error")

    async def start(self, body: dict[str, Any], token: str) -> dict[str, Any]:
        self._require()
        url = f"{self.s.agora_api_base.rstrip('/')}/v2/projects/{self.s.agora_app_id}/join"
        try:
            resp = await self.http.post(url, json=body, headers={**self._auth(token), "Content-Type": "application/json"}, timeout=30)
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach Agora. Check the internet connection and try again.", retryable=True, code="agora_unreachable") from exc
        if resp.status_code != 200:
            raise self._fail(resp, "join")
        data = resp.json()
        if not data.get("agent_id"):
            raise UpstreamError("Agora answered without an agent id.", code="agora_error")
        return data

    async def stop(self, agent_id: str, token: str) -> None:
        url = f"{self.s.agora_api_base.rstrip('/')}/v2/projects/{self.s.agora_app_id}/agents/{agent_id}/leave"
        try:
            resp = await self.http.post(url, headers=self._auth(token), timeout=20)
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach Agora to end the call (it will end by itself when you are idle).", retryable=True, code="agora_unreachable") from exc
        if resp.status_code not in (200, 404):  # 404 = the agent already left
            raise self._fail(resp, "leave")


def new_call_ids() -> tuple[str, int, int]:
    """(channel name, caller uid, agent uid): numeric uids, as the Agora token helpers require."""
    channel = "ss-" + secrets.token_hex(8)
    user_uid = 1000 + secrets.randbelow(2_000_000_000)
    return channel, user_uid, user_uid + 1
