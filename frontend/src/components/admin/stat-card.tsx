import type { LucideIcon } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface StatCardProps {
  label: string
  value: string
  icon: LucideIcon
  hint?: string
  tone?: 'default' | 'success' | 'warning' | 'destructive'
  loading?: boolean
  className?: string
}

const TONES: Record<NonNullable<StatCardProps['tone']>, string> = {
  default: 'bg-primary/10 text-primary',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  destructive: 'bg-destructive/10 text-destructive',
}

/** Single headline number with a supporting line. */
export function StatCard({
  label,
  value,
  icon: Icon,
  hint,
  tone = 'default',
  loading,
  className,
}: StatCardProps) {
  return (
    <div className={cn('rounded-xl border bg-card p-5 shadow-soft', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          {loading ? (
            <Skeleton className="mt-2 h-8 w-20" />
          ) : (
            <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
          )}
          {hint && !loading && (
            <p className="mt-1 truncate text-xs text-muted-foreground">{hint}</p>
          )}
        </div>
        <span className={cn('grid size-9 shrink-0 place-items-center rounded-lg', TONES[tone])}>
          <Icon className="size-4" aria-hidden />
        </span>
      </div>
    </div>
  )
}
