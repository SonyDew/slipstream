import { cn } from '@/lib/utils'

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 0-100. Pass null for an indeterminate bar. */
  value: number | null
  tone?: 'brand' | 'success' | 'destructive'
}

/** Determinate or indeterminate progress bar.
 *
 *  The indeterminate mode matters here: some sources report no total size, and a
 *  bar frozen at a fabricated percentage is worse than one that plainly signals
 *  "still working".
 */
export function Progress({ value, tone = 'brand', className, ...props }: ProgressProps) {
  const clamped = value === null ? null : Math.max(0, Math.min(100, value))
  const fill =
    tone === 'success'
      ? 'bg-success'
      : tone === 'destructive'
        ? 'bg-destructive'
        : 'bg-brand-gradient'

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped ?? undefined}
      aria-valuetext={clamped === null ? 'Working' : `${clamped}%`}
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-muted', className)}
      {...props}
    >
      {clamped === null ? (
        <div className={cn('absolute inset-y-0 w-1/4 animate-indeterminate rounded-full', fill)} />
      ) : (
        <div
          className={cn('h-full rounded-full transition-[width] duration-500 ease-smooth', fill)}
          style={{ width: `${clamped}%` }}
        />
      )}
    </div>
  )
}
