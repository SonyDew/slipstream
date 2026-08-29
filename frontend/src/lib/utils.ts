import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge conditional class names, with later Tailwind utilities winning. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

/** Human-readable byte size. Returns an em dash for unknown values. */
export function formatBytes(bytes: number | null | undefined, precision?: number): string {
  if (bytes === null || bytes === undefined || bytes <= 0 || !Number.isFinite(bytes)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** index
  const digits = precision ?? (index >= 2 ? 1 : 0)
  return `${value.toFixed(digits)} ${units[index]}`
}

/** Bytes per second as a transfer rate. */
export function formatSpeed(bytesPerSecond: number | null | undefined): string {
  if (!bytesPerSecond || bytesPerSecond <= 0) return ''
  return `${formatBytes(bytesPerSecond)}/s`
}

/** Seconds as m:ss or h:mm:ss. */
export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0 || !Number.isFinite(seconds)) return '—'
  const total = Math.floor(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  }
  return `${minutes}:${String(secs).padStart(2, '0')}`
}

/** Short "time remaining" phrasing for a progress bar. */
export function formatEta(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0 || !Number.isFinite(seconds)) return ''
  if (seconds < 60) return `${Math.ceil(seconds)}s left`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m left`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m left`
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 60 * 60 * 24 * 365],
  ['month', 60 * 60 * 24 * 30],
  ['week', 60 * 60 * 24 * 7],
  ['day', 60 * 60 * 24],
  ['hour', 60 * 60],
  ['minute', 60],
  ['second', 1],
]

/** "3 minutes ago" style formatting, locale-aware. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'

  const deltaSeconds = (date.getTime() - Date.now()) / 1000
  const absolute = Math.abs(deltaSeconds)
  if (absolute < 45) return 'just now'

  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  for (const [unit, secondsInUnit] of RELATIVE_UNITS) {
    if (absolute >= secondsInUnit || unit === 'second') {
      return formatter.format(Math.round(deltaSeconds / secondsInUnit), unit)
    }
  }
  return 'just now'
}

/** Absolute date/time for tooltips and tables. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** Thousands separators. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString()
}

/** Compact counts for stat tiles: 12.3K, 4.5M. */
export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(
    value,
  )
}

/** Milliseconds as a short duration for admin tables. */
export function formatMillis(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return formatDuration(ms / 1000)
}

/* -------------------------------------------------------------------------- */
/* Misc helpers                                                                */
/* -------------------------------------------------------------------------- */

/** Truncate to a character budget without cutting mid-word where avoidable. */
export function truncate(text: string, limit: number): string {
  if (text.length <= limit) return text
  const slice = text.slice(0, limit)
  const lastSpace = slice.lastIndexOf(' ')
  return `${(lastSpace > limit * 0.6 ? slice.slice(0, lastSpace) : slice).trimEnd()}…`
}

/** Extract a hostname for display, tolerating malformed input. */
export function hostnameOf(url: string): string {
  try {
    return new URL(url.includes('://') ? url : `https://${url}`).hostname.replace(/^www\./, '')
  } catch {
    return url.slice(0, 40)
  }
}

/** Cheap plausibility check used to enable the Analyse button. */
export function looksLikeUrl(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed.length < 4 || /\s/.test(trimmed)) return false
  // Either an explicit scheme, or something with a dot that could be a host.
  return /^https?:\/\/.+/i.test(trimmed) || /^[\w-]+(\.[\w-]+)+(\/.*)?$/i.test(trimmed)
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

/** Copy text, returning whether it worked. Falls back for insecure contexts. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}

/** Read the clipboard for the Paste button. Returns null when unavailable. */
export async function readClipboard(): Promise<string | null> {
  try {
    if (navigator.clipboard?.readText && window.isSecureContext) {
      return await navigator.clipboard.readText()
    }
  } catch {
    /* permission denied or unsupported */
  }
  return null
}

/** Status → semantic colour classes, shared by badges across the app. */
export function statusTone(status: string): string {
  switch (status) {
    case 'ready':
      return 'bg-success/10 text-success border-success/20'
    case 'failed':
      return 'bg-destructive/10 text-destructive border-destructive/20'
    case 'cancelled':
    case 'expired':
      return 'bg-muted text-muted-foreground border-border'
    case 'queued':
      return 'bg-muted text-muted-foreground border-border'
    default:
      return 'bg-primary/10 text-primary border-primary/20'
  }
}

export const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  analyzing: 'Analysing',
  downloading: 'Downloading',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
  expired: 'Expired',
  cancelled: 'Cancelled',
}

export const MEDIA_TYPE_LABELS: Record<string, string> = {
  video: 'Video',
  audio: 'Audio',
  image: 'Image',
  image_set: 'Photo set',
  unknown: 'Unknown',
}
