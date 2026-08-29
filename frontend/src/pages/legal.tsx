import { FileSearch, Home, Scale, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ButtonLink } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert } from '@/components/ui/feedback'

/* -------------------------------------------------------------------------- */
/* Acceptable use                                                              */
/* -------------------------------------------------------------------------- */

export function LegalPage() {
  return (
    <div className="container max-w-3xl py-12">
      <header className="mb-10">
        <Badge variant="outline" className="mb-4">
          <Scale aria-hidden />
          Acceptable use
        </Badge>
        <h1 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
          What this tool will and will not do
        </h1>
        <p className="mt-3 text-muted-foreground">
          Plain terms, no legalese theatre. This page describes the technical boundaries
          the software enforces and the responsibilities that remain yours.
        </p>
      </header>

      <div className="prose-doc max-w-none">
        <Alert tone="warning" className="mb-8">
          Downloading content you do not have the right to copy may be unlawful where you
          live, regardless of what any tool makes technically possible. Slipstream cannot
          and does not assess whether you hold that right.
        </Alert>

        <h2 id="not-supported">Access controls are never bypassed</h2>
        <p>
          Slipstream deliberately contains no functionality for defeating access controls.
          Specifically, it does not implement, and will not be extended to implement:
        </p>
        <ul>
          <li>DRM decryption or circumvention of any kind.</li>
          <li>Paywall or subscription bypasses.</li>
          <li>Access to private accounts, private posts or unlisted-but-protected media.</li>
          <li>Authentication bypasses, credential stuffing or session forgery.</li>
          <li>CAPTCHA solving or bot-detection evasion.</li>
          <li>Age-verification bypasses.</li>
          <li>Premium-tier or region-lock circumvention.</li>
        </ul>
        <p>
          Requests for such content fail with an explanatory message. This is a design
          decision, not an oversight, and pull requests adding these capabilities will not
          be accepted.
        </p>

        <h2 id="what-is-processed">What is processed</h2>
        <p>
          Only media that is publicly accessible without authentication, or that you are
          otherwise authorised to access. The server fetches the same bytes a normal
          visitor&apos;s browser would receive from the same public URL.
        </p>

        <h2 id="your-responsibility">Your responsibility</h2>
        <p>By using this deployment you confirm that:</p>
        <ul>
          <li>
            You own the content, hold a licence to it, have the rights-holder&apos;s
            permission, or your use is covered by an exception in your jurisdiction such
            as fair use, fair dealing, private copying or quotation.
          </li>
          <li>
            You have read and will comply with the terms of service of the platform you
            are downloading from. Many prohibit downloading outright, and those terms bind
            you regardless of technical feasibility.
          </li>
          <li>
            You will not redistribute downloaded material without the necessary rights.
          </li>
          <li>
            You will not use this service to infringe copyright, harass anyone, or violate
            any applicable law.
          </li>
        </ul>

        <h2 id="operator">If you operate this server</h2>
        <p>
          Running a public instance may create obligations for you, including responding to
          takedown notices and complying with intermediary-liability rules in your
          jurisdiction. Consider whether your instance should be private or restricted to
          accounts you control, and review the security guidance shipped in{' '}
          <code>docs/SECURITY.md</code>.
        </p>

        <h2 id="no-warranty">No warranty</h2>
        <p>
          This software is provided as-is, without warranty of any kind. Extraction from
          third-party platforms is inherently fragile and may stop working without notice.
          The authors accept no liability for how any deployment is used.
        </p>

        <h2 id="reporting">Reporting a problem</h2>
        <p>
          If you are a rights-holder with a concern about a specific deployment, contact
          the operator of that instance — the maintainers of this software do not host it
          and have no access to it. Security issues in the software itself should follow
          the process in <code>SECURITY.md</code>.
        </p>
      </div>

      <div className="mt-10 flex flex-wrap gap-3">
        <ButtonLink to="/privacy" variant="outline">
          Privacy
        </ButtonLink>
        <ButtonLink to="/docs#limitations" variant="outline">
          Technical limitations
        </ButtonLink>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Privacy                                                                     */
/* -------------------------------------------------------------------------- */

export function PrivacyPage() {
  return (
    <div className="container max-w-3xl py-12">
      <header className="mb-10">
        <Badge variant="outline" className="mb-4">
          <ShieldCheck aria-hidden />
          Privacy
        </Badge>
        <h1 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
          What this server stores
        </h1>
        <p className="mt-3 text-muted-foreground">
          Slipstream is self-hosted, so this describes the software&apos;s behaviour. The
          operator of this particular instance controls the settings.
        </p>
      </header>

      <div className="prose-doc max-w-none">
        <h2 id="no-third-parties">No third parties</h2>
        <p>
          The interface loads no analytics, advertising, tag managers, external fonts or
          third-party scripts. Network requests go to this server and, for thumbnail
          images, to the source platform&apos;s CDN. Thumbnails are requested with a
          no-referrer policy so the platform is not told which page you were on.
        </p>

        <h2 id="downloaded-files">Downloaded files</h2>
        <p>
          Media is written to a temporary directory so your browser can fetch it, then
          deleted by a scheduled cleanup job once its expiry window passes (two hours by
          default). Cancelled and failed jobs have their partial data removed immediately.
          Nothing is retained as a library.
        </p>

        <h2 id="history">Download history</h2>
        <p>
          Recorded only for signed-in accounts, and only as metadata — title, author,
          platform, media type, quality, file size, outcome and timestamp. The full URL is
          retained for your own reference and is visible only to you and administrators.
          You can delete individual entries or clear everything from your account page.
          Retention defaults to 90 days.
        </p>
        <p>
          <strong>Guest downloads create no history record at all.</strong>
        </p>

        <h2 id="accounts">Account data</h2>
        <p>
          A username, an email address, and an Argon2id password hash. The hash cannot be
          reversed into your password. Sessions are stored server-side, and only a SHA-256
          hash of each session token is kept, so a database leak does not yield usable
          sessions.
        </p>

        <h2 id="addresses">IP addresses</h2>
        <p>
          Rate limiting has to tell clients apart. For guests, the address is stored as a
          salted SHA-256 hash rather than the address itself, so it cannot be reversed into
          a list of visitors. Session records store a truncated address and user agent so
          you can recognise your own sign-ins.
        </p>

        <h2 id="logs">Logs</h2>
        <p>
          Structured logs record requests, job outcomes, extractor failures, security
          events and administrator actions. A redaction filter strips passwords, session
          tokens, CSRF tokens, cookies, authorisation headers and secret keys before
          anything is written. Query strings are omitted from request logs, because they
          can contain the media URL you pasted.
        </p>

        <h2 id="admin-visibility">What administrators can see</h2>
        <p>
          Administrators can see accounts, aggregate statistics, the download ledger and
          the audit log. The ledger deliberately shows the source <em>domain</em> rather
          than the full URL, so share tokens and tracking parameters are not put on screen.
          Administrators cannot see your password, and every privileged action they take is
          recorded in the audit log.
        </p>

        <h2 id="your-controls">Your controls</h2>
        <ul>
          <li>Download as a guest to leave no record.</li>
          <li>Clear your history at any time from the account page.</li>
          <li>Sign out of every device from the account page.</li>
          <li>Ask the operator to delete your account entirely.</li>
        </ul>
      </div>

      <div className="mt-10 flex flex-wrap gap-3">
        <ButtonLink to="/legal" variant="outline">
          Acceptable use
        </ButtonLink>
        <ButtonLink to="/docs#privacy" variant="outline">
          Retention details
        </ButtonLink>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 404                                                                         */
/* -------------------------------------------------------------------------- */

export function NotFoundPage() {
  return (
    <div className="container flex min-h-[60vh] max-w-lg flex-col items-center justify-center py-16 text-center">
      <div className="mb-6 grid size-14 place-items-center rounded-2xl bg-muted">
        <FileSearch className="size-7 text-muted-foreground" aria-hidden />
      </div>
      <p className="font-mono text-sm text-muted-foreground">404</p>
      <h1 className="mt-2 text-balance text-2xl font-semibold tracking-tight">
        This page does not exist
      </h1>
      <p className="mt-3 text-muted-foreground">
        The link may be out of date, or the address might have a typo.
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-3">
        <ButtonLink to="/" variant="brand">
          <Home aria-hidden />
          Go to the downloader
        </ButtonLink>
        <ButtonLink to="/docs" variant="outline">
          Documentation
        </ButtonLink>
      </div>
      <p className="mt-8 text-sm text-muted-foreground">
        Looking for the API? See{' '}
        <Link to="/docs#api" className="font-medium text-primary underline underline-offset-2">
          API usage
        </Link>
        .
      </p>
    </div>
  )
}
