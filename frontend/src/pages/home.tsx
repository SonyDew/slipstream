import {
  ArrowRight,
  ChevronDown,
  Eye,
  Gauge,
  Lock,
  ScanSearch,
  ShieldCheck,
  SlidersHorizontal,
  TimerReset,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { JobProgress } from '@/components/media/job-progress'
import { PlatformIcon } from '@/components/media/platform-badge'
import { ResultCard } from '@/components/media/result-card'
import { UrlInput } from '@/components/media/url-input'
import { ButtonLink } from '@/components/ui/button'
import { Alert, ErrorCard } from '@/components/ui/feedback'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { Analysis, DownloadMode } from '@/lib/types'
import { cn } from '@/lib/utils'

interface ActiveJob {
  id: string
  key: number
}

export function HomePage() {
  const { config, user } = useAuth()
  const toast = useToast()

  const [url, setUrl] = useState('')
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [analysing, setAnalysing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [job, setJob] = useState<ActiveJob | null>(null)

  const resultRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController>()

  useEffect(() => () => abortRef.current?.abort(), [])

  const analyse = useCallback(async () => {
    const trimmed = url.trim()
    if (!trimmed) return

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    setAnalysing(true)
    setError(null)
    setAnalysis(null)
    setJob(null)

    try {
      const result = await api.analyze(trimmed, abortRef.current.signal)
      setAnalysis(result)
      window.setTimeout(
        () => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }),
        80,
      )
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError('unknown', 'Something went wrong analysing that link.', 0, true),
      )
    } finally {
      setAnalysing(false)
    }
  }, [url])

  const startDownload = useCallback(
    async (request: {
      mode: DownloadMode
      quality: string
      container: string
      imageIndexes?: number[]
    }) => {
      if (!analysis) return
      setSubmitting(true)
      try {
        const created = await api.createDownload({
          url: analysis.original_url,
          mode: request.mode,
          quality: request.quality,
          container: request.container,
          image_indexes: request.imageIndexes ?? null,
        })
        setJob({ id: created.job_id, key: Date.now() })
      } catch (caught) {
        const apiError = caught instanceof ApiError ? caught : null
        toast.error(
          'Could not start the download',
          apiError?.message ?? 'Please try again in a moment.',
        )
      } finally {
        setSubmitting(false)
      }
    },
    [analysis, toast],
  )

  const guestBlocked = config ? !config.guest_downloads_enabled && !user : false

  return (
    <>
      <section id="download" className="hero-stage overflow-hidden border-b">
        <div className="container pb-14 pt-12 sm:pb-20 sm:pt-16 lg:pt-20">
          <div className="grid items-end gap-8 lg:grid-cols-[minmax(0,1.45fr)_minmax(18rem,0.55fr)] lg:gap-16">
            <div className="animate-fade-up">
              <p className="mb-5 flex items-center gap-3 font-mono text-[0.67rem] font-semibold uppercase tracking-[0.17em] text-muted-foreground">
                <span className="signal-dot" aria-hidden />
                Universal media utility
              </p>
              <h1 className="max-w-4xl text-display-sm font-semibold sm:text-display-md lg:text-display-lg">
                Media in.
                <br />
                <span className="text-primary">Files out.</span>
              </h1>
            </div>

            <div className="animate-fade-up border-l-2 border-primary pl-5 [animation-delay:80ms]">
              <p className="text-pretty text-lg font-medium leading-snug">
                Paste one public link. Slipstream finds the source, exposes the real formats,
                and prepares the file.
              </p>
              <p className="mt-4 text-sm leading-6 text-muted-foreground">
                No site picker, no fake quality options, no advertising detours.
              </p>
            </div>
          </div>

          <div className="relative mt-10 animate-fade-up sm:mt-12 [animation-delay:140ms]">
            <div className="stream-lines pointer-events-none absolute -left-24 -right-24 -top-10 h-10 animate-line-drift opacity-45" aria-hidden />

            {guestBlocked && (
              <Alert tone="warning" icon={Lock} className="mb-4" title="Sign in to download">
                Guest downloads are disabled on this server. You can still inspect links.
              </Alert>
            )}

            <UrlInput
              value={url}
              onChange={setUrl}
              onSubmit={analyse}
              platforms={config?.platforms}
              loading={analysing}
              autoFocus
            />
          </div>

          <div ref={resultRef} className="mt-5 space-y-4 scroll-mt-24">
            {analysing && <AnalysisSkeleton />}

            {error && (
              <ErrorCard
                title={errorTitle(error)}
                message={error.message}
                code={error.code}
                onRetry={error.retryable ? analyse : undefined}
                retrying={analysing}
              >
                {error.code === 'unsupported_url' && (
                  <p className="mt-2 text-sm text-muted-foreground">
                    Review the currently enabled sources in the{' '}
                    <a href="#platforms" className="font-medium text-foreground underline decoration-primary decoration-2 underline-offset-4">
                      platform list
                    </a>
                    .
                  </p>
                )}
              </ErrorCard>
            )}

            {analysis && !analysing && (
              <ResultCard analysis={analysis} onDownload={startDownload} submitting={submitting} />
            )}

            {job && (
              <JobProgress key={job.key} jobId={job.id} onDismiss={() => setJob(null)} />
            )}
          </div>

          {!analysis && !analysing && !error && (
            <div className="mt-5 grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
              <MicroFact icon={ScanSearch} label="Automatic source detection" />
              <MicroFact icon={SlidersHorizontal} label="Only formats that exist" />
              <MicroFact icon={TimerReset} label="Files expire automatically" />
            </div>
          )}
        </div>
      </section>

      <SupportedPlatforms />
      <Workflow />
      <TruthSection />
      <Faq />
    </>
  )
}

