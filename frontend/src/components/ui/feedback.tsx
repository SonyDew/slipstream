import { AlertCircle, Inbox, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/* -------------------------------------------------------------------------- */
/* Empty state                                                                 */
/* -------------------------------------------------------------------------- */

interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-14 text-center',
        className,
      )}
    >
      <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-muted">
        <Icon className="size-6 text-muted-foreground" aria-hidden />
      </div>
      <p className="font-medium">{title}</p>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Error state                                                                 */
/* -------------------------------------------------------------------------- */

interface ErrorCardProps {
  title?: string
  message: string
  code?: string | null
  onRetry?: () => void
  retrying?: boolean
  className?: string
  children?: React.ReactNode
}

/** Inline error presentation.
 *
 *  A retry affordance appears only when the caller says the operation is worth
 *  retrying, so the button never lies about whether it can help.
 */
export function ErrorCard({
  title = 'Something went wrong',
  message,
  code,
  onRetry,
  retrying,
  className,
  children,
}: ErrorCardProps) {
  return (
    <div
      role="alert"
      className={cn(
        'rounded-xl border border-destructive/25 bg-destructive/5 p-5',
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-foreground">{title}</p>
          <p className="mt-1 text-sm text-muted-foreground">{message}</p>
          {children}
          <div className="mt-3 flex items-center gap-3">
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry} loading={retrying}>
                {!retrying && <RefreshCw aria-hidden />}
                Try again
              </Button>
            )}
            {code && (
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                {code}
              </code>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Alert                                                                       */
/* -------------------------------------------------------------------------- */

type AlertTone = 'info' | 'warning' | 'destructive' | 'success'

const ALERT_TONES: Record<AlertTone, string> = {
  info: 'border-primary/25 bg-primary/5',
  warning: 'border-warning/30 bg-warning/5',
  destructive: 'border-destructive/25 bg-destructive/5',
  success: 'border-success/25 bg-success/5',
}

const ALERT_ICON_TONES: Record<AlertTone, string> = {
  info: 'text-primary',
  warning: 'text-warning',
  destructive: 'text-destructive',
  success: 'text-success',
}

interface AlertProps {
  tone?: AlertTone
  icon?: React.ComponentType<{ className?: string }>
  title?: string
  children: React.ReactNode
  className?: string
  action?: React.ReactNode
}

export function Alert({
  tone = 'info',
  icon: Icon = AlertCircle,
  title,
  children,
  className,
  action,
}: AlertProps) {
  return (
    <div
      className={cn('rounded-lg border p-4', ALERT_TONES[tone], className)}
      role={tone === 'destructive' ? 'alert' : undefined}
    >
      <div className="flex items-start gap-3">
        <Icon className={cn('mt-0.5 size-5 shrink-0', ALERT_ICON_TONES[tone])} aria-hidden />
        <div className="min-w-0 flex-1 text-sm">
          {title && <p className="font-medium text-foreground">{title}</p>}
          <div className={cn('text-muted-foreground', title && 'mt-1')}>{children}</div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  )
}
