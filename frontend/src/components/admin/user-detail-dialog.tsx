import { AlertCircle, Check, Copy, KeyRound, Shield, ShieldOff } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { PlatformIcon } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Alert, ErrorCard } from '@/components/ui/feedback'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'
import { useAsyncData } from '@/hooks/use-async-data'
import { PasswordField } from '@/pages/login'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { AdminUser } from '@/lib/types'
import {
  MEDIA_TYPE_LABELS,
  STATUS_LABELS,
  cn,
  copyToClipboard,
  formatDateTime,
  formatNumber,
  formatRelative,
  statusTone,
} from '@/lib/utils'

const PASSWORD_ALPHABET = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789-_@#%+='

function generatePassword(length = 20): string {
  const bytes = new Uint32Array(length)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (value) => PASSWORD_ALPHABET[value % PASSWORD_ALPHABET.length]).join('')
}

function passwordAcceptable(password: string, username: string): boolean {
  const classes = [
    /[a-z]/.test(password),
    /[A-Z]/.test(password),
    /\d/.test(password),
    /[^a-zA-Z0-9]/.test(password),
  ].filter(Boolean).length
  return (
    password.length >= 10 &&
    classes >= 3 &&
    !password.toLowerCase().includes(username.trim().toLowerCase())
  )
}

interface UserDetailDialogProps {
  /** Null closes the dialog. */
  userId: number | null
  onClose: () => void
  onChanged: () => void
  canMutate: boolean
}

