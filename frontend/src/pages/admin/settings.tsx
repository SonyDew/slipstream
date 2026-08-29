import { AlertCircle, RotateCcw, Save, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { platformMeta } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, ErrorCard } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'
import { useAsyncData } from '@/hooks/use-async-data'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { SettingSpec } from '@/lib/types'
import { cn, formatBytes, formatDuration } from '@/lib/utils'

/** Group order and copy. The backend supplies the group name on each spec; this
 *  only decides how they are presented. */
const GROUPS: { key: string; title: string; description: string }[] = [
  {
    key: 'access',
    title: 'Access',
    description: 'Who may use this server and whether it is open at all.',
  },
  {
    key: 'platforms',
    title: 'Platforms',
    description: 'Restrict which sources users may download from.',
  },
  {
    key: 'limits',
    title: 'Limits',
    description: 'Ceilings that protect disk and CPU on a small server.',
  },
  {
    key: 'privacy',
    title: 'Privacy',
    description: 'How long download history is kept.',
  },
  {
    key: 'rate_limits',
    title: 'Rate limits',
    description: 'Requests allowed per hour. Zero means unlimited.',
  },
]

type Draft = Record<string, unknown>

export function AdminSettingsPage() {
  const toast = useToast()
  const { config, refreshConfig, mustChangePassword } = useAuth()

  const fetcher = useCallback(() => api.admin.settings(), [])
  const { data, error, loading, reload } = useAsyncData<{ settings: SettingSpec[] }>(fetcher)

  const [draft, setDraft] = useState<Draft>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [cleaning, setCleaning] = useState(false)

  // Memoised so the fresh `[]` fallback does not invalidate dependent memos on
  // every render.
  const specs = useMemo(() => data?.settings ?? [], [data])
  const canMutate = !mustChangePassword

  // Reset the draft whenever the server's view of the settings changes.
  useEffect(() => {
    if (data) {
      setDraft({})
      setFieldErrors({})
    }
  }, [data])

  const currentValue = useCallback(
    (spec: SettingSpec) => (spec.key in draft ? draft[spec.key] : spec.value),
    [draft],
  )

  const dirtyKeys = useMemo(
    () =>
      specs
        .filter((spec) => spec.key in draft && !equal(draft[spec.key], spec.value))
        .map((spec) => spec.key),
    [specs, draft],
  )

  const set = (key: string, value: unknown) => {
    setDraft((current) => ({ ...current, [key]: value }))
    setFieldErrors((current) => {
      if (!(key in current)) return current
      const next = { ...current }
      delete next[key]
      return next
    })
  }

  const save = async () => {
    if (dirtyKeys.length === 0) return
    setSaving(true)
    setSaveError(null)
    setFieldErrors({})
    try {
      const payload: Record<string, unknown> = {}
      for (const key of dirtyKeys) payload[key] = draft[key]

      const result = await api.admin.updateSettings(payload)
      toast.success(
        result.changed.length > 0 ? 'Settings saved' : 'No changes to apply',
        result.changed.length > 0 ? result.changed.join(', ') : undefined,
      )
      setDraft({})
      await reload(true)
      // Public config drives banners and the platform list elsewhere in the UI.
      await refreshConfig()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setSaveError(caught.message)
        setFieldErrors(caught.fieldErrors)
      } else {
        setSaveError('Could not save the settings. Please try again.')
      }
    } finally {
      setSaving(false)
    }
  }

  const runCleanup = async () => {
    setCleaning(true)
    try {
      const { report } = await api.admin.cleanup()
      const summary = Object.entries(report)
        .filter(([, count]) => count > 0)
        .map(([name, count]) => `${name.replace(/_/g, ' ')}: ${count}`)
        .join(' · ')
      toast.success('Cleanup finished', summary || 'Nothing needed removing.')
    } catch (caught) {
      toast.error(
        'Cleanup failed',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setCleaning(false)
    }
  }

  const knownPlatforms = config?.platforms ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Settings</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Overrides stored in the database. Anything left at its default follows the
            environment configuration.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDraft({})
              setFieldErrors({})
              setSaveError(null)
            }}
            disabled={dirtyKeys.length === 0 || saving}
          >
            <RotateCcw aria-hidden />
            Discard
          </Button>
          <Button
            variant="brand"
            size="sm"
            onClick={() => void save()}
            disabled={!canMutate || dirtyKeys.length === 0}
            loading={saving}
          >
            {!saving && <Save aria-hidden />}
            Save
            {dirtyKeys.length > 0 && ` (${dirtyKeys.length})`}
          </Button>
        </div>
      </div>

      {!canMutate && (
        <Alert tone="warning" icon={AlertCircle} title="Read-only">
          Change your own bootstrap password before editing server settings.
        </Alert>
      )}

      {saveError && (
        <Alert tone="destructive" icon={AlertCircle} title="Could not save">
          {saveError}
        </Alert>
      )}

      {error && (
        <ErrorCard
          title="Could not load settings"
          message={error.message}
          code={error.code}
          onRetry={() => void reload()}
          retrying={loading}
        />
      )}

      {loading && !data ? (
        <div className="space-y-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      ) : (
        GROUPS.map((group) => {
          const members = specs.filter((spec) => spec.group === group.key)
          if (members.length === 0) return null
          return (
            <section key={group.key} className="rounded-xl border bg-card p-5 shadow-soft">
              <h3 className="font-medium">{group.title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{group.description}</p>

              <div className="mt-5 divide-y">
                {members.map((spec) => (
                  <SettingRow
                    key={spec.key}
                    spec={spec}
                    value={currentValue(spec)}
                    dirty={dirtyKeys.includes(spec.key)}
                    error={fieldErrors[spec.key]}
                    disabled={!canMutate || saving}
                    onChange={(value) => set(spec.key, value)}
                    platforms={knownPlatforms}
                  />
                ))}
              </div>
            </section>
          )
        })
      )}

      <section className="rounded-xl border bg-card p-5 shadow-soft">
        <h3 className="font-medium">Maintenance</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Cleanup removes expired files, stale jobs and history beyond the retention window. It
          also runs on a schedule; this button just runs it now.
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-4"
          onClick={() => void runCleanup()}
          disabled={!canMutate}
          loading={cleaning}
        >
          {!cleaning && <Sparkles aria-hidden />}
          Run cleanup now
        </Button>
      </section>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Rows                                                                        */
/* -------------------------------------------------------------------------- */

interface SettingRowProps {
  spec: SettingSpec
  value: unknown
  dirty: boolean
  error?: string
  disabled: boolean
  onChange: (value: unknown) => void
  platforms: { platform: string; label: string }[]
}

function SettingRow({
  spec,
  value,
  dirty,
  error,
  disabled,
  onChange,
  platforms,
}: SettingRowProps) {
  const inputId = `setting-${spec.key}`

  return (
    <div className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor={inputId} className="font-medium">
            {humanKey(spec.key)}
          </Label>
          {dirty && <Badge variant="warning">Unsaved</Badge>}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{spec.description}</p>
        {error && <p className="mt-1.5 text-sm text-destructive">{error}</p>}
      </div>

      <div className="shrink-0 sm:w-64">
        {spec.type === 'bool' ? (
          <div className="flex items-center gap-3 sm:justify-end">
            <Switch
              id={inputId}
              checked={Boolean(value)}
              onCheckedChange={onChange}
              disabled={disabled}
            />
            <span className="text-sm text-muted-foreground">
              {value ? 'Enabled' : 'Disabled'}
            </span>
          </div>
        ) : spec.type === 'int' ? (
          <div className="space-y-1.5">
            <Input
              id={inputId}
              type="number"
              inputMode="numeric"
              value={String(value ?? '')}
              min={spec.minimum ?? undefined}
              max={spec.maximum ?? undefined}
              onChange={(event) => {
                const raw = event.target.value
                onChange(raw === '' ? '' : Number(raw))
              }}
              disabled={disabled}
              invalid={Boolean(error)}
              className="text-right tabular-nums"
            />
            <p className="text-right text-xs text-muted-foreground">
              {intHint(spec, value)}
            </p>
          </div>
        ) : spec.type === 'list' ? (
          <PlatformPicker
            selected={Array.isArray(value) ? (value as string[]) : []}
            platforms={platforms}
            disabled={disabled}
            onChange={onChange}
          />
        ) : (
          <Input
            id={inputId}
            value={String(value ?? '')}
            onChange={(event) => onChange(event.target.value)}
            disabled={disabled}
            invalid={Boolean(error)}
          />
        )}
      </div>
    </div>
  )
}

/** Multi-select for `allowed_platforms`.
 *
 *  An empty list means "everything supported", so that state gets an explicit
 *  affordance rather than looking like an accident.
 */
function PlatformPicker({
  selected,
  platforms,
  disabled,
  onChange,
}: {
  selected: string[]
  platforms: { platform: string; label: string }[]
  disabled: boolean
  onChange: (value: string[]) => void
}) {
  const allowAll = selected.length === 0

  const toggle = (platform: string) => {
    onChange(
      selected.includes(platform)
        ? selected.filter((entry) => entry !== platform)
        : [...selected, platform],
    )
  }

  return (
    <div className="space-y-2">
      <Button
        variant={allowAll ? 'default' : 'outline'}
        size="sm"
        className="w-full"
        onClick={() => onChange([])}
        disabled={disabled || allowAll}
      >
        Allow all platforms
      </Button>
      <div className="flex flex-wrap gap-1.5">
        {platforms.map((entry) => {
          const active = selected.includes(entry.platform)
          return (
            <button
              key={entry.platform}
              type="button"
              onClick={() => toggle(entry.platform)}
              disabled={disabled}
              aria-pressed={active}
              className={cn(
                'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                'disabled:cursor-not-allowed disabled:opacity-50',
                active
                  ? 'border-primary/20 bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              {entry.label || platformMeta(entry.platform).label}
            </button>
          )
        })}
      </div>
      {allowAll && (
        <p className="text-xs text-muted-foreground">
          Nothing selected, so every supported platform is available.
        </p>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

function humanKey(key: string): string {
  const label = key.replace(/_/g, ' ')
  return label.charAt(0).toUpperCase() + label.slice(1)
}

/** Restate a raw number in the unit an operator actually thinks in. */
function intHint(spec: SettingSpec, value: unknown): string {
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number)) return ''

  if (spec.key === 'max_file_size') return formatBytes(number)
  if (spec.key === 'max_video_duration') return formatDuration(number)
  if (spec.key === 'temp_file_ttl') return `${formatDuration(number)} (h:mm:ss)`
  if (spec.key === 'history_retention_days') {
    return number === 0 ? 'History disabled' : `${number} days`
  }
  if (spec.key.startsWith('rate_limit')) {
    return number === 0 ? 'Unlimited' : `${number} per hour`
  }
  if (spec.minimum !== null && spec.maximum !== null) {
    return `${spec.minimum}–${spec.maximum}`
  }
  return ''
}

function equal(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((value, index) => value === b[index])
  }
  return a === b
}
