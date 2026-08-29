/** HTTP client.
 *
 * Everything goes through one `request` function so that CSRF, cookie handling
 * and error normalisation happen in exactly one place.
 *
 * Auth uses an HttpOnly session cookie — no token is ever stored in
 * localStorage. The CSRF token lives in a readable cookie and is echoed back in
 * the `X-CSRF-Token` header (double-submit), which is why it must be readable.
 */

import type {
  AdminActiveJob,
  AdminDownload,
  AdminStats,
  AdminUser,
  Analysis,
  AuditEntry,
  DownloadMode,
  HealthReport,
  HistoryItem,
  Job,
  Paginated,
  PublicConfig,
  SettingSpec,
  User,
} from './types'

/** A failure the UI can present directly to the user. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly retryable: boolean
  readonly meta: Record<string, unknown>

  constructor(
    code: string,
    message: string,
    status: number,
    retryable = false,
    meta: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryable = retryable
    this.meta = meta
  }

  /** Field-level messages from a 422, when present. */
  get fieldErrors(): Record<string, string> {
    const fields = this.meta.fields
    return fields && typeof fields === 'object' ? (fields as Record<string, string>) : {}
  }

  get retryAfterSeconds(): number | null {
    const value = this.meta.retry_after
    return typeof value === 'number' ? value : null
  }
}

const CSRF_COOKIE = 'slipstream_csrf'

function readCookie(name: string): string {
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1')}=([^;]*)`),
  )
  return match ? decodeURIComponent(match[1]) : ''
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  /** Milliseconds before the request is aborted. 0 disables the timeout. */
  timeout?: number
  query?: Record<string, string | number | boolean | undefined | null>
}

const DEFAULT_TIMEOUT = 30_000
/** Extraction can legitimately take a while on a slow source. */
const ANALYZE_TIMEOUT = 180_000

function buildUrl(path: string, query?: RequestOptions['query']): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, timeout = DEFAULT_TIMEOUT } = options

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  // Only state-changing requests need the CSRF echo.
  if (method !== 'GET') {
    const csrf = readCookie(CSRF_COOKIE)
    if (csrf) headers['X-CSRF-Token'] = csrf
  }

  const controller = new AbortController()
  const timer = timeout > 0 ? window.setTimeout(() => controller.abort(), timeout) : undefined

  // Honour a caller-supplied signal as well as our timeout.
  if (options.signal) {
    if (options.signal.aborted) controller.abort()
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      // Send and accept cookies; the session cookie is HttpOnly.
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (error) {
    if (timer) window.clearTimeout(timer)
    if (error instanceof DOMException && error.name === 'AbortError') {
      // Distinguish "we gave up waiting" from "caller cancelled".
      if (options.signal?.aborted) throw error
      throw new ApiError(
        'network_timeout',
        'The request took too long. Please try again.',
        0,
        true,
      )
    }
    throw new ApiError(
      'network_error',
      'Could not reach the server. Check your connection and try again.',
      0,
      true,
    )
  }
  if (timer) window.clearTimeout(timer)

  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')

  if (!response.ok) {
    if (isJson) {
      const payload = (await response.json().catch(() => null)) as
        | { error?: { code?: string; message?: string; retryable?: boolean; meta?: unknown } }
        | null
      const err = payload?.error
      throw new ApiError(
        err?.code || 'error',
        err?.message || 'Something went wrong.',
        response.status,
        Boolean(err?.retryable),
        (err?.meta as Record<string, unknown>) || {},
      )
    }
    throw new ApiError(
      'error',
      `Request failed (${response.status}).`,
      response.status,
      response.status >= 500,
    )
  }

  if (!isJson) return undefined as T
  return (await response.json()) as T
}

/* -------------------------------------------------------------------------- */
/* Public API surface                                                          */
/* -------------------------------------------------------------------------- */

