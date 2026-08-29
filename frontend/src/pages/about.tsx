import { Activity, CheckCircle2, Cpu, Database, FileCode2, Scale, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Logo } from '@/components/layout/logo'
import { Badge } from '@/components/ui/badge'
import { ButtonLink } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { HealthReport } from '@/lib/types'
import { cn } from '@/lib/utils'

export function AboutPage() {
  const { config } = useAuth()
  const [health, setHealth] = useState<HealthReport | null>(null)
  const [version, setVersion] = useState<{ version: string; commit: string; built_at: string } | null>(
    null,
  )
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void Promise.allSettled([api.health(), api.version()]).then(([healthResult, versionResult]) => {
      if (cancelled) return
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
      if (versionResult.status === 'fulfilled') setVersion(versionResult.value)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const statusTone =
    health?.status === 'healthy'
      ? 'success'
      : health?.status === 'degraded'
        ? 'warning'
        : 'destructive'

  return (
    <div className="container max-w-3xl py-12">
      <header className="mb-10 text-center">
        <Logo className="justify-center" />
        <h1 className="mt-5 text-2xl font-semibold tracking-tight sm:text-3xl">
          About this deployment
        </h1>
        <p className="mt-3 text-muted-foreground">
          Version information and live component status for the server you are using.
        </p>
      </header>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode2 className="size-4 text-muted-foreground" aria-hidden />
              Version
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <Detail label="Application" value={config?.version ?? version?.version ?? '—'} />
            <Detail
              label="Environment"
              value={config?.environment ?? '—'}
            />
            <Detail
              label="Build"
              value={
                version?.commit && version.commit !== 'unknown' ? version.commit : 'local build'
              }
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Activity className="size-4 text-muted-foreground" aria-hidden />
              Service status
            </CardTitle>
            {loading ? (
              <Skeleton className="h-5 w-20 rounded-full" />
            ) : (
              <Badge variant={statusTone}>{health?.status ?? 'unknown'}</Badge>
            )}
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-12 w-full rounded-lg" />
                ))}
              </div>
            ) : health ? (
              <ul className="divide-y rounded-lg border">
                {Object.entries(health.components).map(([name, detail]) => {
                  const status = String(detail.status ?? 'unknown')
                  const ok = status === 'ok'
                  return (
                    <li key={name} className="flex items-center justify-between gap-4 p-3.5">
                      <span className="flex items-center gap-2.5">
                        <ComponentIcon name={name} />
                        <span className="text-sm font-medium capitalize">{name}</span>
                      </span>
                      <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        {'version' in detail && detail.version ? (
                          <span className="hidden max-w-[16rem] truncate font-mono sm:inline">
                            {String(detail.version)}
                          </span>
                        ) : null}
                        {'workers' in detail ? (
                          <span className="font-mono">{String(detail.workers)} workers</span>
                        ) : null}
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 font-medium',
                            ok ? 'text-success' : 'text-warning',
                          )}
                        >
                          {ok ? (
                            <CheckCircle2 className="size-3.5" aria-hidden />
                          ) : (
                            <XCircle className="size-3.5" aria-hidden />
                          )}
                          {status}
                        </span>
                      </span>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Status is unavailable.</p>
            )}

            {health?.components.ffmpeg?.status !== 'ok' && !loading && (
              <p className="mt-4 text-sm text-muted-foreground">
                FFmpeg is not installed on this server, so MP3 conversion and qualities
                that need stream merging are unavailable.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Scale className="size-4 text-muted-foreground" aria-hidden />
              Legal
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              Slipstream processes only publicly accessible media. It does not bypass
              DRM, paywalls, private-account restrictions, age verification or CAPTCHAs.
            </p>
            <p>
              You are responsible for holding the rights to what you download and for
              complying with each platform&apos;s terms and your local copyright law.
            </p>
            <div className="flex flex-wrap gap-3 pt-1">
              <ButtonLink to="/legal" variant="outline" size="sm">
                Acceptable use
              </ButtonLink>
              <ButtonLink to="/privacy" variant="outline" size="sm">
                Privacy
              </ButtonLink>
            </div>
          </CardContent>
        </Card>

        <p className="text-center text-sm text-muted-foreground">
          Looking for usage instructions? See the{' '}
          <Link to="/docs" className="font-medium text-primary underline underline-offset-2">
            documentation
          </Link>
          .
        </p>
      </div>
    </div>
  )
}

function ComponentIcon({ name }: { name: string }) {
  const className = 'size-4 text-muted-foreground'
  if (name === 'database') return <Database className={className} aria-hidden />
  if (name === 'queue') return <Cpu className={className} aria-hidden />
  return <Activity className={className} aria-hidden />
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1.5 truncate font-mono text-sm">{value}</p>
    </div>
  )
}
