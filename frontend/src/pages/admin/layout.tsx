import {
  AlertTriangle,
  ClipboardList,
  Download,
  KeyRound,
  LayoutDashboard,
  ListTree,
  Settings as SettingsIcon,
  Users,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { Alert } from '@/components/ui/feedback'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

const SECTIONS = [
  { to: '/admin', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/admin/users', label: 'Users', icon: Users, end: false },
  { to: '/admin/downloads', label: 'Downloads', icon: Download, end: false },
  { to: '/admin/jobs', label: 'Active jobs', icon: ListTree, end: false },
  { to: '/admin/audit', label: 'Audit log', icon: ClipboardList, end: false },
  { to: '/admin/settings', label: 'Settings', icon: SettingsIcon, end: false },
]

/** Shell for the admin area: section nav plus the routed section. */
export function AdminLayout() {
  const { mustChangePassword } = useAuth()

  return (
    <div className="container py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Administration</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Server state, accounts and runtime configuration for this deployment.
        </p>
      </header>

      {mustChangePassword && (
        <Alert
          tone="warning"
          icon={KeyRound}
          title="Administrator actions are blocked"
          className="mb-6"
        >
          This account is still using the bootstrap password. Change it on the account
          page to unlock changes here — reading remains available.
        </Alert>
      )}

      {/* Horizontal on mobile (scrollable), a sidebar from lg up. */}
      <div className="lg:grid lg:grid-cols-[13rem_1fr] lg:gap-8">
        <nav aria-label="Admin sections" className="mb-6 lg:mb-0">
          <ul className="flex gap-1 overflow-x-auto pb-1 lg:sticky lg:top-20 lg:flex-col lg:overflow-visible lg:pb-0">
            {SECTIONS.map((section) => (
              <li key={section.to} className="shrink-0 lg:shrink">
                <NavLink
                  to={section.to}
                  end={section.end}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      isActive
                        ? 'bg-accent text-accent-foreground'
                        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                    )
                  }
                >
                  <section.icon className="size-4" aria-hidden />
                  {section.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

/** Shown when a mutating admin action is refused for a temp-password admin. */
export function AdminBlockedNotice() {
  return (
    <Alert tone="warning" icon={AlertTriangle} title="Change your password first">
      Mutating actions stay disabled while this account uses the bootstrap password.
    </Alert>
  )
}
