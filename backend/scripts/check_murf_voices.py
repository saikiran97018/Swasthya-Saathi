"""Check that every live-call voice really speaks its language with YOUR Murf key (uses a little of your Murf quota).

    .\\.venv\\Scripts\\python.exe scripts\\check_murf_voices.py

Reads backend/.env (MURF_API_KEY, MURF_MODEL, MURF_VOICES). Prints one line per language; use it after changing MURF_VOICES.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.agora import LANGUAGES, voice_for  # noqa: E402


def main() -> int:
    s = get_settings()
    sys.stdout.reconfigure(encoding="utf-8")
    if not s.murf_api_key:
        print("MURF_API_KEY is empty in backend/.env")
        return 2
    bad = 0
    for code, lang in LANGUAGES.items():
        voice, started = voice_for(s, lang), time.time()
        r = httpx.post(
            "https://global.api.murf.ai/v1/speech/stream", headers={"api-key": s.murf_api_key}, timeout=60,
            json={"text": lang.greeting, "voiceId": voice, "model": s.murf_model, "locale": lang.locale, "format": "MP3", "sampleRate": s.murf_sample_rate},
        )
        ok = r.status_code == 200 and len(r.content) > 5000
        bad += not ok
        print(f"{code:3} {voice:12} {lang.locale}: " + (f"OK {len(r.content)} bytes in {time.time() - started:.1f}s" if ok else f"FAILED HTTP {r.status_code} {r.text[:160]}"))
    print("all voices OK" if not bad else f"{bad} voice(s) need a different MURF_VOICES entry (see GET https://api.murf.ai/v1/speech/voices?model=FALCON)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
