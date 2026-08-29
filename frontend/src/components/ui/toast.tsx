import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { cn } from '@/lib/utils'

export type ToastTone = 'success' | 'error' | 'warning' | 'info'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface Toast {
  id: string
  tone: ToastTone
  title: string
  description?: string
  action?: ToastAction
  /** Milliseconds before auto-dismiss. 0 keeps it until dismissed. */
  duration: number
}

interface ToastContextValue {
  toasts: Toast[]
  show: (toast: Omit<Toast, 'id' | 'duration'> & { duration?: number }) => string
  dismiss: (id: string) => void
  success: (title: string, description?: string) => string
  error: (title: string, description?: string, action?: ToastAction) => string
  warning: (title: string, description?: string) => string
  info: (title: string, description?: string) => string
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_DURATION = 5000
/** Errors linger: the user may need to read and act on them. */
const ERROR_DURATION = 9000
const MAX_VISIBLE = 4

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef(new Map<string, number>())

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      window.clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const show = useCallback<ToastContextValue['show']>(
    ({ duration, ...toast }) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const resolved: Toast = {
        ...toast,
        id,
        duration: duration ?? (toast.tone === 'error' ? ERROR_DURATION : DEFAULT_DURATION),
      }

      setToasts((current) => {
        const next = [...current, resolved]
        // Drop the oldest rather than letting the stack grow off-screen.
        return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next
      })

      if (resolved.duration > 0) {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), resolved.duration),
        )
      }
      return id
    },
    [dismiss],
  )

  // Clear pending timers if the provider unmounts.
  useEffect(
    () => () => {
      timers.current.forEach((timer) => window.clearTimeout(timer))
      timers.current.clear()
    },
    [],
  )

  const success = useCallback(
    (title: string, description?: string) => show({ tone: 'success', title, description }),
    [show],
  )
  const error = useCallback(
    (title: string, description?: string, action?: ToastAction) =>
      show({ tone: 'error', title, description, action }),
    [show],
  )
  const warning = useCallback(
    (title: string, description?: string) => show({ tone: 'warning', title, description }),
    [show],
  )
  const info = useCallback(
    (title: string, description?: string) => show({ tone: 'info', title, description }),
    [show],
  )

  const value = useMemo<ToastContextValue>(
    () => ({
      toasts,
      show,
      dismiss,
      success,
      error,
      warning,
      info,
    }),
    [toasts, show, dismiss, success, error, warning, info],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside <ToastProvider>')
  return context
}

const TONE_CONFIG: Record<
  ToastTone,
  { icon: typeof Info; iconClass: string; borderClass: string }
> = {
  success: {
    icon: CheckCircle2,
    iconClass: 'text-success',
    borderClass: 'border-l-success',
  },
  error: { icon: XCircle, iconClass: 'text-destructive', borderClass: 'border-l-destructive' },
  warning: {
    icon: AlertTriangle,
    iconClass: 'text-warning',
    borderClass: 'border-l-warning',
  },
  info: { icon: Info, iconClass: 'text-primary', borderClass: 'border-l-primary' },
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: string) => void
}) {
  return (
    <div
      // Polite: toasts announce results, they should not interrupt a screen
      // reader mid-sentence.
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[100] flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:right-0 sm:top-0 sm:items-end sm:p-6"
    >
      {toasts.map((toast) => {
        const config = TONE_CONFIG[toast.tone]
        const Icon = config.icon
        return (
          <div
            key={toast.id}
            role={toast.tone === 'error' ? 'alert' : 'status'}
            className={cn(
              'pointer-events-auto flex w-full max-w-sm animate-slide-in-right items-start gap-3',
              'rounded-xl border border-l-4 bg-popover p-4 text-popover-foreground shadow-lifted',
              config.borderClass,
            )}
          >
            <Icon className={cn('mt-0.5 size-5 shrink-0', config.iconClass)} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium leading-snug">{toast.title}</p>
              {toast.description && (
                <p className="mt-1 text-sm leading-snug text-muted-foreground">
                  {toast.description}
                </p>
              )}
              {toast.action && (
                <button
                  type="button"
                  onClick={() => {
                    toast.action?.onClick()
                    onDismiss(toast.id)
                  }}
                  className="mt-2 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                >
                  {toast.action.label}
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss notification"
              className="-m-1 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="size-4" aria-hidden />
            </button>
          </div>
        )
      })}
    </div>
  )
}
