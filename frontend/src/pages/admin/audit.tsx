import { ClipboardList, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ErrorCard } from '@/components/ui/feedback'
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
import { useAsyncData } from '@/hooks/use-async-data'
import { api } from '@/lib/api'
import type { AuditEntry, Paginated } from '@/lib/types'
import { cn, formatDateTime, formatRelative } from '@/lib/utils'

const PER_PAGE = 50

/** Actions that change who can do what get a louder treatment. */
const SENSITIVE_ACTIONS = new Set([
  'USER_DELETED',
  'ROLE_CHANGED',
  'PASSWORD_RESET',
  'HISTORY_CLEARED',
  'MAINTENANCE_ENABLED',
])

function actionLabel(action: string): string {
  return action
    .toLowerCase()
    .split('_')
    .map((part, index) => (index === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(' ')
}

/** Render `meta` compactly. Values are already scrubbed server-side — the audit
 *  writer never records credentials — so this only has to stay readable. */
function summariseMeta(meta: Record<string, unknown> | null): string | null {
  if (!meta || Object.keys(meta).length === 0) return null

  const parts: string[] = []
  for (const [key, value] of Object.entries(meta)) {
    if (value === null || value === undefined) continue
    if (key === 'changed' && typeof value === 'object') {
      const changed = value as Record<string, { from?: unknown; to?: unknown }>
      for (const [field, delta] of Object.entries(changed)) {
        parts.push(`${field}: ${format(delta?.from)} → ${format(delta?.to)}`)
      }
      continue
    }
    if (key === 'from' || key === 'to') continue
    parts.push(`${key}: ${format(value)}`)
  }

  if ('from' in meta || 'to' in meta) {
    parts.unshift(`${format(meta.from)} → ${format(meta.to)}`)
  }

  return parts.length > 0 ? parts.join(' · ') : null
}

function format(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : 'none'
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function AdminAuditPage() {
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)

  const fetcher = useCallback(
    () => api.admin.audit({ action, page, per_page: PER_PAGE }),
    [action, page],
  )

  const { data, error, loading, reload } =
    useAsyncData<Paginated<AuditEntry> & { actions: string[] }>(fetcher)

  useEffect(() => setPage(1), [action])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Audit log</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Every administrative action, with the account that performed it. Entries are
            append-only and survive deletion of the accounts they mention.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void reload()} loading={loading}>
          {!loading && <RefreshCw aria-hidden />}
          Refresh
        </Button>
      </div>

      <div className="max-w-xs">
        <Label htmlFor="audit-action" className="sr-only">
          Action
        </Label>
        <Select
          id="audit-action"
          value={action}
          onChange={(event) => setAction(event.target.value)}
        >
          <option value="">All actions</option>
          {(data?.actions ?? []).map((value) => (
            <option key={value} value={value}>
              {actionLabel(value)}
            </option>
          ))}
        </Select>
      </div>

      {error && (
        <ErrorCard
          title="Could not load the audit log"
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
              <TH>When</TH>
              <TH>Administrator</TH>
              <TH>Action</TH>
              <TH>Target</TH>
              <TH>Details</TH>
              <TH>IP</TH>
            </TR>
          </THead>
          <TBody>
            {loading && !data ? (
              <TableSkeletonRows rows={12} columns={6} />
            ) : data && data.items.length > 0 ? (
              data.items.map((entry) => {
                const details = summariseMeta(entry.meta)
                return (
                  <TR key={entry.id}>
                    <TD
                      className="whitespace-nowrap text-sm text-muted-foreground"
                      title={formatDateTime(entry.created_at)}
                    >
                      {formatRelative(entry.created_at)}
                    </TD>
                    <TD className="whitespace-nowrap text-sm font-medium">
                      {entry.admin_username}
                      {entry.admin_user_id === null && (
                        <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                          (deleted)
                        </span>
                      )}
                    </TD>
                    <TD>
                      <Badge
                        variant={SENSITIVE_ACTIONS.has(entry.action) ? 'warning' : 'muted'}
                        className="whitespace-nowrap"
                      >
                        {actionLabel(entry.action)}
                      </Badge>
                    </TD>
                    <TD className="text-sm">
                      {entry.target_label || entry.target_id ? (
                        <span className="flex flex-col">
                          <span className="truncate">{entry.target_label || '—'}</span>
                          <span className="truncate text-xs text-muted-foreground">
                            {[entry.target_type, entry.target_id].filter(Boolean).join(' ')}
                          </span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TD>
                    <TD className="max-w-[24rem]">
                      {details ? (
                        <span
                          className="block truncate text-xs text-muted-foreground"
                          title={details}
                        >
                          {details}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TD>
                    <TD
                      className={cn(
                        'whitespace-nowrap font-mono text-xs text-muted-foreground',
                      )}
                    >
                      {entry.ip_address || '—'}
                    </TD>
                  </TR>
                )
              })
            ) : (
              <TableEmptyRow
                colSpan={6}
                message={
                  action
                    ? 'No entries for that action.'
                    : 'No administrative actions recorded yet.'
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

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <ClipboardList className="size-3.5" aria-hidden />
        Passwords and session tokens are never written to this log — only the fact that a reset
        happened.
      </p>
    </div>
  )
}
