import {
  AlertCircle,
  CalendarDays,
  Check,
  KeyRound,
  LogOut,
  Shield,
  Trash2,
  User as UserIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { PasswordField } from '@/pages/login'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Alert } from '@/components/ui/feedback'
import { useToast } from '@/components/ui/toast'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { cn, formatDate } from '@/lib/utils'

function passwordChecks(password: string, username: string) {
  const classes = [
    /[a-z]/.test(password),
    /[A-Z]/.test(password),
    /\d/.test(password),
    /[^a-zA-Z0-9]/.test(password),
  ].filter(Boolean).length

  return [
    { label: 'At least 10 characters', ok: password.length >= 10 },
    { label: 'Three character types', ok: classes >= 3 },
    {
      label: 'Does not contain your username',
      ok: username.length < 3 || !password.toLowerCase().includes(username.toLowerCase()),
    },
  ]
}

export function AccountPage() {
  const { user, refresh, logout, mustChangePassword } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [signOutAllOpen, setSignOutAllOpen] = useState(false)
  const [signingOutAll, setSigningOutAll] = useState(false)
  const [clearOpen, setClearOpen] = useState(false)
  const [clearing, setClearing] = useState(false)

  const checks = useMemo(
    () => passwordChecks(newPassword, user?.username ?? ''),
    [newPassword, user],
  )
  const passwordOk = checks.every((check) => check.ok)
  const matches = newPassword.length > 0 && newPassword === confirmPassword

  if (!user) return null

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await api.changePassword(currentPassword, newPassword)
      toast.success(
        'Password changed',
        'Other sessions were signed out for safety.',
      )
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      await refresh()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not change your password.')
    } finally {
      setSaving(false)
    }
  }

  const signOutEverywhere = async () => {
    setSigningOutAll(true)
    try {
      await api.logoutEverywhere()
      toast.success('Signed out everywhere')
      navigate('/')
    } catch (caught) {
      toast.error(
        'Could not sign out',
        caught instanceof ApiError ? caught.message : 'Please try again.',
      )
    } finally {
      setSigningOutAll(false)
      setSignOutAllOpen(false)
    }
  }

  const clearHistory = async () => {
    setClearing(true)
    try {
      const { deleted } = await api.clearHistory()
      toast.success('History cleared', `${deleted} ${deleted === 1 ? 'entry' : 'entries'} removed.`)
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

  return (
    <div className="container max-w-3xl py-12">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Account</h1>
        <p className="mt-2 text-muted-foreground">
          Manage your credentials, sessions and stored history.
        </p>
      </header>

      {mustChangePassword && (
        <Alert
          tone="warning"
          icon={KeyRound}
          title="Temporary password in use"
          className="mb-6"
        >
          {user.is_admin
            ? 'Administrator actions are blocked until you set your own password below.'
            : 'Please set your own password below.'}
        </Alert>
      )}

      <div className="space-y-6">
        {/* -- profile ------------------------------------------------------ */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UserIcon className="size-4 text-muted-foreground" aria-hidden />
              Profile
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field label="Username" value={user.username} />
            <Field label="Email" value={user.email ?? '—'} />
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Role
              </p>
              <div className="mt-1.5">
                {user.is_admin ? (
                  <Badge variant="default">
                    <Shield aria-hidden />
                    Administrator
                  </Badge>
                ) : (
                  <Badge variant="muted">Standard user</Badge>
                )}
              </div>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Status
              </p>
              <div className="mt-1.5">
                <Badge variant={user.is_active ? 'success' : 'destructive'}>
                  {user.is_active ? 'Active' : 'Disabled'}
                </Badge>
              </div>
            </div>
            <Field
              label="Member since"
              value={formatDate(user.created_at)}
              icon={CalendarDays}
            />
            <Field label="Last sign-in" value={formatDate(user.last_login_at)} />
          </CardContent>
        </Card>

        {/* -- password ----------------------------------------------------- */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4 text-muted-foreground" aria-hidden />
              Change password
            </CardTitle>
            <CardDescription>
              Changing your password signs out every other session.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {error && (
              <Alert tone="destructive" icon={AlertCircle} className="mb-5">
                {error}
              </Alert>
            )}

            <form onSubmit={submitPassword} className="space-y-4">
              <PasswordField
                id="current-password"
                label="Current password"
                value={currentPassword}
                onChange={setCurrentPassword}
                autoComplete="current-password"
                disabled={saving}
              />
              <PasswordField
                id="new-password"
                label="New password"
                value={newPassword}
                onChange={setNewPassword}
                autoComplete="new-password"
                disabled={saving}
              />
              <PasswordField
                id="confirm-password"
                label="Confirm new password"
                value={confirmPassword}
                onChange={setConfirmPassword}
                autoComplete="new-password"
                disabled={saving}
                invalid={confirmPassword.length > 0 && !matches}
                hint={
                  confirmPassword.length > 0 && !matches ? 'Passwords do not match.' : undefined
                }
              />

              {newPassword.length > 0 && (
                <ul className="space-y-1.5 rounded-lg border bg-muted/40 p-3">
                  {checks.map((check) => (
                    <li key={check.label} className="flex items-center gap-2 text-xs">
                      <span
                        className={cn(
                          'grid size-4 shrink-0 place-items-center rounded-full',
                          check.ok
                            ? 'bg-success/15 text-success'
                            : 'bg-muted text-muted-foreground',
                        )}
                        aria-hidden
                      >
                        <Check className="size-2.5" strokeWidth={3} />
                      </span>
                      <span className={check.ok ? 'text-muted-foreground' : 'text-foreground'}>
                        {check.label}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              <Button
                type="submit"
                variant="brand"
                loading={saving}
                disabled={!currentPassword || !passwordOk || !matches}
              >
                Update password
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* -- sessions ----------------------------------------------------- */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LogOut className="size-4 text-muted-foreground" aria-hidden />
              Sessions
            </CardTitle>
            <CardDescription>
              Sign out of every device, including this one. Useful if you signed in
              somewhere you no longer trust.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => setSignOutAllOpen(true)}>
              Sign out everywhere
            </Button>
          </CardContent>
        </Card>

        {/* -- data --------------------------------------------------------- */}
        <Card className="border-destructive/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Trash2 className="size-4 text-destructive" aria-hidden />
              Download history
            </CardTitle>
            <CardDescription>
              Permanently delete every history entry on your account. Files themselves
              are already removed automatically after their expiry window.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="destructive" onClick={() => setClearOpen(true)}>
              Clear my history
            </Button>
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog
        open={signOutAllOpen}
        onClose={() => setSignOutAllOpen(false)}
        onConfirm={signOutEverywhere}
        loading={signingOutAll}
        title="Sign out everywhere?"
        description="Every session, including this browser, will be signed out. You will need to sign in again."
        confirmLabel="Sign out everywhere"
        destructive={false}
      />

      <ConfirmDialog
        open={clearOpen}
        onClose={() => setClearOpen(false)}
        onConfirm={clearHistory}
        loading={clearing}
        title="Clear download history?"
        description="This deletes all of your history entries. It cannot be undone."
        confirmLabel="Delete history"
      />

      <button type="button" onClick={() => void logout()} className="sr-only">
        Sign out
      </button>
    </div>
  )
}

function Field({
  label,
  value,
  icon: Icon,
}: {
  label: string
  value: string
  icon?: React.ComponentType<{ className?: string }>
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1.5 flex items-center gap-1.5 text-sm font-medium">
        {Icon && <Icon className="size-3.5 text-muted-foreground" />}
        <span className="truncate">{value}</span>
      </p>
    </div>
  )
}