/** Full account view: status, role, password reset and recent activity. */
export function UserDetailDialog({
  userId,
  onClose,
  onChanged,
  canMutate,
}: UserDetailDialogProps) {
  const toast = useToast()
  const { user: currentUser } = useAuth()

  const fetcher = useCallback(
    () => (userId === null ? Promise.resolve(null) : api.admin.user(userId)),
    [userId],
  )
  const { data, error, loading, reload, setData } = useAsyncData<AdminUser | null>(fetcher, {
    immediate: userId !== null,
  })

  const [password, setPassword] = useState('')
  const [copied, setCopied] = useState(false)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // A newly opened dialog must never inherit the previous account's draft.
  useEffect(() => {
    setPassword('')
    setCopied(false)
    setActionError(null)
    if (userId === null) setData(null)
  }, [userId, setData])

  const isSelf = data?.id === currentUser?.id
  const passwordOk = useMemo(
    () => (data ? passwordAcceptable(password, data.username) : false),
    [password, data],
  )

  const apply = async (
    changes: { is_active?: boolean; role?: 'user' | 'admin'; new_password?: string },
    successTitle: string,
    successDetail?: string,
  ) => {
    if (!data) return
    setSaving(true)
    setActionError(null)
    try {
      await api.admin.updateUser(data.id, changes)
      toast.success(successTitle, successDetail)
      await reload(true)
      onChanged()
      if (changes.new_password) setPassword('')
    } catch (caught) {
      const message =
        caught instanceof ApiError ? caught.message : 'Could not apply that change.'
      setActionError(message)
    } finally {
      setSaving(false)
    }
  }

  const copy = async () => {
    const ok = await copyToClipboard(password)
    setCopied(ok)
    if (!ok) toast.warning('Could not copy', 'Copy the password manually before continuing.')
  }

  return (
    <Dialog
      open={userId !== null}
      onClose={onClose}
      title={data?.username ?? 'Account'}
      description={data ? (data.email || 'No email on file') : undefined}
      className="max-w-2xl"
      footer={
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      }
    >
      {loading && !data ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full rounded-lg" />
          ))}
        </div>
      ) : error ? (
        <ErrorCard
          title="Could not load that account"
          message={error.message}
          code={error.code}
          onRetry={() => void reload()}
          retrying={loading}
        />
      ) : data ? (
        <div className="space-y-6">
          {actionError && (
            <Alert tone="destructive" icon={AlertCircle}>
              {actionError}
            </Alert>
          )}

          {!canMutate && (
            <Alert tone="warning" icon={AlertCircle} title="Read-only">
              Change your own bootstrap password before modifying accounts.
            </Alert>
          )}

          <dl className="grid gap-4 sm:grid-cols-3">
            <Field label="Downloads" value={formatNumber(data.download_count ?? 0)} />
            <Field label="Joined" value={formatDateTime(data.created_at)} />
            <Field
              label="Last sign-in"
              value={data.last_login_at ? formatDateTime(data.last_login_at) : 'Never'}
            />
            <Field label="Failed sign-ins" value={formatNumber(data.failed_login_count ?? 0)} />
            <Field label="Account ID" value={`#${data.id}`} />
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Flags
              </dt>
              <dd className="mt-1.5 flex flex-wrap gap-1.5">
                <Badge variant={data.is_active ? 'success' : 'muted'}>
                  {data.is_active ? 'Active' : 'Disabled'}
                </Badge>
                {data.role === 'admin' && (
                  <Badge variant="default">
                    <Shield aria-hidden />
                    Admin
                  </Badge>
                )}
                {data.must_change_password && <Badge variant="warning">Temp password</Badge>}
              </dd>
            </div>
          </dl>

          <section className="space-y-4 rounded-xl border p-4">
            <h3 className="text-sm font-semibold">Access</h3>

            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-medium">Account enabled</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Disabling revokes every live session immediately.
                </p>
              </div>
              <Switch
                checked={data.is_active}
                onCheckedChange={(next) =>
                  void apply(
                    { is_active: next },
                    next ? 'Account enabled' : 'Account disabled',
                    data.username,
                  )
                }
                disabled={!canMutate || saving || isSelf}
                aria-label="Account enabled"
              />
            </div>

            <div className="flex items-center justify-between gap-4 border-t pt-4">
              <div className="min-w-0">
                <p className="text-sm font-medium">Administrator</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Full access to this panel, including other accounts and settings.
                </p>
              </div>
              <Button
                variant={data.role === 'admin' ? 'outline' : 'default'}
                size="sm"
                onClick={() =>
                  void apply(
                    { role: data.role === 'admin' ? 'user' : 'admin' },
                    data.role === 'admin' ? 'Removed administrator' : 'Granted administrator',
                    data.username,
                  )
                }
                disabled={!canMutate || saving || isSelf}
              >
                {data.role === 'admin' ? <ShieldOff aria-hidden /> : <Shield aria-hidden />}
                {data.role === 'admin' ? 'Demote to user' : 'Make administrator'}
              </Button>
            </div>

            {isSelf && (
              <p className="border-t pt-4 text-xs text-muted-foreground">
                This is your own account, so its status and role are locked here. Use the account
                page for your own password.
              </p>
            )}
          </section>

          <section className="space-y-3 rounded-xl border p-4">
            <h3 className="text-sm font-semibold">Reset password</h3>
            <p className="text-xs text-muted-foreground">
              The new password works once: the account is forced to choose its own on the next
              sign-in, and all existing sessions are revoked.
            </p>

            <PasswordField
              id="reset-password"
              label="New password"
              value={password}
              onChange={(value) => {
                setPassword(value)
                setCopied(false)
              }}
              autoComplete="new-password"
              disabled={!canMutate || saving}
              hint="At least 10 characters, three character classes, and not the username."
            />

            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setPassword(generatePassword())
                  setCopied(false)
                }}
                disabled={!canMutate || saving}
              >
                Generate
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void copy()}
                disabled={!password || saving}
              >
                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() =>
                  void apply(
                    { new_password: password },
                    'Password reset',
                    `${data.username} must change it at next sign-in.`,
                  )
                }
                disabled={!canMutate || saving || !passwordOk}
                loading={saving}
              >
                {!saving && <KeyRound aria-hidden />}
                Set password
              </Button>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold">Recent activity</h3>
            {data.recent_activity && data.recent_activity.length > 0 ? (
              <ul className="divide-y rounded-xl border">
                {data.recent_activity.map((row) => (
                  <li key={row.id} className="flex items-center gap-3 p-3">
                    <PlatformIcon platform={row.platform} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm">{row.title || 'Untitled'}</p>
                      <p className="text-xs text-muted-foreground">
                        {MEDIA_TYPE_LABELS[row.media_type] ?? row.media_type} ·{' '}
                        {formatRelative(row.created_at)}
                      </p>
                    </div>
                    <span
                      className={cn(
                        'rounded-full border px-2 py-0.5 text-xs font-medium',
                        statusTone(row.status),
                      )}
                    >
                      {STATUS_LABELS[row.status] ?? row.status}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                No downloads recorded for this account.
              </p>
            )}
          </section>
        </div>
      ) : null}
    </Dialog>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1.5 text-sm tabular-nums">{value}</dd>
    </div>
  )
}
