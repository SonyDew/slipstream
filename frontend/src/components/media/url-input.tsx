import { ArrowUpRight, ClipboardPaste, Link2, Search, X } from 'lucide-react'
import { forwardRef, useEffect, useMemo, useRef, useState } from 'react'

import { PlatformIcon } from '@/components/media/platform-badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'
import type { Platform } from '@/lib/types'
import { cn, looksLikeUrl, readClipboard } from '@/lib/utils'

interface UrlInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  platforms?: Platform[]
  loading?: boolean
  disabled?: boolean
  autoFocus?: boolean
  className?: string
}

const PLACEHOLDER = 'Paste a public media link'

function detectPlatform(value: string, platforms: Platform[]): Platform | null {
  try {
    const hostname = new URL(value.trim()).hostname.replace(/^www\./, '').toLowerCase()
    return (
      platforms.find(
        (platform) =>
          !platform.is_fallback &&
          platform.domains.some((domain) => {
            const normalized = domain.replace(/^www\./, '').toLowerCase()
            return hostname === normalized || hostname.endsWith(`.${normalized}`)
          }),
      ) ?? null
    )
  } catch {
    return null
  }
}

/** Product entry point. Platform recognition is advisory; the backend remains authoritative. */
export const UrlInput = forwardRef<HTMLInputElement, UrlInputProps>(
  (
    {
      value,
      onChange,
      onSubmit,
      platforms = [],
      loading,
      disabled,
      autoFocus,
      className,
    },
    forwardedRef,
  ) => {
    const toast = useToast()
    const innerRef = useRef<HTMLInputElement | null>(null)
    const [pasteSupported, setPasteSupported] = useState(false)
    const detected = useMemo(() => detectPlatform(value, platforms), [value, platforms])
    const valid = looksLikeUrl(value)

    useEffect(() => {
      setPasteSupported(
        Boolean(navigator.clipboard && 'readText' in navigator.clipboard && window.isSecureContext),
      )
    }, [])

    useEffect(() => {
      // Avoid summoning the software keyboard on first paint. Desktop users get
      // the faster paste-and-enter path; touch users keep the first viewport stable.
      if (autoFocus && window.matchMedia('(pointer: fine)').matches) innerRef.current?.focus()
    }, [autoFocus])

    const setRefs = (node: HTMLInputElement | null) => {
      innerRef.current = node
      if (typeof forwardedRef === 'function') forwardedRef(node)
      else if (forwardedRef) forwardedRef.current = node
    }

    const handlePaste = async () => {
      const text = await readClipboard()
      if (text === null) {
        toast.info('Clipboard unavailable', 'Paste with Ctrl+V or ⌘V instead.')
        innerRef.current?.focus()
        return
      }
      const trimmed = text.trim()
      if (!trimmed) {
        toast.info('Clipboard is empty', 'Copy a media link first.')
        return
      }
      onChange(trimmed)
      innerRef.current?.focus()
      if (looksLikeUrl(trimmed)) window.setTimeout(onSubmit, 60)
    }

    const canSubmit = valid && !loading && !disabled

    return (
      <form
        className={cn('w-full', className)}
        onSubmit={(event) => {
          event.preventDefault()
          if (canSubmit) onSubmit()
        }}
      >
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#11130e] text-[#f5f4ec] shadow-lifted dark:bg-[#090a07]">
          <div className="flex items-center justify-between gap-4 border-b border-white/10 px-4 py-3 sm:px-5">
            <span className="font-mono text-[0.65rem] font-semibold uppercase tracking-[0.16em] text-white/48">
              Source URL
            </span>
            <span
              className={cn(
                'flex min-w-0 items-center gap-2 text-xs transition-colors',
                value && !valid ? 'text-warning' : 'text-white/55',
              )}
              aria-live="polite"
            >
              {loading ? (
                <>
                  <span className="signal-dot animate-signal-pulse" aria-hidden />
                  Inspecting source
                </>
              ) : detected ? (
                <>
                  <PlatformIcon platform={detected.platform} className="size-3.5" />
                  <span className="truncate">{detected.label} recognized</span>
                </>
              ) : value && !valid ? (
                'Complete link required'
              ) : valid ? (
                <>
                  <span className="signal-dot" aria-hidden />
                  Link ready for inspection
                </>
              ) : (
                <>
                  <span className="signal-dot" aria-hidden />
                  Ready for a link
                </>
              )}
            </span>
          </div>

          <div className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:p-4">
            <div className="relative min-w-0 flex-1">
              <Link2
                className="pointer-events-none absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-white/38"
                aria-hidden
              />
              <input
                ref={setRefs}
                type="url"
                inputMode="url"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={PLACEHOLDER}
                disabled={disabled}
                aria-label="Media URL"
                aria-invalid={Boolean(value && !valid)}
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                className={cn(
                  'h-14 w-full rounded-xl border border-white/12 bg-white/[0.055] pl-11 pr-11 text-base text-white outline-none',
                  'placeholder:text-white/32 transition-[border-color,background-color,box-shadow]',
                  'hover:bg-white/[0.075] focus:border-primary/70 focus:bg-white/[0.075] focus:shadow-[0_0_0_4px_hsl(var(--primary)/0.1)]',
                  'disabled:opacity-50',
                )}
              />
              {value && !loading && (
                <button
                  type="button"
                  onClick={() => {
                    onChange('')
                    innerRef.current?.focus()
                  }}
                  aria-label="Clear link"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-2 text-white/45 transition-colors hover:bg-white/10 hover:text-white focus-visible:ring-primary"
                >
                  <X className="size-4" aria-hidden />
                </button>
              )}
            </div>

            <div className="flex gap-2">
              {pasteSupported && (
                <Button
                  type="button"
                  variant="ghost"
                  size="lg"
                  onClick={handlePaste}
                  disabled={disabled || loading}
                  className="flex-1 text-white/70 hover:bg-white/10 hover:text-white sm:px-4"
                >
                  <ClipboardPaste aria-hidden />
                  <span className="sm:sr-only lg:not-sr-only">Paste</span>
                </Button>
              )}
              <Button
                type="submit"
                variant="brand"
                size="lg"
                loading={loading}
                disabled={!canSubmit}
                className="flex-1 sm:min-w-[9.25rem]"
              >
                {!loading && <Search aria-hidden />}
                {loading ? 'Analyzing' : 'Analyze'}
                {!loading && <ArrowUpRight aria-hidden />}
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-4 font-mono text-[0.63rem] uppercase tracking-[0.1em] text-white/38 sm:px-5">
            <span>Public content only</span>
            <span>Video · audio · images</span>
          </div>
        </div>
      </form>
    )
  },
)
UrlInput.displayName = 'UrlInput'
