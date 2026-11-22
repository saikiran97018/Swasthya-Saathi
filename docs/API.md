# API reference

Base URL: `http://localhost:8000/api/v1` · Interactive docs (Swagger): `http://localhost:8000/docs`

All endpoints except `/health`, `/languages` and `/auth/guest|register|login` need `Authorization: Bearer <JWT>`.

## Conventions

**Errors** always have this shape:

```json
{ "error": { "code": "conversation_not_found", "message": "Conversation not found", "details": null } }
```

| Status | Meaning | Example codes |
|---|---|---|
| 400 | Bad input / business rule | `bad_request`, `no_speech`, `language_not_supported`, `not_awaiting_confirmation`, `not_active`, `invalid_specialty`; booking rules: `invalid_mobile`, `invalid_slot`, `slot_taken`, `slot_in_past`, `slot_too_far`, `too_many_appointments`, `user_conflict`, `no_teleconsultation`; feedback: `too_early`, `already_rated` |
| 401 | Missing/invalid token | `unauthorized`, `invalid_credentials` |
| 403 | Feature disabled | `demo_disabled` |
| 404 | Not found (also used for other users' data) | `conversation_not_found`, `appointment_not_found`, `provider_not_found`, `notification_not_found` |
| 409 | Conflict | `email_taken` |
| 413 | Audio too big / too long | `payload_too_large` |
| 415 | Audio not 16-bit mono WAV | `unsupported_media_type` |
| 422 | Validation failed (`details` lists fields) | `validation_error` |
| 429 | Rate limited (`Retry-After` header) | `rate_limited` |
| 502 | Speech / LLM provider failed | LLM: `llm_error`, `llm_auth_failed`, `llm_rate_limited`, `llm_no_credits`, `llm_timeout`, `llm_unreachable` · Sarvam: `sarvam_error`, `sarvam_auth_failed`, `sarvam_no_credits`, `sarvam_rate_limited`, `sarvam_timeout`, `sarvam_unreachable`, `sarvam_no_model` · Bhashini: `bhashini_error`, `bhashini_no_model`, `bhashini_timeout`, `bhashini_unreachable`. Each carries `retryable` on WebSocket `error` events |
| 503 | Dependency not configured | `llm_not_configured`, `sarvam_not_configured`, `bhashini_not_configured` |

**Languages** use ISO codes: `en hi te ta kn ml bn mr gu pa or as ur sa` (see `GET /languages`).
**Times:** stored and returned as UTC ISO-8601; clinics and slot lists are in **IST (Asia/Kolkata)**. Format with `timeZone: "Asia/Kolkata"`.

## Endpoints

### Health & reference
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `status`, `database`, `speech_provider` (`sarvam`\|`bhashini`), `speech_fallback_provider` (backup provider or `null`), `speech_configured`, `max_audio_seconds` (clients must stop recording before this: 30 with Sarvam, 60 with Bhashini), `bhashini_configured`, `sarvam_configured`, `llm_configured`, `llm_model`, `llm_fallback_model\|null`, `web_search_configured`, `demo_mode`, `version` |
| GET | `/languages` | Supported languages. `asr` / `tts` say whether the **active speech provider** can understand / speak each language (Sarvam: all understood, 11 spoken) |

### Auth
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/auth/guest` | `{display_name?}` | Instant account + JWT (used by the web app) |
| POST | `/auth/register` | `{email, password(≥8), display_name?}` | |
| POST | `/auth/login` | `{email, password}` | |
| POST | `/auth/upgrade` | `{email, password}` | Turns the current guest into a full account, keeping its data |
| GET / PATCH | `/auth/me` | `{display_name}` | |

Token responses: `{access_token, token_type, user:{id,email,display_name,is_guest,created_at}}`.

### Conversations
| Method | Path | Notes |
|---|---|---|
| GET | `/conversations?q=&limit=&offset=` | `q` searches titles **and** message text. Newest first. `{items,total,limit,offset}` |
| POST | `/conversations` | `{title?, language?}` (language defaults to the user's primary language) |
| GET | `/conversations/{id}` | Conversation + `messages[]` (tool runs are attached to the assistant message as `tool_executions`) |
| PATCH | `/conversations/{id}` | `{title}` rename |
| DELETE | `/conversations/{id}` | 204 |

`MessageOut`: `id, seq, role, content, language, input_mode (text|voice), source (user|ai|tool), tools_used[], tool_executions[], pending_confirmation, created_at`. `source = "tool"` means the answer used tools/data; `"ai"` a plain model answer.

### Chat (REST)
`POST /chat`
```json
{ "conversation_id": null, "message": "I have fever for 2 days", "input_mode": "text", "language": null, "voice_output": false, "regenerate": false }
```
* `conversation_id: null` creates a conversation. `language: null` keeps the conversation language (auto-detecting a script change when the user preference allows); a concrete code switches to it.
* `regenerate: true` (with `conversation_id`, no `message`) re-answers the last user message.
* Returns `{conversation, user_message, assistant_message, messages[], tool_executions[], pending_confirmation, language, execution_id}`.
  `tool_executions` is the latest state of every tool execution touched in the turn; after a confirm call it holds the outcome of the confirmed action. If `pending_confirmation` is set, a sensitive tool waits for the user.

### Voice
| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/family/{id}/vaccinations` | A child's vaccination schedule (India's UIP guide): each visit with its vaccines, due date and status `given`/`overdue`/`due`/`upcoming`. Needs the child's `birth_date`; people 17 or older have no schedule |
| PUT | `/family/{id}/vaccinations/{milestone}` | `{given_on: "YYYY-MM-DD" \| null}`: tick a visit as given (or remove the tick) and rebuild the reminders. Milestones: `birth, 6w, 10w, 14w, 9m, 16m, 5y, 10y, 16y` |
| POST | `/conversations/{id}/doctor-note` | `{text, source: assistant\|basic}`: a short note for the doctor from the patient's own words. A note that invents facts is replaced by a plain one |
| GET | `/places/search` | Places near a city or position from Google Maps (when `GOOGLE_MAPS_API_KEY` is set; `source: "google"`, with `rating`, `maps_url`) or OpenStreetMap (`source: "openstreetmap"`). `attribution` says which. Medical-shop searches widen the circle (to 15, then 25 km) when too few are found |
| GET | `/places/search?kind=pharmacy` | Medical shops near a city or position (OpenStreetMap); Jan Aushadhi Kendras carry the specialty `jan aushadhi`. No partner clinics are mixed in |
| GET / POST | `/medicine-reminders` | List / add a daily reminder: `{label, times:["08:00"], days}` (max 4 times a day, 180 days, 10 reminders per person) |
| DELETE | `/medicine-reminders/{series}` | Stop one reminder |
| PUT / DELETE | `/messages/{id}/feedback` | Thumbs up/down on one of your assistant replies: `{rating: up\|down, reason?: wrong_info\|unsafe\|misunderstood\|not_helpful\|other, note?}`; DELETE withdraws it |
| GET | `/billing/plans` | `multipart/form-data`: `audio` (**16-bit PCM mono WAV**, 8-48 kHz, ≤ `max_audio_seconds` from `/health` (30 s on Sarvam), ≤ 10 MB), `language` | `{text, language, duration_seconds}` |
| POST | `/voice/synthesize` | `{text, language, gender?}` | `audio/wav` (markdown/URLs stripped, long text chunked per sentence, cached) |

