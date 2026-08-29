import {
  BookOpen,
  ChevronDown,
  Clock,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  Shield,
  User as UserIcon,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/layout/logo'
import { ThemeToggle } from '@/components/layout/theme-toggle'
import { Badge } from '@/components/ui/badge'
import { Button, ButtonLink } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

const NAV_LINKS = [
  { to: '/', label: 'Download' },
  { to: '/docs', label: 'Documentation' },
  { to: '/about', label: 'About' },
]

export function Navbar() {
  const { user, isAdmin, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  // Close the mobile sheet whenever the route changes.
  useEffect(() => setMobileOpen(false), [location.pathname])

  // Add a border/shadow once the page scrolls, so the header separates from
  // content without being visually heavy at rest.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [mobileOpen])

  const handleLogout = async () => {
    try {
      await logout()
      toast.success('Signed out')
      navigate('/')
    } catch {
      toast.error('Could not sign out', 'Please try again.')
    }
  }

  return (
    <header
      className={cn(
        'sticky top-0 z-50 w-full border-b border-transparent transition-[background-color,border-color] duration-300',
        scrolled ? 'glass border-border' : 'bg-background/85',
      )}
    >
      <div className="container flex h-[4.25rem] items-center justify-between gap-4">
        <Link
          to="/"
          className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Slipstream home"
        >
          <Logo />
        </Link>

        {/* Desktop navigation */}
        <nav className="hidden items-center gap-6 md:flex" aria-label="Main">
          {NAV_LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                cn(
                  'relative rounded py-2 text-[0.72rem] font-semibold uppercase tracking-[0.12em] transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  isActive
                    ? 'text-foreground after:absolute after:-bottom-[1.15rem] after:left-0 after:h-0.5 after:w-full after:bg-primary'
                    : 'text-muted-foreground hover:text-foreground',
                )
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center gap-1.5">
          <ThemeToggle />

          {user ? (
            <UserMenu onLogout={handleLogout} />
          ) : (
            <div className="hidden items-center gap-2 md:flex">
              <ButtonLink variant="ghost" size="sm" to="/login">
                Sign in
              </ButtonLink>
              <ButtonLink variant="brand" size="sm" to="/register">
                Create account
              </ButtonLink>
            </div>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileOpen((value) => !value)}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          >
            {mobileOpen ? <X aria-hidden /> : <Menu aria-hidden />}
          </Button>
        </div>
      </div>

      {/* Mobile sheet */}
      {mobileOpen && (
        <div className="absolute inset-x-0 top-full h-[calc(100svh-4.25rem)] animate-fade-in border-t bg-background md:hidden">
          <nav className="container flex h-full flex-col gap-1 py-6" aria-label="Mobile">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'rounded-xl px-3 py-3 text-lg font-medium tracking-tight',
                    isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground',
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}

            <div className="my-4 h-px bg-border" />

            {user ? (
              <>
                <MobileLink to="/account" icon={UserIcon} label="Account" />
                <MobileLink to="/history" icon={Clock} label="History" />
                {isAdmin && <MobileLink to="/admin" icon={Shield} label="Admin" />}
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-muted-foreground"
                >
                  <LogOut className="size-4" aria-hidden />
                  Sign out
                </button>
              </>
            ) : (
              <div className="flex flex-col gap-2 pt-1">
                <ButtonLink variant="outline" to="/login">
                  Sign in
                </ButtonLink>
                <ButtonLink variant="brand" to="/register">
                  Create account
                </ButtonLink>
              </div>
            )}
          </nav>
        </div>
      )}
    </header>
  )
}

function MobileLink({
  to,
  icon: Icon,
  label,
}: {
  to: string
  icon: typeof UserIcon
  label: string
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium',
          isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground',
        )
      }
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </NavLink>
  )
}

function UserMenu({ onLogout }: { onLogout: () => void }) {
  const { user, isAdmin, mustChangePassword } = useAuth()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (!user) return null

  const initial = user.username.charAt(0).toUpperCase()

  return (
    <div ref={containerRef} className="relative hidden md:block">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          'flex items-center gap-2 rounded-lg py-1.5 pl-1.5 pr-2 text-sm font-medium transition-colors',
          'hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        )}
      >
        <span
          className="grid size-7 place-items-center rounded-md bg-brand-gradient text-xs font-semibold text-white"
          aria-hidden
        >
          {initial}
        </span>
        <span className="max-w-[10rem] truncate">{user.username}</span>
        {mustChangePassword && (
          <span
            className="size-1.5 rounded-full bg-warning"
            aria-label="Password change required"
          />
        )}
        <ChevronDown
          className={cn('size-4 text-muted-foreground transition-transform', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-56 animate-scale-in overflow-hidden rounded-lg border bg-popover p-1 shadow-lifted"
        >
          <div className="border-b px-3 py-2.5">
            <p className="truncate text-sm font-medium">{user.username}</p>
            {user.email && (
              <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            )}
            {isAdmin && (
              <Badge variant="default" className="mt-1.5">
                <Shield aria-hidden />
                Administrator
              </Badge>
            )}
          </div>

          <MenuLink to="/account" icon={Settings} label="Account settings" onNavigate={() => setOpen(false)} />
          <MenuLink to="/history" icon={Clock} label="Download history" onNavigate={() => setOpen(false)} />
          <MenuLink to="/docs" icon={BookOpen} label="Documentation" onNavigate={() => setOpen(false)} />
          {isAdmin && (
            <MenuLink
              to="/admin"
              icon={LayoutDashboard}
              label="Admin panel"
              onNavigate={() => setOpen(false)}
            />
          )}

          <div className="my-1 h-px bg-border" />

          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onLogout()
            }}
            className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <LogOut className="size-4" aria-hidden />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

function MenuLink({
  to,
  icon: Icon,
  label,
  onNavigate,
}: {
  to: string
  icon: typeof UserIcon
  label: string
  onNavigate: () => void
}) {
  return (
    <Link
      to={to}
      role="menuitem"
      onClick={onNavigate}
      className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Icon className="size-4 text-muted-foreground" aria-hidden />
      {label}
    </Link>
  )
}
