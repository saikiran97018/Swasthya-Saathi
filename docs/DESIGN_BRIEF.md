# Design brief for Stitch → Figma: Swasthya Saathi

A copy-paste brief for designing the app's UI in **Google Stitch** and moving it to **Figma**. It describes the screens that already exist in the working app (`frontend/`), so the design and the build stay in step.

## How to use it (3 steps)

1. In Stitch, create a new project. Paste **Section 1 (master prompt)** first and let it generate one screen so you can confirm the look.
2. Paste **one screen prompt from Section 3 at a time**. Generate **mobile first**, then ask Stitch for the desktop version of the same screen ("make a 1440 px desktop version of this screen"). Repeat for light and dark if you want both.
3. Export or copy the screens to Figma using Stitch's Figma option, then organise them using **Section 6 (Figma setup)**.

Tip: keep each prompt under about 150 words. If Stitch drifts from the style, re-paste the "Style rules" lines from the master prompt.

---

## 1. Master prompt (paste first)

```
Design a mobile-first web app called "Swasthya Saathi" ("health companion"): a multilingual, voice-first
healthcare assistant for people across India. A patient speaks or types in their own language (Telugu,
Hindi, Tamil, Kannada, Malayalam, Bengali, Marathi, Gujarati, Punjabi, Odia, English and more). The
assistant works out how urgent their problem is, finds suitable doctors, books the appointment after the
patient confirms, sends reminders, and asks for feedback after the visit.

Users: first-time smartphone users, elders, rural and urban patients, often on a phone, often unsure
about English. They may be anxious. The design must feel calm, trustworthy, warm and very simple.

Style rules:
- Calm medical-trust look, not cold hospital white and not a generic purple AI look.
- Primary: deep teal #0E7C7B. Dark surface: #0B3C40. Accent: saffron #F2A33A (use sparingly for
  attention and "needs your OK"). Emergency only: terracotta red #C8553D. Success: sage #4F8F6A.
  Light tint: #EDF5F3. Text: #10282B (light mode) / #EDF5F3 (dark mode).
- Rounded corners (14 px cards, full pills for chips), soft shadows, generous spacing, large touch
  targets (min 48 px), body text at least 16 px, never tiny grey text.
- Typeface: Inter for Latin text, Noto Sans for Indic scripts (Telugu, Devanagari, Tamil, Kannada,
  Malayalam, Bengali, Gujarati, Gurmukhi, Odia). Icons: simple rounded line icons (Lucide style).
- Always show native language names (తెలుగు, हिन्दी, தமிழ், ಕನ್ನಡ, മലയാളം, বাংলা).
- A persistent red "Emergency? 112 / 108" button must be reachable on every screen.
- Times are Indian Standard Time, shown like "Sat, 21 Nov 2026, 10:00 am IST".
- Provide both light and dark themes. Avoid stock photos; use clean illustrations and icons only.
- Plain, friendly wording. No medical jargon. Nothing should look like it can book without asking.
```

---

## 2. Design system (give this to Figma as variables/styles)

| Token | Light | Dark |
|---|---|---|
| Background | `#FFFFFF` | `#0A1F21` |
| Surface (cards) | `#EDF5F3` | `#10373A` |
| Primary | `#0E7C7B` | `#2BB5B3` |
| Deep (headers, dark panels) | `#0B3C40` | `#0B3C40` |
| Accent (attention, "needs your OK") | `#F2A33A` | `#F2A33A` |
| Emergency | `#C8553D` | `#E0745C` |
| Success | `#4F8F6A` | `#6FBF8F` |
| Info / external | `#3B6EA8` | `#6FA0D8` |
| Text | `#10282B` | `#EDF5F3` |
| Muted text | `#5B7274` | `#9DB6B3` |
| Border | `#C9DAD6` | `#24504F` |