export const api = {
  /* -- system ------------------------------------------------------------- */
  config: () => request<PublicConfig>('/api/config'),
  health: () => request<HealthReport>('/api/health'),
  version: () =>
    request<{ version: string; name: string; commit: string; built_at: string }>('/api/version'),

  /* -- auth --------------------------------------------------------------- */
  me: () => request<{ user: User | null; csrf_token: string | null }>('/api/auth/me'),

  login: (username: string, password: string) =>
    request<{ user: User; csrf_token: string }>('/api/auth/login', {
      method: 'POST',
      body: { username, password },
    }),

  register: (username: string, email: string, password: string) =>
    request<{ user: User; csrf_token: string }>('/api/auth/register', {
      method: 'POST',
      body: { username, email, password },
    }),

  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  logoutEverywhere: () => request<void>('/api/auth/logout-all', { method: 'POST' }),

  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>('/api/auth/change-password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  /* -- media -------------------------------------------------------------- */
  analyze: (url: string, signal?: AbortSignal) =>
    request<Analysis>('/api/media/analyze', {
      method: 'POST',
      body: { url },
      timeout: ANALYZE_TIMEOUT,
      signal,
    }),

  platforms: () => request<{ platforms: PublicConfig['platforms'] }>('/api/media/platforms'),

  createDownload: (payload: {
    url: string
    mode: DownloadMode
    quality: string
    container: string
    image_indexes?: number[] | null
  }) =>
    request<{ job_id: string; status: string; poll_url: string }>('/api/download', {
      method: 'POST',
      body: payload,
      timeout: ANALYZE_TIMEOUT,
    }),

  job: (jobId: string, signal?: AbortSignal) =>
    request<Job>(`/api/jobs/${encodeURIComponent(jobId)}`, { signal, timeout: 15_000 }),

  cancelJob: (jobId: string) =>
    request<{ cancelled: boolean; status: string }>(
      `/api/jobs/${encodeURIComponent(jobId)}`,
      { method: 'DELETE' },
    ),

  /** The browser performs the actual transfer; this is just the URL. */
  fileUrl: (jobId: string) => `/api/jobs/${encodeURIComponent(jobId)}/file`,

  /* -- history ------------------------------------------------------------ */
  history: (page = 1, perPage = 20) =>
    request<Paginated<HistoryItem>>('/api/history', {
      query: { page, per_page: perPage },
    }),

  clearHistory: () => request<{ deleted: number }>('/api/history', { method: 'DELETE' }),

  deleteHistoryItem: (id: number) =>
    request<{ deleted: number }>(`/api/history/${id}`, { method: 'DELETE' }),

  /* -- admin -------------------------------------------------------------- */
  admin: {
    stats: () => request<AdminStats>('/api/admin/stats'),

    users: (params: {
      q?: string
      role?: string
      active?: string
      page?: number
      per_page?: number
    }) => request<Paginated<AdminUser>>('/api/admin/users', { query: params }),

    user: (id: number) => request<AdminUser>(`/api/admin/users/${id}`),

    updateUser: (
      id: number,
      changes: { is_active?: boolean; role?: 'user' | 'admin'; new_password?: string },
    ) => request<AdminUser & { updated: boolean }>(`/api/admin/users/${id}`, {
      method: 'PATCH',
      body: changes,
    }),

    deleteUser: (id: number) =>
      request<{ deleted: boolean }>(`/api/admin/users/${id}`, { method: 'DELETE' }),

    createUser: (payload: {
      username: string
      email: string
      password: string
      role: 'user' | 'admin'
    }) => request<AdminUser>('/api/admin/users', { method: 'POST', body: payload }),

    downloads: (params: {
      q?: string
      platform?: string
      status?: string
      page?: number
      per_page?: number
    }) => request<Paginated<AdminDownload>>('/api/admin/downloads', { query: params }),

    activeJobs: () => request<{ items: AdminActiveJob[] }>('/api/admin/jobs'),

    cancelJob: (jobId: string) =>
      request<{ cancelled: boolean; status: string }>(
        `/api/admin/jobs/${encodeURIComponent(jobId)}`,
        { method: 'DELETE' },
      ),

    audit: (params: { action?: string; page?: number; per_page?: number }) =>
      request<Paginated<AuditEntry> & { actions: string[] }>('/api/admin/audit', {
        query: params,
      }),

    settings: () => request<{ settings: SettingSpec[] }>('/api/admin/settings'),

    updateSettings: (settings: Record<string, unknown>) =>
      request<{ settings: SettingSpec[]; changed: string[] }>('/api/admin/settings', {
        method: 'PATCH',
        body: { settings },
      }),

    cleanup: () =>
      request<{ report: Record<string, number> }>('/api/admin/cleanup', { method: 'POST' }),

    purgeHistory: (olderThanDays: number) =>
      request<{ deleted: number }>('/api/admin/history', {
        method: 'DELETE',
        query: { older_than_days: olderThanDays },
      }),
  },
}

export { request }
