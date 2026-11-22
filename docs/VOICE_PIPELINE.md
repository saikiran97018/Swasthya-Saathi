# Voice agent pipeline

Every spoken turn, on the live call and on the dictation button, follows the same six stages.

```
User speaks (Telugu / Hindi / English / regional accents)
  1. Speech-to-Text            Sarvam Saaras (dictation; language auto-detected, English words kept in English); Agora ARES with a keyword list (live call)
  2. Transcript validation     drop silence, filler sounds and invented captions; collapse recogniser loops
  3. Context and intent        intent rules + one short model call; working memory; upcoming visits; earlier city
  4. LLM + RAG + tool calling  verified knowledge notes in the prompt; 19 tools; confirm before book / cancel / submit
  5. Response validation       facts, safety, language and speakability are checked; one rewrite, else a safe fallback
  6. Text-to-Speech            Murf Falcon (live call), Bhashini or Sarvam (spoken replies in the app)
```

| Stage | Code | What it guarantees |
|---|---|---|
| 1 STT | `services/sarvam_service.py`, `services/agora.py` (ARES keywords). `bhashini_service.py` and `speech_failover.py` stay in the code but are switched off in `.env` / `render.yaml` | Sarvam recognises the language itself (`SARVAM_STT_AUTODETECT`) and keeps English words such as a city or "doctor" in English letters (`SARVAM_STT_MODE=codemix`), so a Hindi speaker with Telugu selected is still understood |
| 2 Transcript validation | `utils/transcript.py`; used by `api/routes/voice.py`, `services/agent_service.py`, `api/routes/agora.py` | Nobody acts on "Thanks for watching", `[music]`, "hmm", or the same phrase repeated ten times. Real one-word answers ("yes", "haan") pass |
| 3 Context and intent | `services/intent.py`, `services/working_memory.py`, `services/rag.py` (`person_context`) | An emergency is flagged in code and "call 112 first" goes at the top of the prompt. "Book the second one" works because the clinics just listed are remembered. A city from an earlier chat is offered, to be confirmed |
| 4 LLM + RAG + tools | `agents/orchestrator.py`, `agents/tools.py`, `services/rag.py`, `database/repositories/knowledge.py` | Health and scheme answers come from verified notes; tools do the actions; the user confirms anything that changes a booking |
| 5 Response validation | `services/response_validator.py`, `_check_reply` in the orchestrator | See below |
| 6 TTS | `services/speech_service.py`, Murf via Agora | Spoken replies are held back until stage 5 passes, so an unchecked sentence is never spoken |

## Stage 5 in detail

A reply is compared with what the assistant had that turn: its instructions, the knowledge notes, the tool results and what the person said.

| Check | Problem found | Action |
|---|---|---|
| Phone numbers, amounts (Rs), appointment references that appear nowhere in that material | invented fact | rewrite, else fallback |
| Medicine doses ("500 mg", "two tablets"), medicine names not in a verified note | unsafe advice | rewrite, else fallback |
| "You have dengue" style diagnoses | diagnosis | rewrite, else fallback |
| Tool names or instructions in the reply | leak | rewrite, else fallback |
| A long reply in the wrong script (for example English to a Telugu speaker) | wrong language | rewrite, else fallback |
| Empty reply | nothing to say | rewrite, else fallback |
| A reply in another writing system than the person's language (English asked, Telugu answered), or a word that mixes two scripts | wrong language / garbled | rewrite, else fallback |
| Emergency intent and the reply does not name 112 or 108 | missing safety line | the localized line is added |
| Markdown, links, emoji, very long text (voice) | not speakable | cleaned or cut at a sentence |

The rewrite is ONE extra model call that tells the model what was wrong. If that draft fails too, the person hears a short localized fallback ("I am not fully sure about that... ask a doctor, or call 104"). In an emergency the 112 line comes first. The result is stored on the message (`meta.validation`) for review.

Settings: `RESPONSE_VALIDATION_ENABLED` (default true), `RESPONSE_VALIDATION_RETRY` (default true).

## Reply language

The model tends to carry on in the language of a long chat. Every turn ends its context with "Reply in <the person's current language> in its native script, even if earlier messages used another language", and stage 5 rejects a reply in the wrong script.

## Speech providers

Sarvam is the only speech provider (STT Saaras, TTS Bulbul); the live call uses Agora ARES and Murf Falcon. Bhashini is commented out: its keys are commented in `backend/.env` and `render.yaml`, and `SPEECH_PROVIDER=sarvam`, `SPEECH_FALLBACK_PROVIDER=none`. To bring it back, set `SPEECH_PROVIDER=bhashini` (and the fallback as you like) and restore the two keys.

## Cost

Rules decide most intents for free. The model is called extra only when: the message is in another script or unclear (one short intent call, which also returns the knowledge-base query), or a reply fails validation (one rewrite). A clean reply costs nothing extra.

## Known limits

- Typed replies stream live, so a problem is fixed in the final message, not in the words already shown.
- The fact check can only compare numbers, amounts and references. It cannot judge whether a general health statement is medically right; that depends on the knowledge notes and the model.
- Fallback sentences exist for the ten live-call languages. Other languages get English.
