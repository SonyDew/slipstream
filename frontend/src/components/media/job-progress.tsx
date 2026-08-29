import { CheckCircle2, Download, Loader2, X, XCircle } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button, ExternalButtonLink } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { useToast } from '@/components/ui/toast'
import { ApiError, api } from '@/lib/api'
import type { Job } from '@/lib/types'
import { STATUS_LABELS, cn, formatBytes, formatEta, formatSpeed } from '@/lib/utils'

/** Poll cadence. Fast enough to feel live, slow enough not to hammer SQLite. */
const POLL_INTERVAL_MS = 1200
/** Back off once a job has been running a while — long downloads need no 1s polls. */
const SLOW_POLL_AFTER_MS = 60_000
const SLOW_POLL_INTERVAL_MS = 3000

const ACTIVE_STATUSES = new Set(['queued', 'analyzing', 'downloading', 'processing'])

interface JobProgressProps {
  jobId: string
  /** Called once the job reaches a terminal state. */
  onFinished?: (job: Job) => void
  onDismiss?: () => void
  className?: string
}

/** Live job tracker: polls status, then offers the finished file.
 *
 *  The browser performs the actual transfer via a normal anchor navigation, so
 *  large files never pass through JavaScript memory.
 */
export function JobProgress({ jobId, onFinished, onDismiss, className }: JobProgressProps) {
  const { success: toastSuccess, error: toastError, info: toastInfo } = useToast()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)

  const startedAt = useRef(Date.now())
  const timer = useRef<number>()
  const abort = useRef<AbortController>()
  const notified = useRef(false)

  const stopPolling = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current)
    abort.current?.abort()
  }, [])

  useEffect(() => {
    let cancelled = false
    startedAt.current = Date.now()
    notified.current = false

    const poll = async () => {
      abort.current = new AbortController()
      try {
        const next = await api.job(jobId, abort.current.signal)
        if (cancelled) return

        setJob(next)
        setError(null)

        if (ACTIVE_STATUSES.has(next.status)) {
          const elapsed = Date.now() - startedAt.current
          const delay =
            elapsed > SLOW_POLL_AFTER_MS ? SLOW_POLL_INTERVAL_MS : POLL_INTERVAL_MS
          timer.current = window.setTimeout(poll, delay)
          return
        }

        // Terminal: report once.
        if (!notified.current) {
          notified.current = true
          onFinished?.(next)
          if (next.status === 'ready') {
            toastSuccess('Download ready', next.file_name ?? undefined)
          } else if (next.status === 'failed') {
            toastError('Download failed', next.error_message ?? undefined)
          }
        }
      } catch (caught) {
        if (cancelled) return
        if (caught instanceof DOMException && caught.name === 'AbortError') return

        const message =
          caught instanceof ApiError ? caught.message : 'Lost contact with the server.'
        // A transient network blip should not kill the tracker.
        if (caught instanceof ApiError && caught.retryable) {
          setError(message)
          timer.current = window.setTimeout(poll, SLOW_POLL_INTERVAL_MS)
          return
        }
        setError(message)
      }
    }

    void poll()

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [jobId, onFinished, stopPolling, toastSuccess, toastError])

  const handleCancel = async () => {
    setCancelling(true)
    try {
      await api.cancelJob(jobId)
      toastInfo('Cancelled', 'The download was stopped.')
    } catch (caught) {
      toastError(
        'Could not cancel',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setCancelling(false)
    }
  }

  if (error && !job) {
    return (
      <div className={cn('rounded-xl border border-destructive/25 bg-destructive/5 p-4', className)}>
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  const status = job?.status ?? 'queued'
  const isActive = ACTIVE_STATUSES.has(status)
  const isReady = status === 'ready'
  const isFailed = status === 'failed'
  const isCancelled = status === 'cancelled' || status === 'expired'

  // A queued or analysing job has no meaningful percentage yet.
  const showIndeterminate = status === 'queued' || (status === 'analyzing' && (job?.progress ?? 0) < 3)

  return (
    <div
      className={cn(
        'animate-fade-up rounded-2xl border border-l-4 border-l-primary bg-card p-4 shadow-card transition-colors sm:p-5',
        isReady && 'border-success/30 border-l-success bg-success/[0.035]',
        isFailed && 'border-destructive/30 border-l-destructive bg-destructive/[0.035]',
        className,
      )}
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0">
          {isActive && <Loader2 className="size-5 animate-spin text-primary" aria-hidden />}
          {isReady && <CheckCircle2 className="size-5 text-success" aria-hidden />}
          {isFailed && <XCircle className="size-5 text-destructive" aria-hidden />}
          {isCancelled && <X className="size-5 text-muted-foreground" aria-hidden />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium">
              {isReady
                ? 'Ready to download'
                : isFailed
                  ? 'Download failed'
                  : isCancelled
                    ? STATUS_LABELS[status]
                    : (job?.progress_label || STATUS_LABELS[status] || 'Working')}
            </p>
            {isActive && !showIndeterminate && (
              <p className="font-mono text-xs tabular-nums text-muted-foreground">
                {job?.progress ?? 0}%
              </p>
            )}
          </div>

          {job?.file_name && (
            <p className="mt-0.5 truncate text-xs text-muted-foreground" title={job.file_name}>
              {job.file_name}
            </p>
          )}

          {(isActive || isReady) && (
            <Progress
              value={showIndeterminate ? null : (job?.progress ?? 0)}
              tone={isReady ? 'success' : 'brand'}
              className="mt-3"
            />
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {isActive && job?.speed_bps ? <span>{formatSpeed(job.speed_bps)}</span> : null}
            {isActive && job?.eta_seconds ? <span>{formatEta(job.eta_seconds)}</span> : null}
            {job?.file_size ? <span>{formatBytes(job.file_size)}</span> : null}
            {error && <span className="text-warning">Reconnecting…</span>}
          </div>

          {isFailed && job?.error_message && (
            <p className="mt-2 text-sm text-destructive">{job.error_message}</p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {isReady && job?.download_url && (
              // A real anchor, not a button with a click handler: the browser
              // streams the file itself and honours Content-Disposition, so the
              // bytes never pass through JavaScript.
              <ExternalButtonLink
                href={api.fileUrl(job.id)}
                download
                variant="brand"
                size="sm"
              >
                <Download aria-hidden />
                Save file
              </ExternalButtonLink>
            )}
            {isActive && (
              <Button variant="outline" size="sm" onClick={handleCancel} loading={cancelling}>
                Cancel
              </Button>
            )}
            {!isActive && onDismiss && (
              <Button variant="ghost" size="sm" onClick={onDismiss}>
                Dismiss
              </Button>
            )}
          </div>

          {isReady && job?.expires_at && (
            <p className="mt-2 text-xs text-muted-foreground">
              This link expires automatically — save the file soon.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
