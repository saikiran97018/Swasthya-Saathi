import type { ApiErrorBody, TokenOut } from './types'

const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''
export const API_PREFIX = `${API_BASE}/api/v1`

const TOKEN_KEY = 'bva.token'

export class ApiError extends Error {
  status: number
  code: string
  details?: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable: token lives only for this session via memoryToken */
  }
  memoryToken = token
}

let memoryToken: string | null = null
let bootstrapping: Promise<TokenOut> | null = null

/** Create a guest account (once, even if many requests race) and remember its token. */
export function bootstrapGuest(): Promise<TokenOut> {
  if (!bootstrapping) {
    bootstrapping = (async () => {
      const res = await fetch(`${API_PREFIX}/auth/guest`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      if (!res.ok) throw await toApiError(res)
      const data = (await res.json()) as TokenOut
      setToken(data.access_token)
      return data
    })().finally(() => {
      bootstrapping = null
    })
  }
  return bootstrapping
}

/** Return a usable token, creating a guest account if there isn't one. */
export async function ensureToken(): Promise<string> {
  const existing = getToken() ?? memoryToken
  if (existing) return existing
  return (await bootstrapGuest()).access_token
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null
  try {
    body = (await res.json()) as Partial<ApiErrorBody>
  } catch {
    /* non-JSON error */
  }
  const e = body?.error
  const fallback = res.status >= 500 ? 'The server had a problem. Please try again.' : `Request failed (${res.status})`
  return new ApiError(res.status, e?.code ?? 'http_error', e?.message ?? fallback, e?.details)
}

interface RequestOptions {
  method?: string
  json?: unknown
  form?: FormData
  query?: Record<string, string | number | boolean | undefined | null>
  signal?: AbortSignal
  as?: 'json' | 'blob' | 'none'
}

export async function request<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const token = await ensureToken()
  const qs = opts.query
    ? '?' +
      Object.entries(opts.query)
        .filter(([, v]) => v !== undefined && v !== null && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : ''
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  }

  let res: Response
  try {
    res = await fetch(`${API_PREFIX}${path}${qs === '?' ? '' : qs}`, { method: opts.method ?? 'GET', headers, body, signal: opts.signal })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check that the backend is running and try again.')
  }

  if (res.status === 401 && !retried) {
    // Token expired or user vanished (e.g. database reset): start over with a fresh guest, once.
    setToken(null)
    await bootstrapGuest()
    return request<T>(path, opts, true)
  }
  if (!res.ok) throw await toApiError(res)
  if (opts.as === 'blob') return (await res.blob()) as T
  if (res.status === 204 || opts.as === 'none') return undefined as T
  return (await res.json()) as T
}

export function wsUrl(token: string): string {
  const base = API_BASE
    ? API_BASE.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  return `${base}/api/v1/ws/chat?token=${encodeURIComponent(token)}`
}
