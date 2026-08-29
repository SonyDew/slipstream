import { useEffect, useState } from 'react'

/** Resolves a design-token colour to a concrete value for canvas/SVG libraries.
 *
 *  Recharts needs real colour strings — it cannot consume a Tailwind class — and
 *  the tokens live as HSL channel triplets in CSS variables, so they must be
 *  read from the document and re-read when the theme flips.
 */
export function useTokenColors<K extends string>(tokens: Record<K, string>): Record<K, string> {
  const [colors, setColors] = useState<Record<K, string>>(() => resolve(tokens))

  useEffect(() => {
    const update = () => setColors(resolve(tokens))
    update()

    // The theme toggles by adding/removing `.dark` on <html>.
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(tokens)])

  return colors
}

function resolve<K extends string>(tokens: Record<K, string>): Record<K, string> {
  const styles = getComputedStyle(document.documentElement)
  const out = {} as Record<K, string>
  for (const [name, token] of Object.entries(tokens) as [K, string][]) {
    const raw = styles.getPropertyValue(token).trim()
    out[name] = raw ? `hsl(${raw})` : 'currentColor'
  }
  return out
}