function errorTitle(error: ApiError): string {
  switch (error.code) {
    case 'invalid_url':
      return 'That link does not look right'
    case 'unsupported_url':
      return 'This source is not supported'
    case 'blocked_target':
      return 'Address not allowed'
    case 'private_content':
    case 'auth_required_content':
      return 'Content is not public'
    case 'media_unavailable':
      return 'Media unavailable'
    case 'rate_limited':
      return 'Rate limit reached'
    case 'maintenance_mode':
      return 'Maintenance in progress'
    case 'network_timeout':
      return 'The source took too long'
    default:
      return 'Could not analyse that link'
  }
}

function MicroFact({ icon: Icon, label }: { icon: typeof ScanSearch; label: string }) {
  return (
    <div className="flex items-center gap-3 bg-background px-4 py-3.5 text-sm text-muted-foreground">
      <Icon className="size-4 text-foreground" aria-hidden />
      {label}
    </div>
  )
}

function AnalysisSkeleton() {
  return (
    <div className="grid animate-fade-in overflow-hidden rounded-2xl border bg-card shadow-card lg:grid-cols-[0.82fr_1.18fr]">
      <div className="border-b p-4 lg:border-b-0 lg:border-r lg:p-6">
        <Skeleton className="aspect-video w-full rounded-xl" />
        <Skeleton className="mt-5 h-5 w-3/4" />
        <Skeleton className="mt-2 h-4 w-2/5" />
      </div>
      <div className="space-y-3 p-4 lg:p-6">
        <Skeleton className="h-11 w-56 rounded-xl" />
        <Skeleton className="h-14 w-full rounded-xl" />
        <Skeleton className="h-14 w-full rounded-xl" />
        <Skeleton className="h-14 w-full rounded-xl" />
      </div>
    </div>
  )
}

