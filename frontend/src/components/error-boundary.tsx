import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** Catches render-time crashes so a single broken page cannot blank the app.
 *
 *  Recovery is a full reload rather than a state reset: if a component threw
 *  while rendering, the surrounding state is no longer trustworthy.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The server never sees this; the browser console is the only place a
    // self-hoster can inspect it.
    console.error('Unhandled error in the interface:', error, info.componentStack)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="flex min-h-screen items-center justify-center px-4 py-16">
        <div className="w-full max-w-lg rounded-xl border bg-card p-8 text-center shadow-card">
          <span className="mx-auto grid size-12 place-items-center rounded-full bg-destructive/10 text-destructive">
            <AlertTriangle className="size-6" aria-hidden />
          </span>
          <h1 className="mt-5 text-lg font-semibold tracking-tight">
            The interface hit an unexpected error
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Reloading usually clears it. If it keeps happening, the browser console has
            the details worth reporting.
          </p>
          <p className="mt-4 break-words rounded-lg bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
            {error.message || error.name}
          </p>
          <Button variant="brand" className="mt-6" onClick={() => window.location.reload()}>
            <RefreshCw aria-hidden />
            Reload the page
          </Button>
        </div>
      </div>
    )
  }
}
