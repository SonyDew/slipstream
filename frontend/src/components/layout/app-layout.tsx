import { AlertTriangle, KeyRound, Wrench } from 'lucide-react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { useEffect } from 'react'

import { Footer } from '@/components/layout/footer'
import { Navbar } from '@/components/layout/navbar'
import { Alert } from '@/components/ui/feedback'
import { useAuth } from '@/lib/auth-context'

/** Application shell: header, banners, routed content, footer. */
export function AppLayout() {
  const { config, user, mustChangePassword } = useAuth()
  const location = useLocation()

  // Scroll to top on navigation, but honour in-page anchors.
  useEffect(() => {
    if (location.hash) {
      const target = document.getElementById(location.hash.slice(1))
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
    }
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
  }, [location.pathname, location.hash])

  const showMaintenance = Boolean(config?.maintenance_mode)
  const showPasswordBanner = Boolean(user && mustChangePassword)

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[200] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        Skip to content
      </a>

      <Navbar />

      {(showMaintenance || showPasswordBanner) && (
        <div className="container mt-4 space-y-3">
          {showMaintenance && (
            <Alert tone="warning" icon={Wrench} title="Maintenance mode is on">
              Downloads are paused for everyone except administrators.
            </Alert>
          )}
          {showPasswordBanner && (
            <Alert
              tone="warning"
              icon={KeyRound}
              title="Change your temporary password"
              action={
                <Link
                  to="/account"
                  className="rounded-lg bg-warning px-3 py-1.5 text-xs font-medium text-warning-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Change now
                </Link>
              }
            >
              This account still uses the temporary bootstrap password.
              {user?.is_admin
                ? ' Administrator actions stay blocked until it is changed.'
                : ' Please choose your own password.'}
            </Alert>
          )}
        </div>
      )}

      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <Footer />
    </div>
  )
}

/** Bare shell for the auth pages: no nav chrome competing with the form. */
export function AuthLayout() {
  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-[minmax(18rem,0.72fr)_1fr]">
      <aside className="relative hidden overflow-hidden border-r bg-foreground p-10 text-background lg:flex lg:flex-col lg:justify-between">
        <div className="stream-lines absolute inset-0 opacity-20" aria-hidden />
        <div className="relative font-mono text-xs uppercase tracking-[0.16em] text-primary">
          Slipstream / access
        </div>
        <div className="relative max-w-sm">
          <span className="signal-dot mb-6" aria-hidden />
          <p className="text-4xl font-semibold leading-[0.98] tracking-[-0.05em]">
            Your media utility, on your hardware.
          </p>
          <p className="mt-5 max-w-xs text-sm leading-6 text-background/60">
            Accounts add history and higher limits. The downloader works without one when the server allows it.
          </p>
        </div>
        <p className="relative font-mono text-[0.65rem] uppercase tracking-[0.14em] text-background/45">
          No ads · no trackers · temporary files
        </p>
      </aside>
      <div className="flex min-h-screen items-center justify-center px-4 py-10 sm:px-8">
        <Outlet />
      </div>
    </div>
  )
}

/** Shown when a route needs an account and there is none. */
export function RequireAuthFallback() {
  return (
    <div className="container py-24">
      <Alert tone="warning" icon={AlertTriangle} title="Sign in required">
        <div className="mt-2">
          <Link to="/login" className="font-medium text-foreground underline underline-offset-2">
            Sign in
          </Link>{' '}
          to view this page.
        </div>
      </Alert>
    </div>
  )
}
