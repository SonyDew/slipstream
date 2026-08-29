import { AlertCircle, ArrowLeft, Check, UserPlus, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/layout/logo'
import { PasswordField } from '@/pages/login'
import { Button } from '@/components/ui/button'
import { Alert } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

/** Mirrors the server-side policy in app/core/security.py.
 *
 *  Kept deliberately in step with the backend so the form never accepts
 *  something the API will reject — the server remains the authority.
 */
function passwordChecks(password: string, username: string) {
  const classes = [
    /[a-z]/.test(password),
    /[A-Z]/.test(password),
    /\d/.test(password),
    /[^a-zA-Z0-9]/.test(password),
  ].filter(Boolean).length

  return [
    { label: 'At least 10 characters', ok: password.length >= 10 },
    { label: 'Three of: lowercase, uppercase, digit, symbol', ok: classes >= 3 },
    {
      label: 'Does not contain your username',
      ok:
        username.trim().length < 3 ||
        !password.toLowerCase().includes(username.trim().toLowerCase()),
    },
  ]
}

export function RegisterPage() {
  const { register, user, loading, config } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const usernameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!loading && user) navigate('/', { replace: true })
  }, [loading, user, navigate])

  useEffect(() => usernameRef.current?.focus(), [])

  const checks = useMemo(() => passwordChecks(password, username), [password, username])
  const passwordOk = checks.every((check) => check.ok)
  const registrationClosed = config ? !config.registration_enabled : false

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setFieldErrors({})
    setSubmitting(true)
    try {
      const created = await register(username.trim(), email.trim(), password)
      toast.success(`Welcome, ${created.username}`, 'Your account is ready.')
      navigate('/', { replace: true })
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors)
      } else {
        setError('Could not create your account. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="w-full max-w-[25rem] animate-fade-up">
      <Link
        to="/"
        className="mb-8 inline-flex items-center gap-2 rounded text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to downloader
      </Link>

      <div className="bg-background sm:p-2">
        <div className="mb-7 text-center">
          <Logo className="justify-center" />
          <h1 className="mt-7 text-3xl font-semibold tracking-[-0.04em]">Create your account</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Keep a download history and get higher rate limits.
          </p>
        </div>

        {registrationClosed ? (
          <Alert tone="warning" icon={AlertCircle} title="Registration is closed">
            The administrator has disabled new accounts on this server. You can still
            download as a guest.
          </Alert>
        ) : (
          <>
            {error && (
              <Alert tone="destructive" icon={AlertCircle} className="mb-5">
                {error}
              </Alert>
            )}

            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="reg-username">Username</Label>
                <Input
                  ref={usernameRef}
                  id="reg-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  autoCapitalize="off"
                  spellCheck={false}
                  minLength={3}
                  maxLength={32}
                  required
                  disabled={submitting}
                  invalid={Boolean(fieldErrors.username)}
                  aria-describedby="reg-username-hint"
                />
                <p id="reg-username-hint" className="text-xs text-muted-foreground">
                  {fieldErrors.username ?? '3–32 characters: letters, numbers, dot, dash or underscore.'}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="reg-email">Email</Label>
                <Input
                  id="reg-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                  disabled={submitting}
                  invalid={Boolean(fieldErrors.email)}
                />
                {fieldErrors.email && (
                  <p className="text-xs text-destructive">{fieldErrors.email}</p>
                )}
              </div>

              <PasswordField
                id="reg-password"
                label="Password"
                value={password}
                onChange={setPassword}
                autoComplete="new-password"
                disabled={submitting}
                invalid={Boolean(fieldErrors.password)}
              />

              {password.length > 0 && (
                <ul className="space-y-1.5 rounded-lg border bg-muted/40 p-3">
                  {checks.map((check) => (
                    <li key={check.label} className="flex items-center gap-2 text-xs">
                      <span
                        className={cn(
                          'grid size-4 shrink-0 place-items-center rounded-full',
                          check.ok ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground',
                        )}
                        aria-hidden
                      >
                        {check.ok ? (
                          <Check className="size-2.5" strokeWidth={3} />
                        ) : (
                          <X className="size-2.5" strokeWidth={3} />
                        )}
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
                className="w-full"
                loading={submitting}
                disabled={!username.trim() || !email.trim() || !passwordOk}
              >
                {!submitting && <UserPlus aria-hidden />}
                Create account
              </Button>
            </form>
          </>
        )}

        <p className="mt-6 text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link
            to="/login"
            className="rounded font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