| | Spec |
|---|---|
| Type scale | Display 32/40, Title 24/32, Heading 20/28, Body 16/24, Label 14/20, Caption 12/16 (captions only for secondary info) |
| Radius | 14 (cards), 12 (inputs, buttons), 999 (chips, pills) |
| Spacing | 4-pt grid: 4, 8, 12, 16, 24, 32 |
| Elevation | Card: soft 0 2 10 at 14% of `#0B3C40`; Modal: 0 8 30 at 22% |
| Touch target | min 48 × 48 px; primary buttons 56 px high |
| Motion | 200 ms ease-out for UI; the voice orb has distinct looping animations (see Voice) |
| Focus | 3 px primary ring on every interactive element |

---

## 3. Screen prompts (paste one at a time)

### 3.1 Voice assistant (the hero screen)
```
Design the "Voice" screen of Swasthya Saathi, mobile 390x844, dark theme. Centre: a large circular
microphone orb (180 px) in teal with a soft glow; around it a ring that animates. Above it, the selected
language chip (తెలుగు) that opens a language picker. Below the orb, large status text: "Tap to speak".
Show these five states as separate frames: Idle ("Tap to speak"), Listening (orb pulses with a live
waveform of vertical bars), Thinking ("Understanding..." with a rotating arc), Speaking (outward
ripples and a playback waveform, "Tap to interrupt"), Muted/Error ("Microphone is off - you can type
instead"). Under the orb: an editable text box showing what was heard ("I have a rash on my skin"),
with a Send button and a Retry link. At the bottom: a text input with a keyboard icon so the user can
switch to typing, and the assistant's latest reply as a card with a play/stop button. Persistent red
"Emergency? 112 / 108" pill at the top right. Bottom navigation: Home, Voice (active), Chat, Visits.
```

### 3.2 Chat assistant
```
Design the "Chat" screen, mobile 390x844, light theme. Header: back arrow, conversation title ("Skin
rash in Guntur"), language chip, a Voice shortcut, and the red Emergency pill. Messages: patient
bubbles on the right (teal, white text), assistant bubbles on the left (light mint) with a small
heart-pulse avatar, timestamps, copy / regenerate / play-audio icons under assistant messages, and a
small badge "Used 3 tools". Include a typing indicator ("Swasthya Saathi is thinking..."). Show an
empty state with four suggested prompts as tappable cards in different languages, for example "I've
had fever for 2 days. Which doctor should I see?", "Book an appointment with a skin doctor in Guntur",
"నాకు డాక్టర్ అపాయింట్‌మెంట్ కావాలి", "मुझे अपने अपॉइंटमेंट की याद दिलाओ". Bottom: message input with a
microphone button on the left and a send button on the right.
```

### 3.3 Rich cards inside chat (component sheet)
```
Design a component sheet of the cards that appear inside the chat, mobile width 358 px, light and
dark. 1) Urgency result: three variants - Emergency (red, "Call 112 now" and "Call 108" big buttons),
Urgent (amber, "See a doctor today"), Routine (green, "A routine visit is fine"), each with the
suggested specialty chip (Dermatology). 2) Provider list: 3 compact cards with clinic name, doctor,
distance-free city, languages as small chips (తెలుగు, English), fee (₹500), "Ayushman accepted" badge,
a "Demo listing" saffron badge, and "Next free: Sat 10:00 am". 3) Free slots: heading "Sat, 21 Nov
(IST)" with time chips (10:00 am, 10:20 am, 10:40 am...) and "+3 more". 4) Confirmation card (saffron
border): "Please confirm", one readable sentence "Book an appointment at Demo Skin & Care Clinic,
Guntur on Saturday, 21 November 2026, 10:00 AM for Ravi Kumar (mobile 9876543210). Reason: skin rash",
a collapsible Details row, and two buttons Cancel and Confirm. 5) Booking confirmed card (green):
reference chip AP-CQDZM with copy icon, When, Where, Fee, Reminders set list. 6) Tool progress card:
running (spinner), done (check), error (red) with duration "57 ms".
```

