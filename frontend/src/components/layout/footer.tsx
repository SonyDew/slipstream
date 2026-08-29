import { Github } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Logo } from '@/components/layout/logo'
import { useAuth } from '@/lib/auth-context'

const LINKS = [
  { to: '/', label: 'Download' },
  { to: '/docs', label: 'Docs' },
  { to: '/history', label: 'History' },
  { to: '/about', label: 'Status' },
  { to: '/legal', label: 'Use policy' },
  { to: '/privacy', label: 'Privacy' },
]

export function Footer() {
  const { config } = useAuth()

  return (
    <footer className="border-t bg-card">
      <div className="container py-10 sm:py-12">
        <div className="flex flex-col justify-between gap-8 lg:flex-row lg:items-start">
          <div className="max-w-sm">
            <Logo />
            <p className="mt-4 text-sm leading-6 text-muted-foreground">
              Self-hosted tooling for publicly accessible media. No ads, no trackers,
              and no access-control bypasses.
            </p>
          </div>

          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-10 gap-y-3 sm:flex sm:flex-wrap sm:justify-end">
            {LINKS.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className="rounded text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="mt-10 flex flex-col gap-4 border-t pt-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>
            © {new Date().getFullYear()} Slipstream · v{config?.version ?? '—'} · Files are temporary.
          </p>
          <a
            href="https://github.com/yt-dlp/yt-dlp"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded transition-colors hover:text-foreground focus-visible:ring-2"
          >
            <Github className="size-3.5" aria-hidden />
            Extraction powered by yt-dlp
          </a>
        </div>
      </div>
    </footer>
  )
}
