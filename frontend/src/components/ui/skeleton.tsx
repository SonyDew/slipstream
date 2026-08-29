import { cn } from '@/lib/utils'

/** Loading placeholder. Uses a shimmer rather than a pulse: it reads as
 *  "content is coming" instead of "something is broken". */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('shimmer rounded-md bg-muted', className)}
      aria-hidden
      {...props}
    />
  )
}
