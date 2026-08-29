import {
  Activity,
  CheckCircle2,
  Cpu,
  Database,
  Download,
  HardDrive,
  RefreshCw,
  ShieldAlert,
  TrendingUp,
  Users,
  XCircle,
} from 'lucide-react'
import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { DailyDownloadsChart, PlatformBarChart, StatusPieChart } from '@/components/admin/charts'
import { StatCard } from '@/components/admin/stat-card'
import { PlatformIcon } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorCard } from '@/components/ui/feedback'
import { Skeleton } from '@/components/ui/skeleton'
import { useAsyncData } from '@/hooks/use-async-data'
import { usePolling } from '@/hooks/use-polling'
import { api } from '@/lib/api'
import type { AdminStats } from '@/lib/types'
import {
  MEDIA_TYPE_LABELS,
  cn,
  formatBytes,
  formatNumber,
  formatRelative,
  statusTone,
  truncate,
} from '@/lib/utils'

/** Live figures are worth a periodic refresh, but not a fast poll. */
const REFRESH_MS = 20_000

export function AdminDashboardPage() {
  const fetcher = useCallback(() => api.admin.stats(), [])
  const { data, error, loading, reload } = useAsyncData<AdminStats>(fetcher)

  usePolling(() => reload(true), REFRESH_MS)

  if (error && !data) {
    return (
      <ErrorCard
        title="Could not load the dashboard"
        message={error.message}
        code={error.code}
        onRetry={() => void reload()}
        retrying={loading}
      />
    )
  }

  const users = data?.users
  const downloads = data?.downloads
  const system = data?.system

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold tracking-tight">Overview</h2>
        <Button variant="outline" size="sm" onClick={() => void reload()} loading={loading}>
          {!loading && <RefreshCw aria-hidden />}
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Users"
          value={formatNumber(users?.total ?? null)}
          hint={users ? `${users.active} active · ${users.admins} admin` : undefined}
          icon={Users}
          loading={loading && !data}
        />
        <StatCard
          label="Downloads"
          value={formatNumber(downloads?.total ?? null)}
          hint={downloads ? `${formatNumber(downloads.today)} today` : undefined}
          icon={Download}
          loading={loading && !data}
        />
        <StatCard
          label="Success rate"
          value={downloads ? `${downloads.success_rate}%` : '—'}
          hint={
            downloads
              ? `${formatNumber(downloads.successful)} ok · ${formatNumber(downloads.failed)} failed`
              : undefined
          }
          icon={TrendingUp}
          tone={
            !downloads || downloads.total === 0
              ? 'default'
              : downloads.success_rate >= 90
                ? 'success'
                : downloads.success_rate >= 70
                  ? 'warning'
                  : 'destructive'
          }
          loading={loading && !data}
        />
        <StatCard
          label="Active jobs"
          value={formatNumber(system?.active_jobs ?? null)}
          hint={
            system
              ? `${system.queue.active} running · ${system.queue.queued} queued`
              : undefined
          }
          icon={Activity}
          tone={system && system.active_jobs > 0 ? 'warning' : 'default'}
          loading={loading && !data}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Downloads, last 14 days</CardTitle>
          </CardHeader>
          <CardContent>
            {loading && !data ? (
              <Skeleton className="h-[260px] w-full rounded-lg" />
            ) : data && data.daily.some((day) => day.total > 0) ? (
              <DailyDownloadsChart data={data.daily} />
            ) : (
              <EmptyChart message="No downloads recorded in this window yet." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Outcomes</CardTitle>
          </CardHeader>
          <CardContent>
            {loading && !data ? (
              <Skeleton className="h-[240px] w-full rounded-lg" />
            ) : data && data.statuses.length > 0 ? (
              <StatusPieChart data={data.statuses} />
            ) : (
              <EmptyChart message="Nothing recorded yet." />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Platforms</CardTitle>
          </CardHeader>
          <CardContent>
            {loading && !data ? (
              <Skeleton className="h-[220px] w-full rounded-lg" />
            ) : data && data.platforms.length > 0 ? (
              <PlatformBarChart data={data.platforms} />
            ) : (
              <EmptyChart message="No platform activity yet." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Media types</CardTitle>
          </CardHeader>
          <CardContent>
            {loading && !data ? (
              <Skeleton className="h-[220px] w-full rounded-lg" />
            ) : data && data.media_types.length > 0 ? (
              <ul className="space-y-3">
                {data.media_types.map((row) => {
                  const total = data.media_types.reduce((sum, item) => sum + item.count, 0)
                  const share = total > 0 ? Math.round((row.count / total) * 100) : 0
                  return (
                    <li key={row.media_type}>
                      <div className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="font-medium">
                          {MEDIA_TYPE_LABELS[row.media_type] ?? row.media_type}
                        </span>
                        <span className="tabular-nums text-muted-foreground">
                          {formatNumber(row.count)} · {share}%
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-brand-gradient"
                          style={{ width: `${share}%` }}
                        />
                      </div>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <EmptyChart message="No media recorded yet." />
            )}
          </CardContent>
        </Card>
      </div>

      <SystemPanel system={system} loading={loading && !data} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">Recent downloads</CardTitle>
            <Link
              to="/admin/downloads"
              className="rounded text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              View all
            </Link>
          </CardHeader>
          <CardContent>
            {loading && !data ? (
              <ListSkeleton />
            ) : data && data.recent_downloads.length > 0 ? (
              <ul className="divide-y">
                {data.recent_downloads.map((row) => (
                  <li key={row.id} className="flex items-center gap-3 py-2.5">
                    <PlatformIcon platform={row.platform} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">
                        {row.title ? truncate(row.title, 60) : 'Untitled'}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {formatRelative(row.created_at)}
                        {row.user_id === null ? ' · guest' : ''}
                      </span>
                    </span>
                    <Badge variant="outline" className={cn('shrink-0', statusTone(row.status))}>
                      {row.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No downloads yet.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">Newest accounts</CardTitle>
            <Link
              to="/admin/users"
              className="rounded text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              View all
            </Link>
          </CardHeader>
          <CardContent>
            {loading && !data ? (
              <ListSkeleton />
            ) : data && data.recent_users.length > 0 ? (
              <ul className="divide-y">
                {data.recent_users.map((row) => (
                  <li key={row.id} className="flex items-center gap-3 py-2.5">
                    <span
                      className="grid size-7 shrink-0 place-items-center rounded-md bg-muted text-xs font-semibold"
                      aria-hidden
                    >
                      {row.username.charAt(0).toUpperCase()}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{row.username}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {row.email} · {formatRelative(row.created_at)}
                      </span>
                    </span>
                    {row.role === 'admin' && (
                      <Badge variant="default" className="shrink-0">
                        Admin
                      </Badge>
                    )}
                    {!row.is_active && (
                      <Badge variant="muted" className="shrink-0">
                        Disabled
                      </Badge>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">No accounts yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-[220px] items-center justify-center rounded-lg border border-dashed">
      <p className="px-6 text-center text-sm text-muted-foreground">{message}</p>
    </div>
  )
}

function ListSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, index) => (
        <Skeleton key={index} className="h-10 w-full rounded-lg" />
      ))}
    </div>
  )
}

function SystemPanel({
  system,
  loading,
}: {
  system: AdminStats['system'] | undefined
  loading: boolean
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">System</CardTitle>
      </CardHeader>
      <CardContent>
        {loading || !system ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-20 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SystemTile
              icon={Database}
              label="Database"
              ok={system.database.status === 'ok'}
              primary={system.database.status === 'ok' ? 'Connected' : 'Error'}
              secondary={
                system.database_size_bytes
                  ? formatBytes(system.database_size_bytes)
                  : system.database.detail
              }
            />
            <SystemTile
              icon={Cpu}
              label="Queue"
              ok={system.queue.running}
              primary={system.queue.running ? `${system.queue.workers} workers` : 'Stopped'}
              secondary={`${formatNumber(system.queue.processed)} processed · ${formatNumber(
                system.queue.failed,
              )} failed`}
            />
            <SystemTile
              icon={ShieldAlert}
              label="Toolchain"
              ok={system.extractor.available && system.ffmpeg.available}
              primary={
                system.extractor.available
                  ? `yt-dlp ${system.extractor.version ?? ''}`.trim()
                  : 'Extractor missing'
              }
              secondary={system.ffmpeg.available ? 'FFmpeg available' : 'FFmpeg not installed'}
            />
            <SystemTile
              icon={HardDrive}
              label="Storage"
              ok
              primary={`${formatBytes(system.storage.temp_bytes)} in ${formatNumber(
                system.storage.temp_files,
              )} files`}
              secondary={
                system.storage.disk_free_bytes !== null
                  ? `${formatBytes(system.storage.disk_free_bytes)} free`
                  : 'Free space unknown'
              }
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SystemTile({
  icon: Icon,
  label,
  ok,
  primary,
  secondary,
}: {
  icon: typeof Database
  label: string
  ok: boolean
  primary: string
  secondary: string
}) {
  return (
    <div className="rounded-lg border p-4">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="size-3.5" aria-hidden />
        {label}
      </div>
      <p className="mt-2 truncate text-sm font-medium" title={primary}>
        {primary}
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
        {ok ? (
          <CheckCircle2 className="size-3.5 shrink-0 text-success" aria-hidden />
        ) : (
          <XCircle className="size-3.5 shrink-0 text-warning" aria-hidden />
        )}
        <span className="truncate" title={secondary}>
          {secondary}
        </span>
      </p>
    </div>
  )
}
