import { AlertCircle, Check, Copy, UserPlus, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Alert } from '@/components/ui/feedback'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast'
import { PasswordField } from '@/pages/login'
import { ApiError, api } from '@/lib/api'
import { cn, copyToClipboard } from '@/lib/utils'

/** Mirrors app/core/security.py, same as the public registration form. */
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
      label: 'Does not contain the username',
      ok:
        username.trim().length < 3 ||
        !password.toLowerCase().includes(username.trim().toLowerCase()),
    },
  ]
}

const PASSWORD_ALPHABET = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789-_@#%+='

/** Generate a handover password with the browser CSPRNG. */
function generatePassword(length = 20): string {
  const bytes = new Uint32Array(length)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (value) => PASSWORD_ALPHABET[value % PASSWORD_ALPHABET.length]).join('')
}

interface CreateUserDialogProps {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

/** Create an account directly, bypassing the registration toggle.
 *
 *  The server flags the account `must_change_password`, so whatever is typed
 *  here is a one-time handover value the new user replaces on first sign-in.
 */
export function CreateUserDialog({ open, onClose, onCreated }: CreateUserDialogProps) {
  const toast = useToast()

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'user' | 'admin'>('user')
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [copied, setCopied] = useState(false)

  const checks = useMemo(() => passwordChecks(password, username), [password, username])
  const passwordOk = checks.every((check) => check.ok)

  const reset = () => {
    setUsername('')
    setEmail('')
    setPassword('')
    setRole('user')
    setError(null)
    setFieldErrors({})
    setCopied(false)
  }

  const close = () => {
    // Do not leave a plaintext handover password sitting in component state.
    reset()
    onClose()
  }

  const submit = async (event?: React.SyntheticEvent) => {
    event?.preventDefault()
    setError(null)
    setFieldErrors({})
    setSubmitting(true)
    try {
      const created = await api.admin.createUser({
        username: username.trim(),
        email: email.trim(),
        password,
        role,
      })
      toast.success(
        `Created ${created.username}`,
        'They must change this password when they first sign in.',
      )
      onCreated()
      close()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        setFieldErrors(caught.fieldErrors)
      } else {
        setError('Could not create the account. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const suggest = () => {
    const next = generatePassword()
    setPassword(next)
    setCopied(false)
  }

  const copy = async () => {
    const ok = await copyToClipboard(password)
    setCopied(ok)
    if (!ok) toast.warning('Could not copy', 'Copy the password manually before continuing.')
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Create an account"
      description="The account is created regardless of whether public registration is open."
      footer={
        <>
          <Button variant="outline" onClick={close} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="brand"
            onClick={() => void submit()}
            loading={submitting}
            disabled={!username.trim() || !email.trim() || !passwordOk}
          >
            {!submitting && <UserPlus aria-hidden />}
            Create account
          </Button>
        </>
      }
    >
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error && (
          <Alert tone="destructive" icon={AlertCircle}>
            {error}
          </Alert>
        )}

        <div className="space-y-2">
          <Label htmlFor="new-user-username">Username</Label>
          <Input
            id="new-user-username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            minLength={3}
            maxLength={32}
            required
            disabled={submitting}
            invalid={Boolean(fieldErrors.username)}
            aria-describedby="new-user-username-hint"
          />
          <p id="new-user-username-hint" className="text-xs text-muted-foreground">
            {fieldErrors.username ?? '3–32 characters: letters, numbers, dot, dash or underscore.'}
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="new-user-email">Email</Label>
          <Input
            id="new-user-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="off"
            required
            disabled={submitting}
            invalid={Boolean(fieldErrors.email)}
          />
          {fieldErrors.email && <p className="text-xs text-destructive">{fieldErrors.email}</p>}
        </div>

        <div className="space-y-2">
          <Label htmlFor="new-user-role">Role</Label>
          <Select
            id="new-user-role"
            value={role}
            onChange={(event) => setRole(event.target.value as 'user' | 'admin')}
            disabled={submitting}
          >
            <option value="user">User</option>
            <option value="admin">Administrator</option>
          </Select>
        </div>

        <PasswordField
          id="new-user-password"
          label="Temporary password"
          value={password}
          onChange={(value) => {
            setPassword(value)
            setCopied(false)
          }}
          autoComplete="new-password"
          disabled={submitting}
          invalid={Boolean(fieldErrors.password)}
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={suggest} disabled={submitting}>
            Generate
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void copy()}
            disabled={submitting || !password}
          >
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <p className="text-xs text-muted-foreground">
            Share it over a channel you trust — it is shown only once here.
          </p>
        </div>

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

        {/* Enter should submit; the visible action lives in the dialog footer. */}
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  )
}
