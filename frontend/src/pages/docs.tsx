import { useEffect, useMemo, useState } from 'react'

import { PlatformIcon, platformMeta } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Alert } from '@/components/ui/feedback'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

interface Section {
  id: string
  title: string
  render: () => React.ReactNode
}

export function DocsPage() {
  const { config } = useAuth()
  const [active, setActive] = useState('overview')

  const platforms = useMemo(
    () =>
      (config?.platforms ?? []).filter(
        (platform) => !platform.is_fallback && platform.operational,
      ),
    [config],
  )

  const sections: Section[] = useMemo(
    () => [
      {
        id: 'overview',
        title: 'Overview',
        render: () => (
          <>
            <p>
              Slipstream is a self-hosted downloader for publicly accessible media. You
              paste a link, it inspects the source, and it offers the formats that
              genuinely exist for that item.
            </p>
            <p>
              Everything runs on the server you deployed it to. No third-party service
              sees your links, and no advertising or analytics code is served to your
              browser.
            </p>
            <h3>What you need</h3>
            <ul>
              <li>A link to a post that is viewable without signing in.</li>
              <li>Nothing else — accounts are optional.</li>
            </ul>
          </>
        ),
      },
      {
        id: 'platforms',
        title: 'Supported platforms',
        render: () => (
          <>
            <p>
              These platforms have dedicated handling, which means URL recognition and
              result normalisation are tuned for their quirks:
            </p>
            <ul className="!list-none !pl-0">
              {platforms.map((platform) => (
                <li key={platform.platform} className="!list-none">
                  <span className="inline-flex items-center gap-2">
                    <PlatformIcon platform={platform.platform} />
                    <strong>{platformMeta(platform.platform).label}</strong>
                    <span className="text-xs text-muted-foreground">
                      {platform.domains.slice(0, 3).join(', ')}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <p>
              Beyond these, any site the extraction engine supports — roughly 1,800 of
              them — is handled by the generic provider. It will not have
              platform-specific polish, but it usually works.
            </p>
            <p>
              An administrator can restrict which platforms are permitted, so a link may
              be refused on one deployment and accepted on another.
            </p>
          </>
        ),
      },
      {
        id: 'how-downloads-work',
        title: 'How downloads work',
        render: () => (
          <>
            <p>A download runs as a background job with a visible lifecycle:</p>
            <ul>
              <li>
                <strong>Queued</strong> — waiting for a free worker. Concurrency is
                capped so one large job cannot starve the server.
              </li>
              <li>
                <strong>Analysing</strong> — reading metadata and choosing a stream.
              </li>
              <li>
                <strong>Downloading</strong> — fetching bytes from the source, with
                speed and time remaining shown.
              </li>
              <li>
                <strong>Processing</strong> — combining video with audio, converting to
                MP3, or building a ZIP.
              </li>
              <li>
                <strong>Ready</strong> — the file is available to save.
              </li>
            </ul>
            <p>
              You can cancel at any point before it finishes. A finished file stays
              available for a short window and is then deleted.
            </p>
          </>
        ),
      },
      {
        id: 'video',
        title: 'Downloading video',
        render: () => (
          <>
            <p>
              The Video tab lists every resolution the source actually publishes —
              typically some subset of 2160p, 1440p, 1080p, 720p, 480p and 360p, plus
              <em> Best available</em>.
            </p>
            <h3>Why a resolution might be missing</h3>
            <ul>
              <li>The platform never published it for that item.</li>
              <li>
                It exists only as a separate video stream that needs FFmpeg to combine
                with audio, and FFmpeg is not installed on this server.
              </li>
            </ul>
            <p>
              Slipstream never lists a rung it cannot actually deliver. If it hid
              options for the second reason, you will see a note explaining it.
            </p>
            <h3>MP4 or WebM</h3>
            <p>
              MP4 is the safest choice and plays everywhere. WebM sometimes offers a
              higher-quality stream at the same size, but has patchier support in older
              players and editing software.
            </p>
          </>
        ),
      },
      {
        id: 'audio',
        title: 'Downloading MP3',
        render: () => (
          <>
            <p>
              The MP3 tab converts the source audio using FFmpeg. Available bitrates are
              320, 256, 192 and 128 kbps, plus <em>Best available</em>.
            </p>
            <Alert tone="info" className="my-4">
              Bitrates above the source are deliberately not offered. Re-encoding
              128 kbps audio at 320 kbps produces a file two and a half times larger
              containing exactly the same information.
            </Alert>
            <p>
              If the source bitrate is unknown before decoding, the full ladder is shown
              and the encoder caps to the real value at conversion time. You therefore
              never receive a file whose advertised bitrate is a fiction.
            </p>
            <p>
              MP3 conversion requires FFmpeg. Without it, the MP3 tab does not appear.
            </p>
          </>
        ),
      },
      {
        id: 'images',
        title: 'Photo posts and slideshows',
        render: () => (
          <>
            <p>
              TikTok and Douyin publish photo posts as well as video. Slipstream detects
              these and shows an Images tab with every picture in the post.
            </p>
            <ul>
              <li>Tap any image to select it; tap again to deselect.</li>
              <li>With nothing selected, all images are downloaded.</li>
              <li>A single image downloads directly; multiple images arrive as a ZIP.</li>
              <li>
                When the post has a soundtrack, an extra button downloads that audio as
                MP3.
              </li>
            </ul>
            <p>
              Images are fetched at the largest size the platform serves publicly.
            </p>
          </>
        ),
      },
      {
        id: 'accounts',
        title: 'Accounts',
        render: () => (
          <>
            <p>
              Downloading works without an account. Signing in adds:
            </p>
            <ul>
              <li>A download history you can browse and clear.</li>
              <li>Higher rate limits than anonymous visitors.</li>
              <li>Account settings and session management.</li>
            </ul>
            <p>
              Passwords are hashed with Argon2id and never stored in a recoverable form.
              Sessions use an HttpOnly cookie, so no token is exposed to JavaScript.
              Changing your password signs out all other sessions.
            </p>
            <p>
              An administrator may disable registration, in which case accounts must be
              created for you.
            </p>
          </>
        ),
      },
      {
        id: 'privacy',
        title: 'Privacy and retention',
        render: () => (
          <>
            <h3>Downloaded files</h3>
            <p>
              Stored temporarily so your browser can fetch them, then deleted by a
              scheduled cleanup job. Nothing is kept as a permanent library.
            </p>
            <h3>History</h3>
            <p>
              Recorded only for signed-in accounts, and only as metadata: title, author,
              platform, quality, size and outcome. Guest downloads leave no record.
              Retention is configurable and defaults to 90 days.
            </p>
            <h3>Addresses</h3>
            <p>
              Guest rate limiting needs to distinguish clients, so an IP is stored as a
              salted hash rather than the address itself. A database dump cannot be
              reversed into a list of visitors.
            </p>
            <h3>Logs</h3>
            <p>
              Structured logs record job outcomes and security events. Passwords,
              session tokens, cookies and secret keys are filtered out before anything
              is written.
            </p>
          </>
        ),
      },
      {
        id: 'limitations',
        title: 'Limitations',
        render: () => (
          <>
            <p>Some things are out of scope by design, and others by circumstance.</p>
            <h3>Deliberately not supported</h3>
            <ul>
              <li>DRM-protected media.</li>
              <li>Paywalled or subscriber-only content.</li>
              <li>Private accounts and posts requiring a login.</li>
              <li>Age-gated content requiring account verification.</li>
              <li>CAPTCHA or bot-check circumvention.</li>
            </ul>
            <p>
              These are access controls. Slipstream does not attempt to defeat them, and
              requests for such content fail with a clear message.
            </p>
            <h3>Practical limitations</h3>
            <ul>
              <li>
                Extractors break when platforms change. This is the most common cause of
                a link that worked last week failing today; updating usually fixes it.
              </li>
              <li>
                Some platforms rate-limit or geo-block servers. Douyin in particular is
                unreliable from outside mainland China.
              </li>
              <li>
                Vimeo currently blocks anonymous extractor access. Its URLs are still
                recognized, but public downloading is marked temporarily unavailable
                instead of being misreported as private content.
              </li>
              <li>Live streams cannot be downloaded while still broadcasting.</li>
              <li>
                File size and video duration limits are set by the administrator and
                will refuse very large items.
              </li>
            </ul>
          </>
        ),
      },
      {
        id: 'errors',
        title: 'Common errors',
        render: () => (
          <>
            <dl className="space-y-4">
              {[
                ['That does not look like a valid link', 'Paste the full URL, including https://.'],
                [
                  'This site is not supported yet',
                  'No provider matched, and the generic extractor found nothing usable.',
                ],
                [
                  'That address is not allowed',
                  'The link points at a private or internal network address, which is blocked for security reasons.',
                ],
                [
                  'This media is unavailable',
                  'The post was deleted, made private, or never existed.',
                ],
                [
                  'This content is private or restricted',
                  'Only publicly accessible media can be processed.',
                ],
                [
                  'The extractor could not read this link',
                  'Usually a platform-side change. Try again later or ask the administrator to update the extraction engine.',
                ],
                [
                  'Rate limit reached',
                  'You have made too many requests this hour. Wait, or sign in for a higher limit.',
                ],
                [
                  'This file exceeds the maximum allowed size',
                  'The item is larger than the administrator permits. Try a lower quality.',
                ],
                [
                  'This download has expired',
                  'Finished files are removed after a short window. Analyse the link again.',
                ],
              ].map(([term, description]) => (
                <div key={term}>
                  <dt className="font-medium text-foreground">{term}</dt>
                  <dd className="mt-1">{description}</dd>
                </div>
              ))}
            </dl>
          </>
        ),
      },
      {
        id: 'api',
        title: 'API usage',
        render: () => (
          <>
            <p>
              The same JSON API the interface uses is available directly. All endpoints
              are under <code>/api</code> on this host. Interactive reference:{' '}
              <a href="/api/docs">/api/docs</a>.
            </p>
            <h3>Analyse a link</h3>
            <pre>{`curl -X POST ${originHint()}/api/media/analyze \\
  -H 'Content-Type: application/json' \\
  -d '{"url":"https://www.youtube.com/watch?v=..."}'`}</pre>
            <h3>Start a download</h3>
            <pre>{`curl -X POST ${originHint()}/api/download \\
  -H 'Content-Type: application/json' \\
  -d '{"url":"...","mode":"video","quality":"1080","container":"mp4"}'`}</pre>
            <p>
              <code>quality</code> accepts <code>best</code> or a numeric rung that the
              analyse response listed. Arbitrary format selectors are rejected.
            </p>
            <h3>Poll and fetch</h3>
            <pre>{`curl ${originHint()}/api/jobs/<job_id>
curl -OJ ${originHint()}/api/jobs/<job_id>/file`}</pre>
            <h3>Authentication</h3>
            <p>
              Session cookies are used, not bearer tokens. Sign in with{' '}
              <code>POST /api/auth/login</code>, keep the cookie jar, and echo the{' '}
              <code>slipstream_csrf</code> cookie in an <code>X-CSRF-Token</code> header
              on any non-GET request.
            </p>
            <pre>{`curl -c jar -X POST ${originHint()}/api/auth/login \\
  -H 'Content-Type: application/json' \\
  -d '{"username":"you","password":"..."}'`}</pre>
            <h3>Rate limits</h3>
            <p>
              Responses include <code>X-RateLimit-Limit</code> and{' '}
              <code>X-RateLimit-Remaining</code>. A 429 includes{' '}
              <code>Retry-After</code>. Errors share one envelope:
            </p>
            <pre>{`{"error":{"code":"invalid_url","message":"...","retryable":false}}`}</pre>
          </>
        ),
      },
    ],
    [platforms],
  )

  // Highlight the section currently in view.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-96px 0px -70% 0px', threshold: 0 },
    )
    for (const section of sections) {
      const element = document.getElementById(section.id)
      if (element) observer.observe(element)
    }
    return () => observer.disconnect()
  }, [sections])

  return (
    <div className="container py-12">
      <header className="mb-10 max-w-2xl">
        <Badge variant="outline" className="mb-4">
          Documentation
        </Badge>
        <h1 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
          How to use Slipstream
        </h1>
        <p className="mt-3 text-muted-foreground">
          Everything about supported platforms, quality options, accounts, privacy and
          the API.
        </p>
      </header>

      <div className="grid gap-10 lg:grid-cols-[220px_minmax(0,1fr)]">
        {/* Sticky table of contents */}
        <nav aria-label="On this page" className="lg:sticky lg:top-24 lg:self-start">
          <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            On this page
          </p>
          <ul className="space-y-0.5">
            {sections.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className={cn(
                    'block rounded-md px-3 py-1.5 text-sm transition-colors',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    active === section.id
                      ? 'bg-accent font-medium text-accent-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 max-w-3xl">
          {sections.map((section) => (
            <section key={section.id} id={section.id} className="scroll-mt-24 border-t py-10 first:border-t-0 first:pt-0">
              <h2 className="!mt-0 mb-4 text-xl font-semibold tracking-tight">{section.title}</h2>
              <div className="prose-doc">{section.render()}</div>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

/** Use the real origin in copyable examples so they work as pasted. */
function originHint(): string {
  if (typeof window === 'undefined') return 'https://example.com'
  return window.location.origin
}