### 3.4 Find care
```
Design the "Find care" screen, mobile 390x844, light theme. Top: title "Find care near you" and a
filter row of chips: Specialty (Dermatology), City (Guntur), Doctor speaks (తెలుగు), Video visit, Accepts
Ayushman. Below: a list of provider cards (clinic name, doctor name, type badge Clinic / Hospital / Health
Centre / Online, languages, fee, next free slot, "Demo listing" badge). Tapping a card opens a bottom sheet
with 5 days of free slot chips in IST and a primary button "Book with assistant" (it opens the chat; it does
not book directly) and a note "The assistant will ask you to confirm". Include an empty state ("No
clinic found in this city - try a video visit") and a loading skeleton.
```

### 3.5 Visits (appointments)
```
Design the "Visits" screen, mobile 390x844, light theme. Tabs: Upcoming / Past. Each appointment card:
status chip (Booked / Cancelled / Completed), mode chip (In person / Video), saffron "Demo listing" badge,
reference chip AP-CQDZM with copy icon, clinic and doctor, "Tomorrow, Sat 21 Nov 2026, 10:00-10:20 am
IST", patient name, masked mobile 98XXXXXX10, fee, reason, a vertical reminder timeline ("Reminder -
Sat 8:00 am - Scheduled", "Feedback request - Sat 12:20 pm - Scheduled"), and buttons "Reschedule with
assistant" and "Cancel" (red, with a confirm dialog). Past cards show a 5-star feedback row. Add an
empty state with a "Ask Saathi to book a new appointment" button.
```

### 3.6 Notifications
```
Design the notification bell dropdown (desktop) and a full-screen notifications list (mobile). Items:
"Appointment reminder", "How was your visit?", "Follow-up visit due", each with an icon in a coloured
circle, the message text in the user's language (show one in తెలుగు), time ("just now"), a small
reference chip, an unread dot, and a "Mark all read" action. Also design the toast shown when a new
reminder arrives, and the bell icon with a numeric badge.
```

### 3.7 Dashboard (Home)
```
Design the "Home" dashboard, mobile 390x844, light theme. Greeting ("Namaste, Ravi") and a large
primary "Start talking" button with a microphone icon, plus a secondary "Type instead". Sections:
"Upcoming appointment" card (next visit with countdown), a row of 4 small stat tiles (Conversations,
Appointments, Open requests, Reminders), "Try asking" suggestion cards in several languages, "Recent
conversations" list, and "Recent assistant actions" list with small tool icons. Desktop version
(1440x900) adds the left sidebar.
```

### 3.8 History
```
Design the "History" screen: a search field ("Search your conversations"), a list of conversations
(title, language chip, message count, "2 h ago"), swipe or overflow menu for Rename and Delete, a delete
confirmation dialog ("This cannot be undone"), and an empty state.
```

### 3.9 Activity (what the assistant did)
```
Design the "Activity" screen: a vertical timeline of assistant runs. Each run: status chip (Completed /
Waiting for confirmation / Failed), the intent ("Book appointment"), which AI model answered (a small
label), duration, and an expandable list of tool steps (icon, tool name, short summary, duration,
success/error). A second tab "Requests and tasks" lists items with reference codes (T-AB3XK, SR-...)
and status chips. A third tab "Tools" lists available tools with a badge "Asks for confirmation".
```

### 3.10 Settings and language
```
Design two screens. 1) "Settings": profile (name, Guest badge), theme (Light / Dark / System segmented
control), voice options (spoken replies, auto-play, send voice automatically, voice gender, silence
timeout slider 0.5-5 s), "Show tool details" toggle, and a "System status" card with green/amber rows:
Speech (Sarvam) connected, AI model (Groq, backup Sarvam) connected, Database connected, each with a
hint when not set up. 2) "Language": a grid of 14 language tiles with native names and small badges
"Listens" and "Speaks" (three languages show only "Listens"), a primary-language picker, secondary
languages multi-select, and an "Auto-detect language" toggle.
```

### 3.11 Mobile navigation and global elements
```
Design the global shell: mobile header (menu, logo mark, red Emergency pill, bell, new chat), bottom
navigation (Home, Voice, Chat, Visits), a slide-over menu with History, Find care, Activity, Settings,
language selector and profile; the desktop 1440x900 layout with a left sidebar (logo, New conversation
button, navigation, recent conversations, Emergency button, language selector, profile) and a
connection status dot ("Live").
```

