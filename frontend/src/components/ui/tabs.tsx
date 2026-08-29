import { createContext, useContext, useId, useMemo, useState } from 'react'

import { cn } from '@/lib/utils'

interface TabsContextValue {
  value: string
  setValue: (value: string) => void
  baseId: string
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabs(component: string): TabsContextValue {
  const context = useContext(TabsContext)
  if (!context) throw new Error(`<${component}> must be used inside <Tabs>`)
  return context
}

interface TabsProps {
  value?: string
  defaultValue: string
  onValueChange?: (value: string) => void
  className?: string
  children: React.ReactNode
}

/** Accessible tabs supporting both controlled and uncontrolled use. */
export function Tabs({ value, defaultValue, onValueChange, className, children }: TabsProps) {
  const [internal, setInternal] = useState(defaultValue)
  const baseId = useId()
  const active = value ?? internal

  const context = useMemo<TabsContextValue>(
    () => ({
      value: active,
      setValue: (next) => {
        if (value === undefined) setInternal(next)
        onValueChange?.(next)
      },
      baseId,
    }),
    [active, value, onValueChange, baseId],
  )

  return (
    <TabsContext.Provider value={context}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

export function TabsList({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex h-11 items-center justify-center gap-1 rounded-xl border bg-muted/55 p-1 text-muted-foreground',
        className,
      )}
    >
      {children}
    </div>
  )
}

interface TabsTriggerProps {
  value: string
  disabled?: boolean
  className?: string
  children: React.ReactNode
}

export function TabsTrigger({ value, disabled, className, children }: TabsTriggerProps) {
  const tabs = useTabs('TabsTrigger')
  const selected = tabs.value === value

  return (
    <button
      type="button"
      role="tab"
      id={`${tabs.baseId}-tab-${value}`}
      aria-selected={selected}
      aria-controls={`${tabs.baseId}-panel-${value}`}
      tabIndex={selected ? 0 : -1}
      disabled={disabled}
      onClick={() => tabs.setValue(value)}
      onKeyDown={(event) => {
        // Arrow-key navigation is expected behaviour for a tablist.
        if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
        const list = event.currentTarget.parentElement
        if (!list) return
        const enabled = Array.from(
          list.querySelectorAll<HTMLButtonElement>('[role="tab"]:not([disabled])'),
        )
        const index = enabled.indexOf(event.currentTarget)
        const step = event.key === 'ArrowRight' ? 1 : -1
        const next = enabled[(index + step + enabled.length) % enabled.length]
        next?.focus()
        next?.click()
      }}
      className={cn(
        'inline-flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5',
        'text-sm font-medium transition-all duration-200 ease-smooth',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        'disabled:pointer-events-none disabled:opacity-40',
        '[&_svg]:size-4',
        selected ? 'bg-foreground text-background shadow-soft' : 'hover:bg-background/60 hover:text-foreground',
        className,
      )}
    >
      {children}
    </button>
  )
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string
  className?: string
  children: React.ReactNode
}) {
  const tabs = useTabs('TabsContent')
  if (tabs.value !== value) return null

  return (
    <div
      role="tabpanel"
      id={`${tabs.baseId}-panel-${value}`}
      aria-labelledby={`${tabs.baseId}-tab-${value}`}
      tabIndex={0}
      className={cn('mt-4 animate-fade-in focus-visible:outline-none', className)}
    >
      {children}
    </div>
  )
}
