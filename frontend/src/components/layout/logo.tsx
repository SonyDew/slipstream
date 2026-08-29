import { cn } from '@/lib/utils'

/** Wordmark used in the navbar, footer and auth pages. */
export function Logo({
  className,
  showText = true,
  size = 'default',
}: {
  className?: string
  showText?: boolean
  size?: 'sm' | 'default'
}) {
  const box = size === 'sm' ? 'h-7 w-8' : 'h-8 w-9'
  const text = size === 'sm' ? 'text-[0.72rem]' : 'text-[0.78rem]'

  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <svg
        viewBox="0 0 36 32"
        className={cn(
          'shrink-0 overflow-visible',
          box,
        )}
        aria-hidden="true"
      >
        <rect x="0.75" y="0.75" width="34.5" height="30.5" rx="8" fill="#11130e" />
        <rect
          x="0.75"
          y="0.75"
          width="34.5"
          height="30.5"
          rx="8"
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.14"
          strokeWidth="1.5"
        />
        <path
          d="M7 8.75h13.25c3.75 0 6 1.75 6 4.5s-2.25 4.5-6 4.5h-7.1c-2.25 0-3.4.95-3.4 2.55s1.15 2.7 3.4 2.7H27"
          fill="none"
          stroke="#f4f2e9"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.65"
        />
        <path
          d="M7 14h11.25"
          fill="none"
          stroke="#c9ff35"
          strokeLinecap="round"
          strokeWidth="2.65"
        />
        <circle cx="27" cy="23" r="1.5" fill="#c9ff35" />
      </svg>
      {showText && (
        <span className={cn('font-mono font-semibold uppercase tracking-[0.14em]', text)}>
          Slipstream
        </span>
      )}
    </span>
  )
}
