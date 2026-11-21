import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { api } from './endpoints'
import type { Appointment, Conversation, CreateAppointmentBody, EmergencyContactBody, FamilyMemberBody, FeedbackBody, Page, PlaceQuery, Preferences, PreferencesUpdate, ProviderQuery } from './types'

export const qk = {
  me: ['me'] as const,
  prefs: ['preferences'] as const,
  languages: ['languages'] as const,
  health: ['health'] as const,
  agents: ['agents'] as const,
  dashboard: ['dashboard'] as const,
  conversations: (q: string) => ['conversations', q] as const,
  conversationsAll: ['conversations'] as const,
  conversation: (id: string) => ['conversation', id] as const,
  executions: ['executions'] as const,
  agoraStatus: ['agora', 'status'] as const,
  callTranscript: (id: string) => ['agora', 'transcript', id] as const,
  tasks: (status: string) => ['tasks', status] as const,
  tasksAll: ['tasks'] as const,
}

const PAGE = 20

export const useMe = () => useQuery({ queryKey: qk.me, queryFn: api.me, staleTime: 5 * 60_000 })
export const useLanguages = () => useQuery({ queryKey: qk.languages, queryFn: api.languages, staleTime: Infinity })
export const useHealth = () => useQuery({ queryKey: qk.health, queryFn: api.health, staleTime: 15_000, refetchInterval: 30_000 })
export const useAgents = () => useQuery({ queryKey: qk.agents, queryFn: api.agents, staleTime: 5 * 60_000 })
export const useDashboard = () => useQuery({ queryKey: qk.dashboard, queryFn: api.dashboard, staleTime: 10_000 })

export const usePrefs = () => useQuery({ queryKey: qk.prefs, queryFn: api.preferences, staleTime: 5 * 60_000 })

export function useUpdatePrefs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: PreferencesUpdate) => api.updatePreferences(patch),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: qk.prefs })
      const prev = qc.getQueryData<Preferences>(qk.prefs)
      if (prev) qc.setQueryData<Preferences>(qk.prefs, { ...prev, ...patch })
      return { prev }
    },
    onError: (_e, _p, ctx) => ctx?.prev && qc.setQueryData(qk.prefs, ctx.prev),
    onSuccess: (data) => qc.setQueryData(qk.prefs, data),
  })
}

export function useUpdateMe() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (name: string) => api.updateMe(name), onSuccess: (u) => qc.setQueryData(qk.me, u) })
}

export function useConversations(q = '') {
  return useInfiniteQuery({
    queryKey: qk.conversations(q),
    queryFn: ({ pageParam }) => api.conversations({ q, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.limit : undefined),
    staleTime: 10_000,
  })
}

export function flattenPages<T>(data: InfiniteData<Page<T>> | undefined): T[] {
  return data?.pages.flatMap((p) => p.items) ?? []
}

export function useRenameConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.renameConversation(id, title),
    onMutate: async ({ id, title }) => {
      await qc.cancelQueries({ queryKey: qk.conversationsAll })
      const snapshots = qc.getQueriesData<InfiniteData<Page<Conversation>>>({ queryKey: qk.conversationsAll })
      snapshots.forEach(([key, data]) => {
        if (!data) return
        qc.setQueryData<InfiniteData<Page<Conversation>>>(key, { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.map((c) => (c.id === id ? { ...c, title } : c)) })) })
      })
      return { snapshots }
    },
    onError: (_e, _v, ctx) => ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data)),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.conversationsAll })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: qk.conversationsAll })
      const snapshots = qc.getQueriesData<InfiniteData<Page<Conversation>>>({ queryKey: qk.conversationsAll })
      snapshots.forEach(([key, data]) => {
        if (!data) return
        qc.setQueryData<InfiniteData<Page<Conversation>>>(key, { ...data, pages: data.pages.map((p) => ({ ...p, total: Math.max(0, p.total - 1), items: p.items.filter((c) => c.id !== id) })) })
      })
      return { snapshots }
    },
    onError: (_e, _v, ctx) => ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data)),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.conversationsAll })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

