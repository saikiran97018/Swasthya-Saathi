// Mirrors backend/app/schemas/*.py and the WebSocket events in services/agent_service.py + agents/orchestrator.py.

export type Role = 'user' | 'assistant'
export type InputMode = 'text' | 'voice'
export type MessageSource = 'user' | 'ai' | 'tool'

export type ToolStatus = 'running' | 'success' | 'error' | 'awaiting_confirmation' | 'denied' | 'cancelled'

export interface ToolExecution {
  id: string
  execution_id: string
  conversation_id: string
  assistant_message_id: string | null
  tool_name: string
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
  summary: string | null
  explanation: string | null
  status: ToolStatus
  requires_confirmation: boolean
  duration_ms: number | null
  error: string | null
  created_at: string
}

export interface Message {
  id: string
  conversation_id: string
  seq: number
  role: Role
  content: string
  language: string | null
  input_mode: InputMode
  source: MessageSource
  tools_used: string[]
  tool_executions: ToolExecution[]
  pending_confirmation: boolean
  created_at: string
}

/** A message in the UI: server message plus client-only delivery state. */
export interface UiMessage extends Message {
  localStatus?: 'sending' | 'failed'
}

export interface Conversation {
  id: string
  title: string
  language: string
  created_at: string
  updated_at: string
  last_message_at: string
  message_count: number
  voice_message_count: number
  summary: string | null
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface User {
  id: string
  email: string | null
  display_name: string
  is_guest: boolean
  created_at: string
}

export interface TokenOut {
  access_token: string
  token_type: string
  user: User
}

export interface ChatOut {
  conversation: Conversation
  user_message: Message | null
  assistant_message: Message | null
  messages: Message[]
  /** Latest state of every tool execution touched in the turn (after a confirm call: the outcome). */
  tool_executions?: ToolExecution[]
  pending_confirmation: ToolExecution | null
  language: string
  execution_id: string | null
}

export interface Transcription {
  text: string
  language: string
  duration_seconds: number
}

export interface AgentToolInfo {
  name: string
  description: string
  category: string
  requires_confirmation: boolean
  enabled: boolean
}

export interface AgentInfo {
  id: string
  name: string
  description: string
  model: string
  tools: AgentToolInfo[]
}

export interface Execution {
  id: string
  conversation_id: string
  conversation_title: string | null
  status: string
  intent: string | null
  model: string | null
  steps: number
  latency_ms: number | null
  error: string | null
  started_at: string
  finished_at: string | null
  tool_executions: ToolExecution[]
}

export type TaskStatus = 'open' | 'in_progress' | 'done' | 'cancelled' | 'submitted'

export interface Task {
  id: string
  ref: string
  kind: 'task' | 'service_request' | string
  title: string
  description: string | null
  status: TaskStatus | string
  due_at: string | null
  payload: Record<string, unknown>
  conversation_id: string | null
  created_at: string
  updated_at: string
}

export interface Preferences {
  theme: 'system' | 'light' | 'dark'
  voice_output_enabled: boolean
  auto_play_responses: boolean
  auto_send_voice: boolean
  auto_detect_language: boolean
  tts_gender: 'female' | 'male'
  show_tool_details: boolean
  silence_timeout_ms: number
  symptom_checkins: boolean
  sms_reminders: boolean
  sms_available: boolean
  primary_language: string
  secondary_languages: string[]
}

export type PreferencesUpdate = Partial<Preferences>

export interface LanguageInfo {
  code: string
  name: string
  native_name: string
  asr: boolean
  tts: boolean
}

export interface Dashboard {
  conversations: number
  messages: number
  voice_messages: number
  tool_runs: number
  open_tasks: number
  submitted_requests: number
  appointments_total: number
  unread_notifications: number
  upcoming_appointments: Appointment[]
  tool_usage: { tool: string; count: number }[]
  recent_conversations: Conversation[]
  recent_executions: Execution[]
}

export interface Health {
  status: 'ok' | 'degraded'
  database: boolean
  /** Active speech-to-text / text-to-speech provider. */
  speech_provider: 'sarvam' | 'bhashini'
  /** True when the active speech provider has credentials. */
  speech_configured: boolean
  /** Longest recording the speech provider accepts; the app must stop recording before this. */
  max_audio_seconds: number
  bhashini_configured: boolean
  sarvam_configured: boolean
  llm_configured: boolean
  llm_model: string
  /** Model used automatically when the primary model fails. */
  llm_fallback_model?: string | null
  web_search_configured: boolean
  /** True when demo helpers (simulate visit / remind now) and sample provider data are enabled. */
  demo_mode: boolean
  version: string
}

// ---------------------------------------------------------------- providers & appointments

export const SPECIALTIES = ['general medicine', 'pediatrics', 'gynecology', 'dermatology', 'cardiology', 'orthopedics', 'ophthalmology', 'ent', 'dentistry', 'psychiatry'] as const
export type Specialty = (typeof SPECIALTIES)[number]

export interface Provider {
  code: string
  name: string
  kind: string
  doctor_name: string | null
  specialties: string[]
  city: string
  state: string
  address: string | null
  phone: string | null
  languages: string[]
  fee_inr: number
  accepts_ayushman: boolean
  teleconsultation: boolean
  is_demo: boolean
  /** IST date (YYYY-MM-DD) and time (HH:MM) of the first open slot. */
  next_available: { date: string; time: string } | null
  /** Average of real patient ratings; null until the first rating exists. */
  rating_avg?: number | null
  /** How many real ratings exist (0 until the first one). Show a rating only when this is above 0. */
  rating_count?: number
  /** Where the listing comes from. OpenStreetMap places have no fee, rating or online slots. */
  source?: 'openstreetmap' | 'partner' | 'demo' | null
  lat?: number | null
  lon?: number | null
  website?: string | null
  opening_hours?: string | null
}

/** POST /appointments body. `slot_start` is "YYYY-MM-DD HH:MM" in IST, exactly as the availability endpoint returned it. */
export interface CreateAppointmentBody {
  /** Exactly one of provider_code (partner clinic with online slots) or place_id (a map place: "Plan a visit"). */
  provider_code?: string
  place_id?: string
  slot_start: string
  patient_name: string
  patient_mobile: string
  reason: string
  mode?: 'in_person' | 'teleconsultation'
  language?: string
  /** Book for a saved family member instead of the account holder. */
  family_member_id?: string
}

export interface FeedbackBody {
  rating: number
  comment?: string
}

export interface ProviderSlots {
  provider: Provider
  timezone: string
  slot_minutes: number
  /** local IST date (YYYY-MM-DD) -> open start times (HH:MM, IST) */
  open_slots: Record<string, string[]>
}

export interface ProviderQuery {
  specialty?: string
  city?: string
  language?: string
  teleconsultation?: boolean
  accepts_ayushman?: boolean
}

export interface ReminderInfo {
  kind: string
  due_at: string
  status: string
}

export type AppointmentStatus = 'booked' | 'cancelled' | 'completed'

export interface Appointment {
  id: string
  ref: string
  status: AppointmentStatus
  mode: 'in_person' | 'teleconsultation' | string
  starts_at: string
  ends_at: string
  patient_name: string
  /** Already masked by the server, e.g. 98XXXXXX10. */
  patient_mobile: string
  reason: string
  language: string
  provider: Provider
  reschedule_count: number
  feedback_rating: number | null
  feedback_comment: string | null
  conversation_id: string | null
  reminders: ReminderInfo[]
  /** Set when the visit was booked for a family member; null when it is for the account holder. */
  family_member?: { id: string; name: string; relation: string } | null
  /** false = a planned visit: the clinic has not confirmed it and the person should phone to confirm. */
  clinic_confirmed?: boolean
  created_at: string
}

export type NotificationKind = 'appointment_reminder' | 'follow_up' | 'feedback_request' | 'medicine' | 'symptom_checkin' | 'vaccine'

export interface AppNotification {
  id: string
  kind: NotificationKind
  title: string
  /** Already translated into the user's language when possible. */
  message: string
  language: string
  appointment_ref: string | null
  conversation_id: string | null
  delivered_at: string
  read_at: string | null
}

export interface NotificationPage {
  items: AppNotification[]
  total: number
  unread_count: number
}

// ---------------------------------------------------------------- places (OpenStreetMap + partner clinics)

export type PlaceKind = 'hospital' | 'clinic' | 'doctor' | 'phc' | 'pharmacy' | 'other'

export interface Place {
  /** 'osm:node/123' (OpenStreetMap), 'gmaps:<id>' (Google) or the partner provider code. */
  id: string
  name: string
  kind: PlaceKind
  specialties: string[]
  address: string | null
  city: string | null
  phone: string | null
  website: string | null
  opening_hours: string | null
  lat: number
  lon: number
  distance_km: number | null
  emergency: boolean
  /** Google results only. */
  rating?: number | null
  rating_count?: number | null
  maps_url?: string | null
  source: 'openstreetmap' | 'google' | 'partner'
  has_slots: boolean
  provider_code: string | null
}

export interface PlacesResult {
  center: { lat: number; lon: number; label: string | null } | null
  items: Place[]
  attribution: string
  note: string | null
}

/** GET /places/search: send a city OR lat+lon. */
export interface PlaceQuery {
  city?: string
  lat?: number
  lon?: number
  radius_km?: number
  kind?: 'hospital' | 'clinic' | 'doctor' | 'pharmacy'
  q?: string
  specialty?: string
  limit?: number
}

// ---------------------------------------------------------------- family profiles

export const FAMILY_RELATIONS = ['self', 'spouse', 'child', 'parent', 'sibling', 'other'] as const
export type FamilyRelation = (typeof FAMILY_RELATIONS)[number]
export type FamilyGender = 'female' | 'male' | 'other'

export interface FamilyMember {
  id: string
  name: string
  relation: FamilyRelation
  birth_year: number | null
  birth_date: string | null
  gender: FamilyGender | null
  mobile: string | null
  language: string | null
  created_at: string
}

/** POST /family body; PATCH /family/{id} takes any subset of these. */
export interface FamilyMemberBody {
  name: string
  relation: FamilyRelation
  birth_year?: number | null
  birth_date?: string | null
  gender?: FamilyGender | null
  mobile?: string | null
  language?: string | null
}

// ---------------------------------------------------------------- emergency (SOS)

export interface VaccineItem {
  key: string
  label: string
  vaccines: string[]
  due_on: string
  status: 'given' | 'overdue' | 'due' | 'upcoming'
  given_on: string | null
  note: string
}

export interface VaccinationView {
  member_id: string
  name: string
  birth_date: string | null
  eligible: boolean
  reason: 'no_birth_date' | 'too_old' | null
  schedule_name: string
  disclaimer: string
  items: VaccineItem[]
}

export interface DoctorNote {
  text: string
  source: 'assistant' | 'basic'
}

export interface MedicineReminder {
  series: string
  label: string
  times: string[]
  ends_on: string | null
  next_due: string | null
}

export interface MedicineReminderBody {
  label: string
  times: string[]
  days: number
}

export type ReplyRating = 'up' | 'down'
export type ReplyReason = 'wrong_info' | 'unsafe' | 'misunderstood' | 'not_helpful' | 'other'

export interface BillingPlan {
  id: 'monthly' | 'yearly'
  name: string
  price_inr: number
  period: string
  note: string | null
}

export interface BillingPlans {
  enabled: boolean
  key_id: string | null
  plans: BillingPlan[]
  features: string[]
  free_daily_messages: number
  free_daily_calls: number
}

export interface BillingStatus {
  plan: 'free' | 'plus'
  status: string | null
  billing_period: string | null
  renews_at: string | null
  cancel_at_cycle_end: boolean
  messages_today: number
  messages_limit: number | null
  calls_today: number
  calls_limit: number | null
}

export interface SubscribeResult {
  subscription_id: string
  key_id: string
  plan: string
}

export interface VerifyBody {
  razorpay_payment_id: string
  razorpay_subscription_id: string
  razorpay_signature: string
}

export interface PushConfig {
  available: boolean
  public_key: string
  devices: number
}

export interface PushSubscribeBody {
  endpoint: string
  keys: { p256dh: string; auth: string }
}

export interface EmergencyContact {
  id: string
  name: string
  phone: string
  relation: string | null
  created_at: string
}

export interface EmergencyContactBody {
  name: string
  phone: string
  relation?: string
}

export type SosNumberKind = 'emergency' | 'ambulance' | 'women' | 'child' | 'mental_health' | 'other'

export interface SosNumber {
  code: string
  label: string
  description: string
  kind: SosNumberKind
}

export interface SosNearby {
  code: string
  name: string
  kind: string
  city: string | null
  address: string | null
  phone: string | null
  teleconsultation: boolean
  is_demo: boolean
  lat?: number | null
  lon?: number | null
  distance_km?: number | null
  source?: 'openstreetmap' | 'partner' | null
}

export interface FirstAidGuide {
  id: string
  title: string
  steps: string[]
  call_if: string
}

/** GET /sos?city= */
export interface SosInfo {
  numbers: SosNumber[]
  nearby: SosNearby[]
  first_aid: FirstAidGuide[]
  disclaimer: string
}

// ---------------------------------------------------------------- websocket

export type ClientCommand =
  | { type: 'message'; text: string; conversation_id?: string | null; input_mode: InputMode; language?: string; voice_output: boolean }
  | { type: 'regenerate'; conversation_id: string; voice_output?: boolean }
  | { type: 'confirm'; execution_id: string; approve: boolean; voice_output?: boolean }
  | { type: 'cancel' }
  | { type: 'ping' }

export type Stage = 'thinking' | 'tool' | 'responding'

export type ServerEvent =
  | { type: 'conversation'; conversation: Conversation }
  | { type: 'language'; language: string; changed: boolean }
  | { type: 'user_message'; message: Message }
  | { type: 'stage'; stage: Stage }
  | { type: 'token'; delta: string }
  | { type: 'message'; message: Message }
  | { type: 'tool_start'; tool_execution: ToolExecution }
  | { type: 'tool_result'; tool_execution: ToolExecution }
  | { type: 'confirmation_required'; tool_execution: ToolExecution }
  | { type: 'error'; code: string; message: string; retryable: boolean }
  | { type: 'cancelled' }
  | { type: 'done'; execution_id: string; status: 'completed' | 'awaiting_confirmation' | string; language?: string }
  | { type: 'pong' }

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}

// ---- Agora Conversational AI (live call) ----
export type AgoraMode = 'tools' | 'chat_only' | 'unconfigured'

export interface AgoraLanguage {
  code: string
  name: string
  native_name: string
  voice: string
}

export interface AgoraStatus {
  configured: boolean
  murf_configured: boolean
  mode: AgoraMode
  languages: AgoraLanguage[]
  note: string | null
}

export interface AgoraSessionBody {
  language?: string
  conversation_id?: string
}

export interface AgoraSession {
  app_id: string
  channel: string
  token: string
  uid: number
  agent_uid: number
  agent_id: string
  conversation_id: string
  language: string
  mode: 'tools' | 'chat_only'
  /** Seconds until the RTC token expires. */
  expires_in: number
  greeting: string
  voice: { vendor: 'murf'; voice_id: string; locale: string }
}
