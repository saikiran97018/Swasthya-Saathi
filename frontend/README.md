# Swasthya Saathi: web app

React 18 + TypeScript + Vite + Tailwind. It talks to the FastAPI backend over REST and one WebSocket. See the [root README](../README.md) for the whole project and [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for how the pieces fit.

```powershell
npm install
npm run dev          # http://localhost:5173  (proxies /api, including the WebSocket, to 127.0.0.1:8000)
npm test             # unit tests (vitest)
npm run typecheck    # strict TypeScript, no emit
npm run build        # production bundle in dist/
```

`VITE_API_BASE` is only needed when the backend is on another origin (the app uses relative `/api/v1/...` URLs).

## Screens

| Route | Screen |
|---|---|
| `/` | Home (landing page): what the app does, language chips, feature cards, how it works, upcoming visit, urgent-help card and quick access on the side. The symptom intake box was removed: symptoms are checked in AI Consult |
| `/chat`, `/chat/:id` | AI Consult: streaming chat with tool cards; an emergency result links to `/sos` |
| `/find-care` | Doctors: real hospitals, clinics and doctors from `GET /places/search` (OpenStreetMap, by city or "Use my location"). Partner clinics with online slots are booked (`provider_code`); every other place is a planned visit (`place_id`, not confirmed by the clinic) |
| `/appointments` | Care Plan: next visit, upcoming / past, "Planned - call to confirm" vs "Confirmed", checklist from `/tasks`, follow-ups, feedback stars |
| `/sos` | Emergency help (opened by the red SOS button in every header): Call 112 / 108, share location (`sms:` links, Web Share, copy), emergency contacts, nearest care, first aid, helplines. Works offline from a bundled copy and the last cached answer |
| `/family` | Family profiles (max 8); pick "Booking for" in the booking sheet |
| `/call` | Live call (More menu; also buttons on Home and in the chat header): real-time voice agent over Agora Conversational AI with Murf Falcon speech. `agora-rtc-sdk-ng` is lazy-loaded when a call starts; the transcript polls `/conversations/{id}` every 1.5 s and reuses the chat message and confirm cards. Logic lives in `lib/callState.ts` + `lib/callSession.ts` (tested); `lib/agoraCall.ts` is the only file that touches the SDK |
| `/history`, `/activity`, `/settings`, `/settings/language` | More screens (sidebar "More" and the mobile menu). `/voice` redirects to `/call` |

The header always has one red **SOS** button. There is no other emergency control (the "Need urgent help?" card and emergency chat results link to `/sos`). Nothing dials, texts or shares by itself: only `tel:`, `sms:` and share links the person taps. Map data is shown with the attribution "Map data © OpenStreetMap contributors"; fees, ratings and availability are never shown for map places.

## How the code is organised (`src/`)

| Folder | What lives there |
|---|---|
| `pages/` | One file per screen |
| `components/` | `chat` (bubbles, `ToolCard`, `ToolResults` rich views for urgency, providers, slots, booking), `voice` (orb, waveform), `health` (appointment card, notification bell and watcher), `layout`, `ui` |
| `hooks/` | `ChatProvider` (one conversation state shared by Chat and Voice), `useSpeech`, `useDictation`, theme and language providers |
| `lib/chatReducer.ts` | The heart of the chat: turns the server's event stream (`token`, `message`, `tool_start`, `tool_result`, `confirmation_required`, `done`, …) into UI state. Pure and unit-tested |
| `lib/chatSocket.ts` | WebSocket client: reconnect with back-off, 25 s ping, REST fallback when the socket cannot connect |
| `lib/recorder.ts`, `vad.ts`, `wav.ts` | Microphone capture (AudioWorklet), silence detection, 16 kHz mono WAV encoding |
| `lib/speechStreamer.ts`, `speechPlayer.ts`, `ttsCache.ts`, `sentences.ts` | Speak the answer sentence by sentence while it is still streaming; playback queue; replay cache |
| `lib/time.ts` | All times shown in IST (`Asia/Kolkata`) |
| `api/` | Typed client (guest sign-in on first load, retry once on 401), endpoint functions mirroring the backend schemas, react-query hooks |

## Things to know

- Live call without Agora keys (dev only): in `npm run dev` the call hook uses `window.__fakeCallTransport(handlers)` if defined (an object with `prepareMic/join/setMuted/leave`), so the UI can be driven with a mocked `fetch`. It is compiled out of production builds.

- **Microphone**: browsers allow it only on `localhost` or HTTPS, and only after permission. Typing always works.
- **Recording length** follows the server: `GET /health` returns `max_audio_seconds` (30 with Sarvam), and the recorder stops 2 s earlier.
- **Languages** the app can *speak* depend on the active speech provider (`GET /languages` flags `tts` per language); other languages are answered in text.
- **Auth**: a guest account is created on first load and stored in `localStorage`; there is no login screen yet (the API supports register / login / upgrade).