export function useExecutions() {
  return useInfiniteQuery({
    queryKey: qk.executions,
    queryFn: ({ pageParam }) => api.executions({ limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.limit : undefined),
    staleTime: 5_000,
  })
}

// ---------------------------------------------------------------- appointments

export const useAppointments = (scope: 'upcoming' | 'past') =>
  useQuery({ queryKey: ['appointments', scope], queryFn: () => api.appointments({ scope, limit: 50 }), staleTime: 10_000 })

/** Put a changed appointment into every cached list, then refetch (a cancelled one moves from Upcoming to Past). */
function useAppointmentCacheUpdate() {
  const qc = useQueryClient()
  return (updated: Appointment) => {
    qc.setQueriesData<Page<Appointment>>({ queryKey: ['appointments'] }, (page) => (page ? { ...page, items: page.items.map((a) => (a.id === updated.id ? updated : a)) } : page))
    void qc.invalidateQueries({ queryKey: ['appointments'] })
    void qc.invalidateQueries({ queryKey: qk.dashboard })
    void qc.invalidateQueries({ queryKey: ['notifications'] })
  }
}

export function useCancelAppointment() {
  const apply = useAppointmentCacheUpdate()
  return useMutation({ mutationFn: ({ id, reason }: { id: string; reason?: string }) => api.cancelAppointment(id, reason), onSuccess: apply })
}

/** Demo-only helpers ("simulate visit done" / "send reminder now"). */
export function useDemoAppointmentAction(kind: 'complete' | 'remind') {
  const apply = useAppointmentCacheUpdate()
  return useMutation({ mutationFn: (id: string) => (kind === 'complete' ? api.completeAppointment(id) : api.remindNow(id)), onSuccess: apply })
}

// ---------------------------------------------------------------- notifications

/** Polled every 20 s; react-query pauses the interval while the tab is hidden and refetches on focus. */
export const useNotifications = () =>
  useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.notifications({ limit: 20 }),
    refetchInterval: 20_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  })

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => api.markNotificationRead(id), onSettled: () => void qc.invalidateQueries({ queryKey: ['notifications'] }) })
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: () => api.markAllNotificationsRead(), onSettled: () => void qc.invalidateQueries({ queryKey: ['notifications'] }) })
}

// ---------------------------------------------------------------- providers

export const useProviders = (query: ProviderQuery) => useQuery({ queryKey: ['providers', query], queryFn: () => api.providers(query), staleTime: 30_000 })

/** Real places near a city or a point. Only runs when there is a location to search around. */
export const usePlaces = (query: PlaceQuery | null) =>
  useQuery({ queryKey: ['places', query], queryFn: () => api.searchPlaces(query as PlaceQuery), enabled: !!query, staleTime: 5 * 60_000, retry: 1, retryDelay: 800 })

export const useProviderAvailability = (code: string | null, enabled = true) =>
  useQuery({ queryKey: ['availability', code], queryFn: () => api.providerAvailability(code as string, 7), enabled: enabled && !!code, staleTime: 10_000 })

/** Book an appointment from the booking sheet (the same rules as the assistant's tool; the server is the authority). */
export function useCreateAppointment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateAppointmentBody) => api.createAppointment(body),
    onSettled: (_data, _err, body) => {
      void qc.invalidateQueries({ queryKey: ['availability', body.provider_code] }) // the slot is taken now (or was already)
      void qc.invalidateQueries({ queryKey: ['providers'] })
      void qc.invalidateQueries({ queryKey: ['appointments'] })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      void qc.invalidateQueries({ queryKey: ['notifications'] })
    },
  })
}

/** Rate a completed visit (1-5 stars and an optional comment). */
export function useSubmitFeedback() {
  const apply = useAppointmentCacheUpdate()
  return useMutation({ mutationFn: ({ id, ...body }: { id: string } & FeedbackBody) => api.submitFeedback(id, body), onSuccess: apply })
}

