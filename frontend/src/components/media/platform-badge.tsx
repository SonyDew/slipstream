import {
  Facebook,
  Film,
  Globe,
  Instagram,
  Music,
  Twitter,
  Video,
  Youtube,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/** Icon and accent per platform.
 *
 *  Icons come from Lucide; platforms without a Lucide brand glyph fall back to a
 *  neutral media icon rather than a hand-drawn approximation of their logo.
 */
const PLATFORM_META: Record<
  string,
  { icon: React.ComponentType<{ className?: string }>; tint: string; label: string }
> = {
  youtube: { icon: Youtube, tint: 'text-[#ff0033]', label: 'YouTube' },
  tiktok: { icon: Music, tint: 'text-foreground', label: 'TikTok' },
  douyin: { icon: Music, tint: 'text-[#fe2c55]', label: 'Douyin' },
  instagram: { icon: Instagram, tint: 'text-[#e1306c]', label: 'Instagram' },
  twitter: { icon: Twitter, tint: 'text-foreground', label: 'X' },
  facebook: { icon: Facebook, tint: 'text-[#1877f2]', label: 'Facebook' },
  reddit: { icon: Globe, tint: 'text-[#ff4500]', label: 'Reddit' },
  vimeo: { icon: Video, tint: 'text-[#1ab7ea]', label: 'Vimeo' },
  soundcloud: { icon: Music, tint: 'text-[#ff5500]', label: 'SoundCloud' },
  generic: { icon: Film, tint: 'text-muted-foreground', label: 'Direct link' },
}

export function platformMeta(platform: string) {
  return PLATFORM_META[platform] ?? PLATFORM_META.generic
}

export function PlatformIcon({
  platform,
  className,
}: {
  platform: string
  className?: string
}) {
  const meta = platformMeta(platform)
  const Icon = meta.icon
  return <Icon className={cn('size-4', meta.tint, className)} aria-hidden />
}

export function PlatformBadge({
  platform,
  label,
  className,
}: {
  platform: string
  label?: string
  className?: string
}) {
  const meta = platformMeta(platform)
  return (
    <Badge variant="outline" className={cn('gap-1.5 bg-background/80', className)}>
      <PlatformIcon platform={platform} />
      {label || meta.label}
    </Badge>
  )
}
