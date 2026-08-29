import { Ban, Loader2, RefreshCw } from 'lucide-react'
import { useCallback, useState } from 'react'

import { PlatformIcon, platformMeta } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { EmptyState, ErrorCard } from '@/components/ui/feedback'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { useAsyncData } from '@/hooks/use-async-data'
import { usePolling } from '@/hooks/use-polling'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { AdminActiveJob } from '@/lib/types'
import { MEDIA_TYPE_LABELS, STATUS_LABELS, cn, formatRelative, statusTone } from '@/lib/utils'

/** Live view, so it polls faster than the dashboard. */
const POLL_MS = 4000

export function AdminJobsPage() {
  const toast = useToast()
  const { mustChangePassword } = useAuth()

  const fetcher = useCallback(() => api.admin.activeJobs(), [])
  const { data, error, loading, reload } = useAsyncData<{ items: AdminActiveJob[] }>(fetcher)

  const [cancelTarget, setCancelTarget] = useState<AdminActiveJob | null>(null)
  const [cancelling, setCancelling] = useState(false)

  usePolling(() => reload(true), POLL_MS)

  const canMutate = !mustChangePassword
  const jobs = data?.items ?? []

  const confirmCancel = async () => {
    if (!cancelTarget) return
    setCancelling(true)
    try {
      await api.admin.cancelJob(cancelTarget.id)
      toast.info('Job cancelled', platformMeta(cancelTarget.platform).label)
      setCancelTarget(null)
      await reload(true)
    } catch (caught) {
      toast.error(
        'Could not cancel the job',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setCancelling(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            Active jobs
            {jobs.length > 0 && <Badge variant="default">{jobs.length}</Badge>}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Queued and in-flight work, refreshed automatically every few seconds.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void reload()} loading={loading}>
          {!loading && <RefreshCw aria-hidden />}
          Refresh
        </Button>
      </div>

      {error && (
        <ErrorCard
          title="Could not load the queue"
          message={error.message}
          code={error.code}
          onRetry={() => void reload()}
          retrying={loading}
        />
      )}

      {loading && !data ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-xl" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState
          icon={Loader2}
          title="The queue is empty"
          description="Nothing is being analysed, downloaded or processed right now."
        />
      ) : (
        <ul className="space-y-3">
          {jobs.map((job) => (
            <li key={job.id} className="rounded-xl border bg-card p-4 shadow-soft">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <PlatformIcon platform={job.platform} />
                    <p className="truncate font-medium" title={job.title ?? undefined}>
                      {job.title || 'Analysing…'}
                    </p>
                    <span
                      className={cn(
                        'shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium',
                        statusTone(job.status),
                      )}
                    >
                      {STATUS_LABELS[job.status] ?? job.status}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {job.source_domain} · {MEDIA_TYPE_LABELS[job.media_type] ?? job.media_type} ·{' '}
                    {job.quality} · {job.is_guest ? 'guest' : `account #${job.user_id}`} · queued{' '}
                    {formatRelative(job.created_at)}
                  </p>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCancelTarget(job)}
                  disabled={!canMutate}
                  title={canMutate ? 'Cancel this job' : 'Change your bootstrap password first'}
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  <Ban aria-hidden />
                  Cancel
                </Button>
              </div>

              <div className="mt-3 flex items-center gap-3">
                <Progress
                  value={job.status === 'queued' ? null : job.progress}
                  className="flex-1"
                />
                <span className="w-24 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {job.status === 'queued' ? 'waiting' : `${job.progress}%`}
                </span>
              </div>

              {job.progress_label && (
                <p className="mt-1.5 truncate text-xs text-muted-foreground">
                  {job.progress_label}
                </p>
              )}

              <p className="mt-2 font-mono text-[11px] text-muted-foreground/70">{job.id}</p>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={cancelTarget !== null}
        onClose={() => setCancelTarget(null)}
        onConfirm={() => void confirmCancel()}
        title="Cancel this job?"
        description="The download stops and any partial file is discarded. The user sees the job as cancelled."
        confirmLabel="Cancel job"
        cancelLabel="Keep running"
        loading={cancelling}
      />
    </div>
  )
}
