import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/* -------------------------------------------------------------------------- */
/* Table primitives                                                            */
/* -------------------------------------------------------------------------- */

/** Table wrapper.
 *
 *  The horizontal scroll lives on this container, never on the page body — a
 *  wide admin table must not make the whole document scroll sideways.
 */
export function TableWrapper({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('w-full overflow-x-auto rounded-xl border bg-card shadow-subtle', className)}>{children}</div>
  )
}

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full caption-bottom text-sm', className)} {...props} />
}

export function THead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn('bg-muted/45 [&_tr]:border-b', className)} {...props} />
}

export function TBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}

export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn('border-b transition-colors hover:bg-muted/40 data-[state=selected]:bg-muted', className)}
      {...props}
    />
  )
}

export function TH({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'h-11 whitespace-nowrap px-4 text-left align-middle text-xs font-semibold uppercase tracking-wide text-muted-foreground',
        className,
      )}
      {...props}
    />
  )
}

export function TD({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-4 py-3 align-middle', className)} {...props} />
}

/* -------------------------------------------------------------------------- */
/* Loading / empty rows                                                        */
/* -------------------------------------------------------------------------- */

export function TableSkeletonRows({ rows = 6, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TR key={rowIndex}>
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <TD key={columnIndex}>
              <Skeleton
                className={cn('h-4', columnIndex === 0 ? 'w-40' : 'w-20')}
              />
            </TD>
          ))}
        </TR>
      ))}
    </>
  )
}

export function TableEmptyRow({
  colSpan,
  message,
}: {
  colSpan: number
  message: string
}) {
  return (
    <TR className="hover:bg-transparent">
      <TD colSpan={colSpan} className="py-12 text-center text-sm text-muted-foreground">
        {message}
      </TD>
    </TR>
  )
}

/* -------------------------------------------------------------------------- */
/* Pagination                                                                  */
/* -------------------------------------------------------------------------- */

interface PaginationProps {
  page: number
  pages: number
  total: number
  perPage: number
  onPageChange: (page: number) => void
  className?: string
}

export function Pagination({
  page,
  pages,
  total,
  perPage,
  onPageChange,
  className,
}: PaginationProps) {
  if (total === 0) return null

  const first = (page - 1) * perPage + 1
  const last = Math.min(page * perPage, total)

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-between gap-3 pt-4 sm:flex-row',
        className,
      )}
    >
      <p className="text-sm text-muted-foreground">
        Showing <span className="font-medium text-foreground">{first}</span>–
        <span className="font-medium text-foreground">{last}</span> of{' '}
        <span className="font-medium text-foreground">{total.toLocaleString()}</span>
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
        >
          <ChevronLeft aria-hidden />
          Previous
        </Button>
        <span className="px-2 text-sm text-muted-foreground" aria-live="polite">
          Page {page} of {pages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
        >
          Next
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </div>
  )
}
