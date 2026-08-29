import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import { forwardRef } from 'react'
import { Link, type LinkProps } from 'react-router-dom'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  // Base: consistent focus ring, disabled treatment and icon sizing everywhere.
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold ' +
    'transition-[color,background-color,border-color,transform,box-shadow] duration-200 ease-smooth select-none ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ' +
    'disabled:pointer-events-none disabled:opacity-50 ' +
    '[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-foreground text-background shadow-soft hover:opacity-90 active:scale-[0.98]',
        brand:
          'bg-primary text-primary-foreground shadow-soft hover:-translate-y-0.5 hover:shadow-card active:translate-y-0 active:scale-[0.98]',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-secondary/70 active:scale-[0.98]',
        outline:
          'border border-input bg-transparent hover:border-foreground/35 hover:bg-accent/60 hover:text-accent-foreground active:scale-[0.98]',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        destructive:
          'bg-destructive text-destructive-foreground shadow-soft hover:bg-destructive/90 active:scale-[0.98]',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-9 rounded-md px-3 text-xs',
        default: 'h-11 px-4',
        lg: 'h-[3.25rem] rounded-xl px-6 text-sm',
        xl: 'h-14 rounded-xl px-8 text-base',
        icon: 'size-10',
        'icon-sm': 'size-8 rounded-md',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Shows a spinner and blocks interaction. */
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, disabled, children, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="animate-spin" aria-hidden />}
      {children}
    </button>
  ),
)
Button.displayName = 'Button'

export interface ButtonLinkProps
  extends Omit<LinkProps, 'className'>,
    VariantProps<typeof buttonVariants> {
  className?: string
}

/** A router link that looks like a button.
 *
 *  Kept as its own component rather than an `asChild` prop on Button: a real
 *  anchor keeps middle-click, "open in new tab" and copy-link-address working,
 *  which a button with an onClick handler silently breaks.
 */
export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(
  ({ className, variant, size, ...props }, ref) => (
    <Link ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
)
ButtonLink.displayName = 'ButtonLink'

/** Same treatment for links leaving the app. */
export function ExternalButtonLink({
  className,
  variant,
  size,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & VariantProps<typeof buttonVariants>) {
  return (
    <a
      className={cn(buttonVariants({ variant, size }), className)}
      rel="noopener noreferrer"
      {...props}
    />
  )
}

export { buttonVariants }