export function useTasks(status = '') {
  return useQuery({ queryKey: qk.tasks(status), queryFn: () => api.tasks({ status: status || undefined, limit: 50 }), staleTime: 5_000 })
}

/** The pre-visit checklist: the person's own to-dos (not submitted service requests). */
export const useChecklist = () => useQuery({ queryKey: ['tasks', 'checklist'], queryFn: () => api.tasks({ kind: 'task', limit: 50 }), staleTime: 5_000 })

export function useUpdateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'open' | 'in_progress' | 'done' | 'cancelled' }) => api.updateTask(id, status),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.tasksAll })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

// ---------------------------------------------------------------- family profiles

export const useFamily = () => useQuery({ queryKey: ['family'], queryFn: api.family, staleTime: 30_000 })

/** A change to a member also changes how appointments label "for <name>", so those lists refresh too. */
function useFamilyInvalidate() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ['family'] })
    void qc.invalidateQueries({ queryKey: ['appointments'] })
  }
}

export function useCreateFamilyMember() {
  const done = useFamilyInvalidate()
  return useMutation({ mutationFn: (body: FamilyMemberBody) => api.createFamilyMember(body), onSuccess: done })
}

export function useUpdateFamilyMember() {
  const done = useFamilyInvalidate()
  return useMutation({ mutationFn: ({ id, patch }: { id: string; patch: Partial<FamilyMemberBody> }) => api.updateFamilyMember(id, patch), onSuccess: done })
}

export function useDeleteFamilyMember() {
  const done = useFamilyInvalidate()
  return useMutation({ mutationFn: (id: string) => api.deleteFamilyMember(id), onSuccess: done })
}

// ---------------------------------------------------------------- emergency (SOS)

export const useEmergencyContacts = () => useQuery({ queryKey: ['emergency-contacts'], queryFn: api.emergencyContacts, staleTime: 30_000 })

export function useCreateEmergencyContact() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (body: EmergencyContactBody) => api.createEmergencyContact(body), onSuccess: () => void qc.invalidateQueries({ queryKey: ['emergency-contacts'] }) })
}

export function useDeleteEmergencyContact() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => api.deleteEmergencyContact(id), onSuccess: () => void qc.invalidateQueries({ queryKey: ['emergency-contacts'] }) })
}

/** Numbers, nearby care and first aid, for a city or exact coordinates. Retries once only: with no network the page falls back to its cached copy fast. */
export const useSos = (where: { city: string; lat?: number; lon?: number }) => {
  const city = where.city.trim()
  const coords = where.lat !== undefined && where.lon !== undefined ? { lat: where.lat, lon: where.lon } : null
  return useQuery({
    queryKey: ['sos', coords ? `${coords.lat.toFixed(3)},${coords.lon.toFixed(3)}` : city.toLowerCase()],
    queryFn: () => api.sos(coords ?? { city: city || undefined }),
    staleTime: 5 * 60_000,
    retry: 1,
    retryDelay: 800,
  })
}

/** Refs of upcoming visits the clinic has not confirmed, so reminders about them can say "call to confirm". */
export function usePlannedRefs(): Set<string> {
  const { data } = useAppointments('upcoming')
  return new Set((data?.items ?? []).filter((a) => a.status === 'booked' && a.clinic_confirmed === false).map((a) => a.ref))
}

/** Live-call availability (keys configured, tool mode, languages). */
export const useAgoraStatus = () => useQuery({ queryKey: qk.agoraStatus, queryFn: api.agoraStatus, staleTime: 60_000, retry: false })

/** The conversation behind a live call. Polls every 1.5 s while the call is live so the transcript fills in. */
export const useCallTranscript = (conversationId: string | null, live: boolean) =>
  useQuery({
    queryKey: qk.callTranscript(conversationId ?? ''),
    queryFn: () => api.conversation(conversationId as string),
    enabled: !!conversationId,
    refetchInterval: live ? 1500 : false,
    staleTime: 0,
  })