### Real places (hospitals and clinics near the user)
There is **no invented doctor data**. Places come from OpenStreetMap (Nominatim finds the city; the place list also comes from Nominatim, with optional Overpass via `OVERPASS_URL`). OpenStreetMap is volunteer-edited, so phone numbers and hours are often missing, and these places have no booking system: a visit is only *planned*.

| Method | Path | Notes |
|---|---|---|
| GET | `/places/search?city=&lat=&lon=&radius_km=8&kind=hospital\|clinic\|doctor&q=&specialty=&limit=30` | Send `city` OR `lat`+`lon`. `{center:{lat,lon,label}, items: PlaceOut[], attribution, note}`. `PlaceOut`: `id` (`osm:node/123`, or a partner clinic's provider code), `name, kind (hospital\|clinic\|doctor\|phc\|other), specialties[], address, city, phone, website, opening_hours, lat, lon, distance_km, emergency, source (openstreetmap\|partner), has_slots, provider_code`. Nearest first; cached for 6 hours. Errors: `location_required` (400), `place_not_found` (404), `places_unavailable` (502) |

**Planned visit.** `POST /appointments` accepts `place_id` (from the search) instead of `provider_code`; `slot_start` is any IST time `YYYY-MM-DD HH:MM` between 2 hours and 60 days ahead. The response has `clinic_confirmed: false` (the clinic has not agreed to that time; the user phones to confirm) and the reminders say so. Partner clinics with online slots still return `clinic_confirmed: true`, and only those take part in double-booking protection. Exactly one of `provider_code` / `place_id` must be sent (`422` otherwise).

### Family profiles, emergency contacts and SOS
| Method | Path | Notes |
|---|---|---|
| GET / POST | `/family` | `FamilyMember {id, name, relation (self\|spouse\|child\|parent\|sibling\|other), birth_year, gender, mobile, language, created_at}`. Max 8 (`409 family_limit`). Errors: `invalid_mobile`, `unsupported_language` |
| PATCH / DELETE | `/family/{id}` | Partial update (send `null` to clear an optional field). Deleting keeps past appointments (the person's name is stored on each) |
| | `POST /appointments` with `family_member_id` | Books for that person. Overlap checks are per person (a parent and a child can see different doctors at the same time). `AppointmentOut.family_member` = `{id, name, relation}` or `null`. The assistant also links a booking when the patient name matches a saved profile |
| GET / POST / DELETE | `/emergency-contacts` | `{id, name, phone, relation}`. Max 5 (`409 contact_limit`) |
| GET | `/sos?city=&lat=&lon=` | `{numbers[] (112, 108, 102, 181, 1098, 14416, 104), nearby[] (hospitals via OpenStreetMap, best effort), first_aid[] {id,title,steps[],call_if}, disclaimer}`. Numbers and first aid always come back, even if the map service is down. The server never calls or messages anyone; the phone does (tap-to-call, SMS link prepared in the browser) |

### Live voice calls (Agora Conversational AI + Murf Falcon)
| Method | Path | Notes |
|---|---|---|
| GET | `/agora/status` | `{configured, murf_configured, mode (tools\|chat_only\|unconfigured), languages[{code,name,native_name,voice}], note}` |
| POST | `/agora/session` | `{language?, conversation_id?}` -> `201 {app_id, channel, token, uid, agent_uid, agent_id, conversation_id, language, mode, expires_in, greeting, voice{vendor,voice_id,locale}}`. Starts the cloud voice agent and returns a short-lived RTC token for the browser (no secret is ever returned). Errors: `agora_not_configured` / `murf_not_configured` (503), `unsupported_language` (400), `agora_auth_failed` / `agora_error` / `agora_unreachable` (502) |
| POST | `/agora/session/{agent_id}/stop` | Hang up (`204`, idempotent, owner only) |
| POST | `/agora/llm/chat/completions` | **Called by Agora's cloud, not by browsers.** OpenAI-compatible SSE. Authenticated by a per-call token that is valid only here. Every spoken turn runs through the normal assistant (tools, safety rules); a spoken yes/no answers a pending confirmation |

Languages for calls: en, hi, te, ta, kn, ml, bn, mr, gu, pa (voices verified against Murf Falcon). Odia, Assamese and Urdu are not offered because Falcon lists no voice for them. `mode: tools` needs `AGORA_PUBLIC_URL` (a public HTTPS address Agora can reach); without it the agent talks to the LLM directly and cannot take actions.

### Providers & appointments
| Method | Path | Notes |
|---|---|---|
| GET | (partner clinics only: usually empty, see Real places above) `/providers?specialty=&city=&language=&teleconsultation=&accepts_ayushman=&limit=` | `ProviderOut[]` with `next_available:{date,time}\|null`. Specialties: `general medicine, pediatrics, gynecology, dermatology, cardiology, orthopedics, ophthalmology, ent, dentistry, psychiatry`. City aliases work (Bangalore → Bengaluru). `is_demo: true` marks sample listings. `rating_avg` / `rating_count` come only from real patient feedback (`null` / `0` until someone has rated that provider; never invented) |
| GET | `/providers/{code}/availability?from_date=YYYY-MM-DD&days=5` | `{provider, slot_minutes, open_slots:{"2026-11-23":["10:00","10:20"]}}` (IST, already excludes booked/too-soon slots) |
| POST | `/appointments` | **Book from the UI.** Body `{provider_code, slot_start, patient_name, patient_mobile, reason, mode?, language?}` where `slot_start` is the IST slot exactly as returned by availability (`"2026-11-23 10:20"`), `mode` is `in_person` (default) or `teleconsultation`, and `language` defaults to the user's primary language. Returns `201` + `AppointmentOut` (with the scheduled reminders). The patient's explicit Confirm tap after reviewing the details is the consent step; every rule is the one the agent's `book_appointment` tool uses (valid slot, 30-minute lead time, 14-day horizon, per-user limit, no overlap, **no double-booking**). Errors: `invalid_mobile`, `invalid_slot`, `slot_taken`, `slot_in_past`, `slot_too_far`, `too_many_appointments`, `user_conflict`, `no_teleconsultation` (400); `provider_not_found` (404) |
| POST | `/appointments/{id}/feedback` | `{rating 1-5, comment?}` after the visit time has passed (or the visit is completed); once per appointment. Returns the updated `AppointmentOut`. Errors: `too_early`, `already_rated`, `not_active` (400) |
| GET | `/appointments?scope=upcoming\|past\|all&limit=&offset=` | `AppointmentOut`: `id, ref, status (booked\|cancelled\|completed), mode, starts_at, ends_at, patient_name, patient_mobile (masked), reason, language, provider, reschedule_count, feedback_rating, feedback_comment, conversation_id, reminders[]` |
| GET | `/appointments/{id}` | |
| POST | `/appointments/{id}/cancel` | `{reason?}`: user-initiated from the UI (no extra confirmation step) |
| POST | `/appointments/{id}/complete` | **Demo helper**: pretend the visit happened (triggers the feedback request). `403 demo_disabled` unless `DEMO_MODE=true` |
| POST | `/appointments/{id}/remind-now` | **Demo helper**: deliver a reminder now. Same gating |

Booking can be done two ways: through the agent (conversation, then a confirmation card) or directly with `POST /appointments` from the Doctors screen after the patient confirms in the UI. Rescheduling and agent-initiated cancelling go through the agent; `POST /appointments/{id}/cancel` is the user's own Cancel button.

### Notifications (reminders)
| Method | Path | Notes |
|---|---|---|
| GET | `/notifications?unread_only=&limit=&offset=` | `{items, total, unread_count}`. `NotificationOut`: `id, kind (appointment_reminder\|follow_up\|feedback_request), title, message (translated when possible), language, appointment_ref, conversation_id, delivered_at, read_at`. Poll every ~20 s for the bell badge |
| POST | `/notifications/{id}/read` | |
| POST | `/notifications/read-all` | `{marked_read}` |

### Agents, tools, tasks, preferences, dashboard
| Method | Path | Notes |
|---|---|---|
| GET | `/agents` | Agent description + tool list (`requires_confirmation`, `enabled`, `category`) |
| GET | `/agents/executions?conversation_id=&limit=&offset=` | Run history: status, intent, latency, steps, `tool_executions[]` |
| POST | `/agents/executions/{tool_execution_id}/confirm` | `{approve: true\|false}` → same shape as `POST /chat` |
| GET | `/tasks?status=&kind=` · PATCH `/tasks/{id}` | To-dos (`T-…`) and assistance requests (`SR-…`, locked) |
| GET | `/billing/plans` | `{enabled, key_id, plans[], features[], free_daily_messages, free_daily_calls}` (Razorpay public key id only) |
| GET | `/billing/status` | `{plan: free\|plus, status, renews_at, cancel_at_cycle_end, messages_today/limit, calls_today/limit}` (limit null = unlimited) |
| POST | `/billing/subscribe` | `{plan: monthly\|yearly}` -> `{subscription_id, key_id}` to open Razorpay Checkout. 409 if already on Plus, 503 if payments are not set up |
| POST | `/billing/verify` | After checkout: `{razorpay_payment_id, razorpay_subscription_id, razorpay_signature}`. The signature is checked (HMAC-SHA256) before anything changes |
| POST | `/billing/cancel` | Stop renewing; Plus stays until the paid period ends |
| POST | `/billing/webhook` | Razorpay only: signed with `RAZORPAY_WEBHOOK_SECRET`, each event id applied once |
| GET | `/push/config` | `{available, public_key, devices}`: the key the browser subscribes with, and how many of your devices get notifications |
| POST / DELETE | `/push/subscriptions` | Register this phone/browser (`{endpoint, keys:{p256dh, auth}}`, max 10 per person) / forget it (`{endpoint}`) |
| POST | `/push/test` | Send a test notification to your devices: `{sent}` |
| GET / PUT | `/preferences` | theme, voice_output_enabled, auto_play_responses, auto_send_voice, sms_reminders (opt-in text reminders; read-only `sms_available` says whether the server can text), auto_detect_language, tts_gender, show_tool_details, silence_timeout_ms, primary_language, secondary_languages |
| GET | `/dashboard/summary` | counts, tool usage, recent conversations/runs, `upcoming_appointments[]`, `appointments_total`, `unread_notifications` |

`ToolExecutionOut`: `id, execution_id, assistant_message_id, tool_name, arguments, result, summary, explanation, status, requires_confirmation, duration_ms, error, created_at`; `status`: `running | success | error | awaiting_confirmation | denied | cancelled`.

## WebSocket: `/ws/chat?token=<JWT>`

One socket per browser tab. **One turn at a time**: after a command wait for `done`, `error` or `cancelled` (otherwise the server replies `error: busy`).

### Client → server
```json
{"type":"message","text":"…","conversation_id":null,"input_mode":"voice","language":null,"voice_output":true}
{"type":"regenerate","conversation_id":"…"}
{"type":"confirm","execution_id":"<tool_execution id>","approve":true}
{"type":"cancel"}
{"type":"ping"}
```

### Server → client events
| `type` | Payload | Meaning |
|---|---|---|
| `conversation` | `conversation` | Create/update (title, language, counters); also sent after the answer with the generated title |
| `language` | `language, changed` | Language used for this turn |
| `user_message` | `message` | The saved user message |
| `stage` | `stage: thinking｜tool｜responding` | Progress indicator |
| `token` | `delta` | Streamed answer text |
| `message` | `message` | A saved assistant message. **Upsert by `id`**; replaces the streaming buffer |
| `tool_start` / `tool_result` | `tool_execution` | A tool began / finished |
| `confirmation_required` | `tool_execution` (status `awaiting_confirmation`, readable `explanation`) | Show a confirm card, reply with `confirm` |
| `error` | `code, message, retryable` | Turn failed (user message kept; `regenerate` retries) |
| `cancelled` | – | Turn cancelled by `cancel` |
| `done` | `execution_id, status: completed｜awaiting_confirmation, language` | Turn finished |
| `pong` | – | Reply to `ping` |

Typical order: `conversation → language → user_message → stage → token… → message → conversation → done`. With tools: `… message(interim) → stage(tool) → tool_start → tool_result → message(interim + cards) → stage(thinking) → token… → message(final) → … → done`.

### Sensitive-action flow (confirmation)
1. The model asks for `book_appointment` (or cancel / reschedule / submit request). The server **does not run it**: it stores the call as `awaiting_confirmation`, emits `confirmation_required` with a readable sentence (*"Book an appointment at Demo Family Clinic, Guntur on Monday, 23 November 2026, 10:00 AM for Ravi…"*) and ends the turn with `done {status:"awaiting_confirmation"}`.
2. The user approves or declines in the UI.
3. Client sends `confirm` (WebSocket) or `POST /agents/executions/{id}/confirm` (REST). On approve the server re-validates everything (slot still free? number valid?) and runs the tool, then the model writes the final answer; on decline the model is told the user declined.
4. If the user sends a new message instead, the pending action is cancelled automatically.

## Agent tools

| Tool | Purpose | Confirmation |
|---|---|---|
| `assess_urgency` | Rule-based red-flag check → `emergency｜urgent｜routine` + suggested specialty (+ 112/108/Tele-MANAS numbers) | no |
| `find_healthcare_providers` | Search by specialty, city, doctor language, teleconsultation, Ayushman; returns codes, fee, next free slot (falls back to teleconsultation if the city has none) | no |
| `check_availability` | Open slots of one provider (IST) | no |
| `book_appointment` | Book a free slot; validates slot, mobile, lead time (≥30 min), horizon (14 days), per-user limit, overlaps; DB guard against double-booking; schedules reminders | **yes** |
| `list_appointments` | The user's appointments by scope | no |
| `reschedule_appointment` | Move to another free slot of the same provider; rebuilds reminders | **yes** |
| `cancel_appointment` | Cancel an upcoming appointment; reopens the slot, cancels reminders | **yes** |
| `schedule_follow_up` | Reminder on a future date (max 3 per appointment, ≤ 1 year) | no |
| `record_feedback` | Rating 1-5 + comment after the visit (once per appointment) | no |
| `search_knowledge_base` | RAG over the health knowledge base | no |
| `lookup_service_directory` | Helplines/portals (emergency, mental health, insurance, digital health) | no |
| `form_assistant` / `submit_service_request` | Step-by-step Ayushman card / ABHA ID callback request, validated; submit returns `SR-…` | submit: **yes** |
| `create_task` / `list_tasks` / `update_task_status` | Personal health to-dos (`T-…`) | no |
| `web_search` | Tavily or SearXNG; only offered when configured | no |
| `set_language` | Switch conversation language when asked | no |

The model can call **only** these tools: no SQL, shell or free-form HTTP. Arguments are validated by Pydantic models, every tool is scoped to the calling user, business rules live in services (not prompts), and tool output is treated as data, not instructions.

## Model providers

* **Speech:** `SPEECH_PROVIDER=auto|sarvam|bhashini`, plus `SPEECH_FALLBACK_PROVIDER=auto|sarvam|bhashini|none`: when the main provider raises an upstream error, the backup (if configured and it supports the language) is tried; silence is not treated as a failure. Bhashini audio is normalised to 16-bit PCM WAV. Sarvam uses `POST /speech-to-text` (Saaras v4) and `POST /text-to-speech` (Bulbul v3, explicit speaker per gender); language codes are mapped (`te` → `te-IN`, Odia `or` → `od-IN`).
* **LLM:** an ordered list of OpenAI-compatible targets: primary (`LLM_*`, e.g. Groq) then optional fallback (`LLM_FALLBACK_*`, e.g. Sarvam). A rate limit (429) fails over immediately; 5xx/timeouts get one retry first; failover only happens before any token was streamed. The model that actually answered is stored on the run (`agent_executions.model`) and the message metadata.

## Outbound webhook (`WEBHOOK_URL`)

`POST {"event": "...", "data": {...}, "sent_at": "..."}` with headers `X-Event` and `X-Signature` (hex HMAC-SHA256 of the raw body using `WEBHOOK_SECRET`). Events: `appointment.booked`, `appointment.cancelled`, `appointment.rescheduled`, `appointment.feedback`, `reminder.delivered`, `service_request.submitted`. Delivery failures never break the user's action.

