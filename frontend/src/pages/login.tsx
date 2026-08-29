import { AlertCircle, ArrowLeft, Eye, EyeOff, LogIn } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/layout/logo'
import { Button } from '@/components/ui/button'
import { Alert } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'

/** Password field with a reveal toggle. Shared by sign-in and registration. */
export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  invalid,
  hint,
  disabled,
  autoFocus,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  autoComplete?: string
  invalid?: boolean
  hint?: string
  disabled?: boolean
  autoFocus?: boolean
}) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          invalid={invalid}
          disabled={disabled}
          autoFocus={autoFocus}
          className="pr-10"
          aria-describedby={hint ? `${id}-hint` : undefined}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
        </button>
      </div>
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  )
}

export function LoginPage() {
  const { login, user, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const usernameRef = useRef<HTMLInputElement>(null)

  // Return the user where they were headed before being asked to sign in.
  const redirectTo = (location.state as { from?: string } | null)?.from ?? '/'

  useEffect(() => {
    if (!loading && user) navigate(redirectTo, { replace: true })
  }, [loading, user, navigate, redirectTo])

  useEffect(() => usernameRef.current?.focus(), [])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const signedIn = await login(username.trim(), password)
      toast.success(`Welcome back, ${signedIn.username}`)
      navigate(signedIn.must_change_password ? '/account' : redirectTo, { replace: true })
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Could not sign in. Please try again.',
      )
      // Clear only the password: retyping the username is needless friction.
      setPassword('')
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
          <h1 className="mt-7 text-3xl font-semibold tracking-[-0.04em]">Welcome back</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Access your download history and account settings.
          </p>
        </div>

        {error && (
          <Alert tone="destructive" icon={AlertCircle} className="mb-5">
            {error}
          </Alert>
        )}

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">Username or email</Label>
            <Input
              ref={usernameRef}
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              autoCapitalize="off"
              spellCheck={false}
              required
              disabled={submitting}
            />
          </div>

          <PasswordField
            id="password"
            label="Password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            disabled={submitting}
          />

          <Button
            type="submit"
            variant="brand"
            className="w-full"
            loading={submitting}
            disabled={!username.trim() || !password}
          >
            {!submitting && <LogIn aria-hidden />}
            Sign in
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-muted-foreground">
          No account?{' '}
          <Link
            to="/register"
            className="rounded font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Create one
          </Link>
        </p>
      </div>

      <p className="mt-6 text-center text-xs text-muted-foreground">
        You can download without an account — sign in only if you want history.
      </p>
    </div>
  )
}
