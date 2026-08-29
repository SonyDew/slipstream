import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { ErrorBoundary } from '@/components/error-boundary'
import { AppLayout, AuthLayout } from '@/components/layout/app-layout'
import { Spinner } from '@/components/ui/spinner'
import { ToastProvider } from '@/components/ui/toast'
import { AuthProvider, useAuth } from '@/lib/auth-context'
import { ThemeProvider } from '@/lib/theme-context'
import { AboutPage } from '@/pages/about'
import { AccountPage } from '@/pages/account'
import { DocsPage } from '@/pages/docs'
import { HistoryPage } from '@/pages/history'
import { HomePage } from '@/pages/home'
import { LegalPage, NotFoundPage, PrivacyPage } from '@/pages/legal'
import { LoginPage } from '@/pages/login'
import { RegisterPage } from '@/pages/register'

// The admin area pulls in recharts, which is by far the largest dependency.
// Loading it on demand keeps it out of the bundle every visitor downloads.
const AdminLayout = lazy(() =>
  import('@/pages/admin/layout').then((module) => ({ default: module.AdminLayout })),
)
const AdminDashboardPage = lazy(() =>
  import('@/pages/admin/dashboard').then((module) => ({ default: module.AdminDashboardPage })),
)
const AdminUsersPage = lazy(() =>
  import('@/pages/admin/users').then((module) => ({ default: module.AdminUsersPage })),
)
const AdminDownloadsPage = lazy(() =>
  import('@/pages/admin/downloads').then((module) => ({ default: module.AdminDownloadsPage })),
)
const AdminJobsPage = lazy(() =>
  import('@/pages/admin/jobs').then((module) => ({ default: module.AdminJobsPage })),
)
const AdminAuditPage = lazy(() =>
  import('@/pages/admin/audit').then((module) => ({ default: module.AdminAuditPage })),
)
const AdminSettingsPage = lazy(() =>
  import('@/pages/admin/settings').then((module) => ({ default: module.AdminSettingsPage })),
)

/** Full-height placeholder used while a lazy chunk or the session probe loads. */
function RouteFallback() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Spinner label="Loading" />
    </div>
  )
}

/** Gate for routes that need any signed-in account. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <RouteFallback />
  if (!user) {
    // Remember where they were headed so sign-in can return them there.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return <>{children}</>
}

/** Gate for the admin area.
 *
 *  A non-admin is sent home rather than to sign-in: they are already
 *  authenticated, so prompting for credentials would be misleading. The server
 *  enforces this independently — this only keeps the UI honest.
 */
function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user, isAdmin, loading } = useAuth()
  const location = useLocation()

  if (loading) return <RouteFallback />
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  if (!isAdmin) return <Navigate to="/" replace />
  return <>{children}</>
}

/** Route table. Mirrors SPA_ROUTES in backend/app/main.py. */
function AppRoutes() {
  return (
    <Routes>
      {/* Auth pages get their own chrome-free shell. */}
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Route>

      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/legal" element={<LegalPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />

        <Route
          path="/account"
          element={
            <RequireAuth>
              <AccountPage />
            </RequireAuth>
          }
        />
        <Route
          path="/history"
          element={
            <RequireAuth>
              <HistoryPage />
            </RequireAuth>
          }
        />

        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <Suspense fallback={<RouteFallback />}>
                <AdminLayout />
              </Suspense>
            </RequireAdmin>
          }
        >
          <Route index element={<AdminDashboardPage />} />
          <Route path="users" element={<AdminUsersPage />} />
          <Route path="downloads" element={<AdminDownloadsPage />} />
          <Route path="jobs" element={<AdminJobsPage />} />
          <Route path="audit" element={<AdminAuditPage />} />
          <Route path="settings" element={<AdminSettingsPage />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
          <AuthProvider>
            <ToastProvider>
              <AppRoutes />
            </ToastProvider>
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  )
}