function SupportedPlatforms() {
  const { config } = useAuth()
  const platforms = (config?.platforms ?? []).filter(
    (platform) => !platform.is_fallback && platform.operational,
  )

  return (
    <section id="platforms" className="border-b bg-card">
      <div className="container grid gap-6 py-7 md:grid-cols-[14rem_1fr] md:items-center">
        <div>
          <p className="font-mono text-[0.65rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Enabled sources
          </p>
          <p className="mt-1 text-sm font-medium">Reported by this server</p>
        </div>

        {platforms.length > 0 ? (
          <ul className="no-scrollbar flex gap-2 overflow-x-auto md:justify-end">
            {platforms.map((platform) => (
              <li
                key={platform.platform}
                className="flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-2 text-xs font-medium"
              >
                <PlatformIcon platform={platform.platform} className="size-3.5 text-foreground" />
                {platform.label}
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex gap-2 overflow-hidden md:justify-end">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-9 w-24 shrink-0 rounded-full" />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

const STEPS = [
  {
    number: '01',
    title: 'Inspect',
    body: 'The source is detected from the URL and queried for public metadata.',
  },
  {
    number: '02',
    title: 'Choose',
    body: 'Select from the resolutions, bitrates, or images that really exist.',
  },
  {
    number: '03',
    title: 'Collect',
    body: 'Watch the live job state, then save the completed file directly.',
  },
]

function Workflow() {
  return (
    <section className="py-20 sm:py-28">
      <div className="container grid gap-12 lg:grid-cols-[0.72fr_1.28fr] lg:gap-20">
        <div>
          <p className="font-mono text-[0.67rem] font-semibold uppercase tracking-[0.17em] text-primary">
            The workflow
          </p>
          <h2 className="mt-5 max-w-sm text-4xl font-semibold leading-[0.98] tracking-[-0.05em] sm:text-5xl">
            One clean path from link to file.
          </h2>
          <p className="mt-6 max-w-sm text-sm leading-6 text-muted-foreground">
            Every state is explicit. Nothing starts downloading until you choose the output.
          </p>
        </div>

        <ol className="border-t">
          {STEPS.map((step) => (
            <li key={step.number} className="group grid grid-cols-[3.5rem_1fr] gap-4 border-b py-7 sm:grid-cols-[5rem_10rem_1fr] sm:items-baseline">
              <span className="font-mono text-xs text-muted-foreground">{step.number}</span>
              <h3 className="text-xl font-semibold tracking-tight transition-transform duration-300 ease-smooth group-hover:translate-x-1">
                {step.title}
              </h3>
              <p className="col-start-2 text-sm leading-6 text-muted-foreground sm:col-start-3">
                {step.body}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

const TRUTHS = [
  { icon: Eye, title: 'Honest formats', body: 'Unavailable qualities never appear in the selector.' },
  { icon: Gauge, title: 'Visible progress', body: 'Status, transfer speed, and ETA come from the live job.' },
  { icon: ShieldCheck, title: 'Public media only', body: 'No DRM, paywall, private-account, or CAPTCHA bypasses.' },
  { icon: TimerReset, title: 'Temporary by design', body: 'Prepared files are automatically removed after expiry.' },
]

function TruthSection() {
  return (
    <section className="bg-[#11130e] py-20 text-[#f5f4ec] dark:bg-[#050604] sm:py-24">
      <div className="container">
        <div className="grid gap-8 border-b border-white/15 pb-12 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="font-mono text-[0.67rem] font-semibold uppercase tracking-[0.17em] text-primary">
              Product principles
            </p>
            <h2 className="mt-5 max-w-3xl text-4xl font-semibold leading-none tracking-[-0.05em] sm:text-5xl">
              Built to tell you the truth.
            </h2>
          </div>
          <ButtonLink to="/docs" variant="outline" className="border-white/20 text-white hover:bg-white/10 hover:text-white">
            Read the docs
            <ArrowRight aria-hidden />
          </ButtonLink>
        </div>

        <ul className="grid md:grid-cols-2 xl:grid-cols-4">
          {TRUTHS.map((item, index) => (
            <li key={item.title} className={cn('py-8 md:px-6', index > 0 && 'border-t border-white/15 md:border-t-0 md:border-l', index === 2 && 'md:border-l-0 xl:border-l')}>
              <item.icon className="size-5 text-primary" aria-hidden />
              <h3 className="mt-8 font-semibold">{item.title}</h3>
              <p className="mt-2 text-sm leading-6 text-white/52">{item.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

const FAQS = [
  {
    question: 'Do I need an account?',
    answer: 'Not when guest downloads are enabled. An account adds history and server-defined higher rate limits.',
  },
  {
    question: 'Why is a quality missing?',
    answer: 'Slipstream only lists formats the source genuinely exposes. Some combined formats also require FFmpeg on the server.',
  },
  {
    question: 'Can it download private or paid content?',
    answer: 'No. It does not bypass DRM, authentication, paywalls, private accounts, regional controls, or CAPTCHAs.',
  },
  {
    question: 'How long is a file available?',
    answer: 'The expiry window is configured by the server operator. The live result tells you when a completed file is ready to save.',
  },
]

function Faq() {
  const [open, setOpen] = useState<number | null>(0)

  return (
    <section className="py-20 sm:py-28">
      <div className="container grid gap-12 lg:grid-cols-[0.72fr_1.28fr] lg:gap-20">
        <div>
          <p className="font-mono text-[0.67rem] font-semibold uppercase tracking-[0.17em] text-primary">
            Before you paste
          </p>
          <h2 className="mt-5 text-4xl font-semibold leading-none tracking-[-0.05em]">
            Useful answers.
          </h2>
        </div>

        <div className="border-t">
          {FAQS.map((item, index) => {
            const expanded = open === index
            return (
              <section key={item.question} className="border-b">
                <h3>
                  <button
                    type="button"
                    onClick={() => setOpen(expanded ? null : index)}
                    aria-expanded={expanded}
                    className="flex min-h-16 w-full items-center justify-between gap-4 py-5 text-left font-medium focus-visible:ring-inset"
                  >
                    {item.question}
                    <ChevronDown className={cn('size-4 shrink-0 text-muted-foreground transition-transform duration-200', expanded && 'rotate-180')} aria-hidden />
                  </button>
                </h3>
                {expanded && (
                  <p className="animate-fade-in pb-6 pr-10 text-sm leading-6 text-muted-foreground">
                    {item.answer}
                  </p>
                )}
              </section>
            )
          })}
        </div>
      </div>
    </section>
  )
}
