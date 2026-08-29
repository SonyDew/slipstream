import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { ApiError, api } from '@/lib/api'
import type { PublicConfig, User } from '@/lib/types'

interface AuthContextValue {
  user: User | null
  config: PublicConfig | null
  /** True until the initial session + config probe finishes. */
  loading: boolean
  login: (username: string, password: string) => Promise<User>
  register: (username: string, email: string, password: string) => Promise<User>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  refreshConfig: () => Promise<void>
  isAdmin: boolean
  mustChangePassword: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [config, setConfig] = useState<PublicConfig | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const { user: current } = await api.me()
      setUser(current)
    } catch {
      // A failed probe means "not signed in" as far as the UI is concerned.
      setUser(null)
    }
  }, [])

  const refreshConfig = useCallback(async () => {
    try {
      setConfig(await api.config())
    } catch {
      // Leave the previous config in place; the app still works without it.
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    // Both probes are independent, so run them together.
    void Promise.allSettled([api.me(), api.config()]).then(([session, configuration]) => {
      if (cancelled) return
      if (session.status === 'fulfilled') setUser(session.value.user)
      if (configuration.status === 'fulfilled') setConfig(configuration.value)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const { user: signedIn } = await api.login(username, password)
    setUser(signedIn)
    return signedIn
  }, [])

  const register = useCallback(async (username: string, email: string, password: string) => {
    const { user: created } = await api.register(username, email, password)
    setUser(created)
    return created
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch (error) {
      // An expired session already achieves the goal; anything else is worth
      // surfacing to the caller.
      if (!(error instanceof ApiError) || error.status !== 401) throw error
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      config,
      loading,
      login,
      register,
      logout,
      refresh,
      refreshConfig,
      isAdmin: Boolean(user?.is_admin),
      mustChangePassword: Boolean(user?.must_change_password),
    }),
    [user, config, loading, login, register, logout, refresh, refreshConfig],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
