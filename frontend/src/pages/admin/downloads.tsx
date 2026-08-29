import { RefreshCw, Search, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { PlatformIcon, platformMeta } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorCard } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import {
  Pagination,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  TableEmptyRow,
  TableSkeletonRows,
  TableWrapper,
} from '@/components/ui/table'
import { useToast } from '@/components/ui/toast'
import { useAsyncData } from '@/hooks/use-async-data'
import { useDebounced } from '@/hooks/use-debounced'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { AdminDownload, Paginated } from '@/lib/types'
import {
  MEDIA_TYPE_LABELS,
  STATUS_LABELS,
  cn,
  formatBytes,
  formatDateTime,
  formatMillis,
  formatRelative,
  statusTone,
} from '@/lib/utils'

const PER_PAGE = 25

const STATUS_OPTIONS = ['ready', 'failed', 'expired', 'cancelled'] as const

/** Retention windows offered by the purge control. */
const PURGE_WINDOWS = [
  { days: 90, label: 'Older than 90 days' },
  { days: 30, label: 'Older than 30 days' },
  { days: 7, label: 'Older than 7 days' },
  { days: 0, label: 'Everything' },
]

export function AdminDownloadsPage() {
  const toast = useToast()
  const { config, mustChangePassword } = useAuth()

  const [query, setQuery] = useState('')
  const [platform, setPlatform] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [purgeDays, setPurgeDays] = useState<number | null>(null)
  const [purging, setPurging] = useState(false)

  const debouncedQuery = useDebounced(query)

  const fetcher = useCallback(
    () =>
      api.admin.downloads({
        q: debouncedQuery.trim(),
        platform,
        status,
        page,
        per_page: PER_PAGE,
      }),
    [debouncedQuery, platform, status, page],
  )

  const { data, error, loading, reload } = useAsyncData<Paginated<AdminDownload>>(fetcher)

  useEffect(() => setPage(1), [debouncedQuery, platform, status])

  const canMutate = !mustChangePassword

  const purge = async () => {
    if (purgeDays === null) return
    setPurging(true)
    try {
      const { deleted } = await api.admin.purgeHistory(purgeDays)
      toast.success(
        deleted > 0 ? `Removed ${deleted.toLocaleString()} entries` : 'Nothing to remove',
        purgeDays > 0 ? `Older than ${purgeDays} days.` : undefined,
      )
      setPurgeDays(null)
      setPage(1)
      await reload(true)
    } catch (caught) {
      toast.error(
        'Could not purge history',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setPurging(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Downloads</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Every recorded download. Source domains are shown rather than full links, because a
            pasted URL can carry share tokens.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void reload()} loading={loading}>
          {!loading && <RefreshCw aria-hidden />}
          Refresh
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
        <div>
          <Label htmlFor="download-search" className="sr-only">
            Search downloads
          </Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              id="download-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search title or author"
              className="pl-9"
              autoComplete="off"
            />
          </div>
        </div>

        <div>
          <Label htmlFor="download-platform" className="sr-only">
            Platform
          </Label>
          <Select
            id="download-platform"
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            className="sm:w-44"
          >
            <option value="">All platforms</option>
            {(config?.platforms ?? []).map((entry) => (
              <option key={entry.platform} value={entry.platform}>
                {entry.label}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <Label htmlFor="download-status" className="sr-only">
            Status
          </Label>
          <Select
            id="download-status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="sm:w-40"
          >
            <option value="">Any status</option>
            {STATUS_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {STATUS_LABELS[value] ?? value}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {error && (
        <ErrorCard
          title="Could not load the download ledger"
          message={error.message}
          code={error.code}
          onRetry={() => void reload()}
          retrying={loading}
        />
      )}

      <TableWrapper>
        <Table>
          <THead>
            <TR>
              <TH>Media</TH>
              <TH>Platform</TH>
              <TH>Account</TH>
              <TH>Output</TH>
              <TH className="text-right">Size</TH>
              <TH className="text-right">Took</TH>
              <TH>Status</TH>
              <TH>When</TH>
            </TR>
          </THead>
          <TBody>
            {loading && !data ? (
              <TableSkeletonRows rows={10} columns={8} />
            ) : data && data.items.length > 0 ? (
              data.items.map((row) => (
                <TR key={row.id}>
                  <TD className="max-w-[22rem]">
                    <p className="truncate font-medium" title={row.title ?? undefined}>
                      {row.title || 'Untitled'}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {row.author ? `${row.author} · ` : ''}
                      {row.source_domain}
                    </p>
                  </TD>
                  <TD>
                    <span className="flex items-center gap-2 whitespace-nowrap text-sm">
                      <PlatformIcon platform={row.platform} />
                      {platformMeta(row.platform).label}
                    </span>
                  </TD>
                  <TD className="whitespace-nowrap text-sm">
                    {row.is_guest ? (
                      <Badge variant="muted">Guest</Badge>
                    ) : (
                      (row.username ?? `#${row.user_id ?? '?'}`)
                    )}
                  </TD>
                  <TD className="whitespace-nowrap text-sm text-muted-foreground">
                    <span className="block">
                      {MEDIA_TYPE_LABELS[row.media_type] ?? row.media_type}
                    </span>
                    <span className="block text-xs">
                      {[row.quality, row.output_format].filter(Boolean).join(' · ') || '—'}
                    </span>
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums">
                    {formatBytes(row.file_size)}
                  </TD>
                  <TD className="whitespace-nowrap text-right tabular-nums text-muted-foreground">
                    {formatMillis(row.duration_ms)}
                  </TD>
                  <TD>
                    <span
                      className={cn(
                        'inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium',
                        statusTone(row.status),
                      )}
                      title={row.error_code ?? undefined}
                    >
                      {STATUS_LABELS[row.status] ?? row.status}
                    </span>
                  </TD>
                  <TD
                    className="whitespace-nowrap text-sm text-muted-foreground"
                    title={formatDateTime(row.created_at)}
                  >
                    {formatRelative(row.created_at)}
                  </TD>
                </TR>
              ))
            ) : (
              <TableEmptyRow
                colSpan={8}
                message={
                  query || platform || status
                    ? 'No downloads match those filters.'
                    : 'No downloads recorded yet.'
                }
              />
            )}
          </TBody>
        </Table>
      </TableWrapper>

      {data && (
        <Pagination
          page={data.page}
          pages={data.pages}
          total={data.total}
          perPage={data.per_page}
          onPageChange={setPage}
        />
      )}

      <section className="rounded-xl border border-destructive/25 bg-destructive/5 p-4">
        <h3 className="text-sm font-semibold">Purge history</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Deletes ledger rows for every account. Files on disk are handled separately by cleanup.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {PURGE_WINDOWS.map((window) => (
            <Button
              key={window.days}
              variant={window.days === 0 ? 'destructive' : 'outline'}
              size="sm"
              onClick={() => setPurgeDays(window.days)}
              disabled={!canMutate || purging}
            >
              <Trash2 aria-hidden />
              {window.label}
            </Button>
          ))}
        </div>
        {!canMutate && (
          <p className="mt-3 text-xs text-muted-foreground">
            Change your bootstrap password before running destructive operations.
          </p>
        )}
      </section>

      <ConfirmDialog
        open={purgeDays !== null}
        onClose={() => setPurgeDays(null)}
        onConfirm={() => void purge()}
        title={purgeDays === 0 ? 'Delete all download history?' : `Delete entries older than ${purgeDays} days?`}
        description="This removes history rows for every account and cannot be undone. The action itself is recorded in the audit log."
        confirmLabel="Delete entries"
        loading={purging}
      />
    </div>
  )
}
