import { Clock, Film, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { PlatformIcon } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button, ButtonLink } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { EmptyState, ErrorCard } from '@/components/ui/feedback'
import { Pagination } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { ApiError, api } from '@/lib/api'
import type { HistoryItem, Paginated } from '@/lib/types'
import {
  MEDIA_TYPE_LABELS,
  STATUS_LABELS,
  formatBytes,
  formatRelative,
  statusTone,
} from '@/lib/utils'

const PER_PAGE = 20

export function HistoryPage() {
  const toast = useToast()
  const [data, setData] = useState<Paginated<HistoryItem> | null>(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | null>(null)
  const [clearOpen, setClearOpen] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [removing, setRemoving] = useState<number | null>(null)

  const load = useCallback(
    async (targetPage: number) => {
      setLoading(true)
      setError(null)
      try {
        setData(await api.history(targetPage, PER_PAGE))
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError('unknown', 'Could not load your history.', 0, true),
        )
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    void load(page)
  }, [load, page])

  const clearAll = async () => {
    setClearing(true)
    try {
      const { deleted } = await api.clearHistory()
      toast.success('History cleared', `${deleted} ${deleted === 1 ? 'entry' : 'entries'} removed.`)
      setPage(1)
      await load(1)
    } catch (caught) {
      toast.error(
        'Could not clear history',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setClearing(false)
      setClearOpen(false)
    }
  }

  const removeOne = async (id: number) => {
    setRemoving(id)
    try {
      await api.deleteHistoryItem(id)
      // Step back a page if the last item on this page was removed.
      const nextPage = data && data.items.length === 1 && page > 1 ? page - 1 : page
      setPage(nextPage)
      await load(nextPage)
    } catch (caught) {
      toast.error(
        'Could not remove entry',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setRemoving(null)
    }
  }

  const isEmpty = !loading && !error && (data?.total ?? 0) === 0

  return (
    <div className="container max-w-4xl py-12">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Download history</h1>
          <p className="mt-2 text-muted-foreground">
            Metadata only — the files themselves are deleted after their expiry window.
          </p>
        </div>
        {(data?.total ?? 0) > 0 && (
          <Button variant="outline" onClick={() => setClearOpen(true)}>
            <Trash2 aria-hidden />
            Clear all
          </Button>
        )}
      </header>

      {error && (
        <ErrorCard message={error.message} code={error.code} onRetry={() => void load(page)} />
      )}

      {loading && (
        <ul className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <li key={index} className="flex gap-4 rounded-xl border bg-card p-4">
              <Skeleton className="size-16 shrink-0 rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/3" />
              </div>
            </li>
          ))}
        </ul>
      )}

      {isEmpty && (
        <EmptyState
          icon={Clock}
          title="No downloads yet"
          description="Once you download something while signed in, it will appear here."
          action={
            <ButtonLink to="/" variant="brand">
              Download something
            </ButtonLink>
          }
        />
      )}

      {!loading && data && data.items.length > 0 && (
        <>
          <ul className="space-y-3">
            {data.items.map((item) => (
              <li
                key={item.id}
                className="flex gap-4 rounded-xl border bg-card p-4 shadow-subtle transition-shadow hover:shadow-soft"
              >
                <div className="size-16 shrink-0 overflow-hidden rounded-lg border bg-muted">
                  {item.thumbnail ? (
                    <img
                      src={item.thumbnail}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      referrerPolicy="no-referrer"
                      className="size-full object-cover"
                      onError={(event) => {
                        event.currentTarget.style.display = 'none'
                      }}
                    />
                  ) : (
                    <div className="grid size-full place-items-center">
                      <Film className="size-5 text-muted-foreground/40" aria-hidden />
                    </div>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium" title={item.title ?? undefined}>
                    {item.title || item.source_domain}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <PlatformIcon platform={item.platform} className="size-3.5" />
                      {item.platform}
                    </span>
                    <span>{MEDIA_TYPE_LABELS[item.media_type] ?? item.media_type}</span>
                    {item.quality && <span>{item.quality}</span>}
                    {item.output_format && (
                      <span className="uppercase">{item.output_format}</span>
                    )}
                    {item.file_size ? <span>{formatBytes(item.file_size)}</span> : null}
                    <span>{formatRelative(item.created_at)}</span>
                  </div>
                </div>

                <div className="flex shrink-0 flex-col items-end justify-between gap-2">
                  <Badge variant="outline" className={statusTone(item.status)}>
                    {STATUS_LABELS[item.status] ?? item.status}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => void removeOne(item.id)}
                    loading={removing === item.id}
                    aria-label={`Remove ${item.title || 'entry'} from history`}
                  >
                    {removing !== item.id && <Trash2 aria-hidden />}
                  </Button>
                </div>
              </li>
            ))}
          </ul>

          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            perPage={data.per_page}
            onPageChange={setPage}
          />
        </>
      )}

      <ConfirmDialog
        open={clearOpen}
        onClose={() => setClearOpen(false)}
        onConfirm={clearAll}
        loading={clearing}
        title="Clear download history?"
        description="Every entry will be permanently deleted. This cannot be undone."
        confirmLabel="Delete all"
      />
    </div>
  )
}