---

## 4. Component and state checklist (so nothing is missed)

| Component | States and variants to design |
|---|---|
| Voice orb | idle, listening, thinking, speaking, muted / permission denied, error |
| Message bubble | patient, assistant, streaming (typing dots), failed (Retry), with tool badge |
| Buttons | primary, secondary, danger, ghost; default, hover, pressed, disabled, loading |
| Chips | language, status (booked, cancelled, completed), specialty, "Demo listing", "Ayushman accepted" |
| Cards | provider, appointment, notification, tool (running, done, error), confirmation, booking confirmed |
| Urgency result | emergency, urgent, routine |
| Inputs | text, search, message composer, dictated text (editable), toggle, slider, segmented control |
| Feedback | toast (success, info, error), inline error with Retry, empty state, skeleton loader |
| Dialogs | confirm cancel appointment, delete conversation, language picker, microphone permission |
| Navigation | bottom bar (4 items), sidebar, header with bell badge |

## 5. Content bank (use these real strings)

- Tagline: *Your health guide, in your language*
- Voice prompts: *Tap to speak* · *Listening...* · *Understanding...* · *Speaking... tap to interrupt*
- Confirm card title: *Please confirm* · buttons: *Cancel* / *Confirm*
- Demo notice: *These provider listings are SAMPLE (demo) data.*
- Emergency: *Emergency? 112 / 108* · *This may be an emergency. Call 112 or 108 now.*
- Booking reference example: **AP-CQDZM** · mobile shown masked: **98XXXXXX10**
- Sample patient: *Ravi Kumar* · clinic: *Demo Skin & Care Clinic, Guntur* · fee: *₹500*
- Telugu sample reply: *మీ అపాయింట్‌మెంట్ బుక్ అయింది. రిఫరెన్స్ AP-CQDZM.*
- Hindi sample: *आपका अपॉइंटमेंट बुक हो गया है।*
- Languages (native name + English): తెలుగు Telugu · हिन्दी Hindi · தமிழ் Tamil · ಕನ್ನಡ Kannada · മലയാളം Malayalam · বাংলা Bengali · मराठी Marathi · ગુજરાતી Gujarati · ਪੰਜਾਬੀ Punjabi · ଓଡ଼ିଆ Odia · English · অসমীয়া Assamese · اردو Urdu · संस्कृतम् Sanskrit

## 6. Figma setup after export

- **Frames:** mobile 390 × 844, tablet 768 × 1024, desktop 1440 × 900. Name them `Screen / State / Theme` (for example `Voice / Listening / Dark`).
- **Variables:** create colour variables from Section 2 with Light and Dark modes; text styles from the type scale.
- **Components:** build each item in Section 4 as a component with variants (use Auto Layout; boolean props for badge, icon and error).
- **Fonts:** install Inter and Noto Sans (and the Noto script families) so Indic text does not fall back to boxes.
- **Handoff:** keep names aligned with the code (`ToolCard`, `AppointmentCard`, `NotificationBell`, `VoiceOrb`) so developers can map design to `frontend/src/components`.

## 7. Accessibility and responsive rules

- WCAG AA contrast (4.5:1 for text, 3:1 for icons and borders); never use colour alone for status (always an icon or label).
- Touch targets at least 48 px; visible focus ring; every icon button has a text label or tooltip.
- Support text size up to 200 percent without clipping; allow long Indic words to wrap.
- Respect "reduce motion": replace pulsing and ripple animations with a static ring.
- Mobile first, one column. Tablet: two columns for Visits and Find care. Desktop: sidebar plus a centred 760 px conversation column.
- Voice must never be the only way: a typing path is always visible.

## 8. Do not

- Do not let any screen look like it books or cancels without a confirmation step.
- Do not use red except for emergencies and destructive actions.
- Do not use stock photos of doctors or patients; keep to icons and calm illustrations.
- Do not hide the Emergency button, and do not show provider data as real (always the "Demo listing" badge in this version).
- Do not use text smaller than 12 px, or light grey on white.
