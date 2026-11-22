import { API_PREFIX, getToken, request } from './client'
import type {
  AgentInfo,
  AgoraSession,
  AgoraSessionBody,
  AgoraStatus,
  AppNotification,
  BillingPlans,
  BillingStatus,
  Appointment,
  ChatOut,
  Conversation,
  ConversationDetail,
  CreateAppointmentBody,
  Dashboard,
  DoctorNote,
  EmergencyContact,
  EmergencyContactBody,
  Execution,
  FamilyMember,
  FamilyMemberBody,
  FeedbackBody,
  Health,
  LanguageInfo,
  MedicineReminder,
  MedicineReminderBody,
  NotificationPage,
  Page,
  PlaceQuery,
  PlacesResult,
  Preferences,
  PreferencesUpdate,
  ReplyRating,
  ReplyReason,
  PushConfig,
  PushSubscribeBody,
  Provider,
  SubscribeResult,
  VerifyBody,
  ProviderQuery,
  ProviderSlots,
  SosInfo,
  Task,
  TokenOut,
  Transcription,
  User,
  VaccinationView,
} from './types'

export const api = {
  // auth
  me: () => request<User>('/auth/me'),
  updateMe: (display_name: string) => request<User>('/auth/me', { method: 'PATCH', json: { display_name } }),
  guest: () => request<TokenOut>('/auth/guest', { method: 'POST', json: {} }),

  // reference data
  health: () => request<Health>('/health'),
  languages: () => request<LanguageInfo[]>('/languages'),
  preferences: () => request<Preferences>('/preferences'),
  updatePreferences: (patch: PreferencesUpdate) => request<Preferences>('/preferences', { method: 'PUT', json: patch }),

  // conversations
  conversations: (params: { q?: string; limit?: number; offset?: number }) => request<Page<Conversation>>('/conversations', { query: params }),
  conversation: (id: string) => request<ConversationDetail>(`/conversations/${id}`),
  createConversation: (body?: { title?: string; language?: string }) => request<Conversation>('/conversations', { method: 'POST', json: body ?? {} }),
  renameConversation: (id: string, title: string) => request<Conversation>(`/conversations/${id}`, { method: 'PATCH', json: { title } }),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: 'DELETE', as: 'none' }),

  // chat (REST; the WebSocket is the primary path)
  chat: (body: { conversation_id?: string | null; message?: string; input_mode?: 'text' | 'voice'; language?: string; voice_output?: boolean; regenerate?: boolean }) =>
    request<ChatOut>('/chat', { method: 'POST', json: body }),
  confirm: (executionId: string, approve: boolean) => request<ChatOut>(`/agents/executions/${executionId}/confirm`, { method: 'POST', json: { approve } }),

  // live call (Agora Conversational AI)
  agoraStatus: () => request<AgoraStatus>('/agora/status'),
  agoraStartSession: (body: AgoraSessionBody) => request<AgoraSession>('/agora/session', { method: 'POST', json: body }),
  agoraStopSession: (agentId: string) => request<void>(`/agora/session/${encodeURIComponent(agentId)}/stop`, { method: 'POST', as: 'none' }),

  // voice
  transcribe: (audio: Blob, language: string) => {
    const form = new FormData()
    form.append('audio', audio, 'speech.wav')
    form.append('language', language)
    return request<Transcription>('/voice/transcribe', { method: 'POST', form })
  },
  synthesize: (text: string, language: string, gender?: 'female' | 'male') =>
    request<Blob>('/voice/synthesize', { method: 'POST', json: { text, language, ...(gender ? { gender } : {}) }, as: 'blob' }),

  // appointments
  appointments: (params: { scope: 'upcoming' | 'past' | 'all'; limit?: number; offset?: number }) => request<Page<Appointment>>('/appointments', { query: params }),
  createAppointment: (body: CreateAppointmentBody) => request<Appointment>('/appointments', { method: 'POST', json: body }),
  submitFeedback: (id: string, body: FeedbackBody) => request<Appointment>(`/appointments/${id}/feedback`, { method: 'POST', json: body }),
  cancelAppointment: (id: string, reason?: string) => request<Appointment>(`/appointments/${id}/cancel`, { method: 'POST', json: reason ? { reason } : {} }),
  /** Demo helpers: 403 `demo_disabled` unless the server runs with DEMO_MODE=true. */
  completeAppointment: (id: string) => request<Appointment>(`/appointments/${id}/complete`, { method: 'POST' }),
  remindNow: (id: string) => request<Appointment>(`/appointments/${id}/remind-now`, { method: 'POST' }),

  // notifications
  notifications: (params: { limit?: number; unread_only?: boolean } = {}) => request<NotificationPage>('/notifications', { query: params }),
  markNotificationRead: (id: string) => request<AppNotification>(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request<{ marked_read: number }>('/notifications/read-all', { method: 'POST' }),

  // providers
  providers: (q: ProviderQuery) => request<Provider[]>('/providers', { query: { ...q, limit: 12 } }),
  providerAvailability: (code: string, days = 7) => request<ProviderSlots>(`/providers/${encodeURIComponent(code)}/availability`, { query: { days } }),

  // places: real nearby hospitals, clinics and doctors (OpenStreetMap) plus registered partner clinics
  searchPlaces: (q: PlaceQuery) => request<PlacesResult>('/places/search', { query: { limit: 30, radius_km: 8, ...q } }),

  // family profiles
  family: () => request<FamilyMember[]>('/family'),
  createFamilyMember: (body: FamilyMemberBody) => request<FamilyMember>('/family', { method: 'POST', json: body }),
  updateFamilyMember: (id: string, patch: Partial<FamilyMemberBody>) => request<FamilyMember>(`/family/${id}`, { method: 'PATCH', json: patch }),
  deleteFamilyMember: (id: string) => request<void>(`/family/${id}`, { method: 'DELETE', as: 'none' }),

  // vaccination tracker and the note for the doctor
  vaccinations: (memberId: string) => request<VaccinationView>(`/family/${memberId}/vaccinations`),
  markVaccination: (memberId: string, milestone: string, givenOn: string | null) =>
    request<VaccinationView>(`/family/${memberId}/vaccinations/${milestone}`, { method: 'PUT', json: { given_on: givenOn } }),
  doctorNote: (conversationId: string) => request<DoctorNote>(`/conversations/${conversationId}/doctor-note`, { method: 'POST' }),

  // medicine reminders and reply ratings
  medicineReminders: () => request<MedicineReminder[]>('/medicine-reminders'),
  addMedicineReminder: (body: MedicineReminderBody) => request<MedicineReminder>('/medicine-reminders', { method: 'POST', json: body }),
  stopMedicineReminder: (series: string) => request<void>(`/medicine-reminders/${series}`, { method: 'DELETE', as: 'none' }),
  rateReply: (messageId: string, body: { rating: ReplyRating; reason?: ReplyReason; note?: string }) =>
    request<{ message_id: string; rating: ReplyRating; reason: ReplyReason | null }>(`/messages/${messageId}/feedback`, { method: 'PUT', json: body }),
  clearReplyRating: (messageId: string) => request<void>(`/messages/${messageId}/feedback`, { method: 'DELETE', as: 'none' }),

  // Saathi Plus (Razorpay)
  billingPlans: () => request<BillingPlans>('/billing/plans'),
  billingStatus: () => request<BillingStatus>('/billing/status'),
  billingSubscribe: (plan: 'monthly' | 'yearly') => request<SubscribeResult>('/billing/subscribe', { method: 'POST', json: { plan } }),
  billingVerify: (body: VerifyBody) => request<BillingStatus>('/billing/verify', { method: 'POST', json: body }),
  billingCancel: () => request<BillingStatus>('/billing/cancel', { method: 'POST' }),

  // phone notifications (Web Push)
  pushConfig: () => request<PushConfig>('/push/config'),
  pushSubscribe: (body: PushSubscribeBody) => request<PushConfig>('/push/subscriptions', { method: 'POST', json: body }),
  pushUnsubscribe: (endpoint: string) => request<void>('/push/subscriptions', { method: 'DELETE', json: { endpoint }, as: 'none' }),
  pushTest: () => request<{ sent: number }>('/push/test', { method: 'POST' }),

  // emergency / SOS
  emergencyContacts: () => request<EmergencyContact[]>('/emergency-contacts'),
  createEmergencyContact: (body: EmergencyContactBody) => request<EmergencyContact>('/emergency-contacts', { method: 'POST', json: body }),
  deleteEmergencyContact: (id: string) => request<void>(`/emergency-contacts/${id}`, { method: 'DELETE', as: 'none' }),
  sos: (where: { city?: string; lat?: number; lon?: number } = {}) => request<SosInfo>('/sos', { query: where }),

  // agents, tasks, dashboard
  agents: () => request<AgentInfo[]>('/agents'),
  executions: (params: { limit?: number; offset?: number }) => request<Page<Execution>>('/agents/executions', { query: params }),
  tasks: (params: { status?: string; kind?: string; limit?: number; offset?: number }) => request<Page<Task>>('/tasks', { query: params }),
  updateTask: (id: string, status: 'open' | 'in_progress' | 'done' | 'cancelled') => request<Task>(`/tasks/${id}`, { method: 'PATCH', json: { status } }),
  dashboard: () => request<Dashboard>('/dashboard/summary'),
}

/**
 * Best-effort "stop the cloud agent" for when the page is going away (unmount, pagehide).
 * Uses fetch with keepalive and the same bearer header as the API client (sendBeacon cannot set headers).
 */
export function stopAgoraSessionKeepalive(agentId: string): void {
  const token = getToken()
  if (!token) return
  try {
    void fetch(`${API_PREFIX}/agora/session/${encodeURIComponent(agentId)}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, keepalive: true }).catch(() => undefined)
  } catch {
    /* nothing more we can do while unloading */
  }
}
