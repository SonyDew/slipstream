import {
  AlertTriangle,
  Check,
  Download,
  Film,
  Image as ImageIcon,
  Images,
  Music,
  Radio,
  User,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import { PlatformBadge } from '@/components/media/platform-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert } from '@/components/ui/feedback'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Analysis, DownloadMode } from '@/lib/types'
import { MEDIA_TYPE_LABELS, cn, formatBytes, formatCompact } from '@/lib/utils'

interface ResultCardProps {
  analysis: Analysis
  onDownload: (request: {
    mode: DownloadMode
    quality: string
    container: string
    imageIndexes?: number[]
  }) => void
  submitting?: boolean
  className?: string
}

/** Analysis result: metadata plus the download options that actually exist. */
export function ResultCard({ analysis, onDownload, submitting, className }: ResultCardProps) {
  const hasVideo = analysis.video_options.length > 0
  const hasAudio = analysis.audio_options.length > 0
  const hasImages = analysis.images.length > 0

  // Open on whichever tab suits the media, rather than always defaulting to video.
  const defaultTab = hasImages && !hasVideo ? 'images' : hasVideo ? 'video' : hasAudio ? 'audio' : 'images'
  const [tab, setTab] = useState(defaultTab)

  return (
    <div
      className={cn(
        'grid animate-fade-up overflow-hidden rounded-2xl border bg-card shadow-card lg:grid-cols-[minmax(0,0.82fr)_minmax(24rem,1.18fr)]',
        className,
      )}
    >
      <MediaHeader analysis={analysis} />

      <div className="border-t p-4 sm:p-6 lg:border-l lg:border-t-0">
        {analysis.warnings.length > 0 && (
          <div className="mb-5 space-y-2">
            {analysis.warnings.map((warning) => (
              <Alert key={warning} tone="warning" icon={AlertTriangle} className="py-3">
                {warning}
              </Alert>
            ))}
          </div>
        )}

        {!hasVideo && !hasAudio && !hasImages ? (
          <Alert tone="destructive" icon={AlertTriangle} title="Nothing downloadable">
            No usable media was found at this link.
          </Alert>
        ) : (
          <Tabs value={tab} defaultValue={defaultTab} onValueChange={setTab}>
            <TabsList className="w-full sm:w-auto">
              {hasVideo && (
                <TabsTrigger value="video">
                  <Film aria-hidden />
                  Video
                </TabsTrigger>
              )}
              {hasAudio && (
                <TabsTrigger value="audio">
                  <Music aria-hidden />
                  MP3
                </TabsTrigger>
              )}
              {hasImages && (
                <TabsTrigger value="images">
                  <Images aria-hidden />
                  Images
                  <Badge variant="muted" className="ml-1 px-1.5 py-0">
                    {analysis.images.length}
                  </Badge>
                </TabsTrigger>
              )}
            </TabsList>

            {hasVideo && (
              <TabsContent value="video">
                <VideoOptions analysis={analysis} onDownload={onDownload} submitting={submitting} />
              </TabsContent>
            )}
            {hasAudio && (
              <TabsContent value="audio">
                <AudioOptions analysis={analysis} onDownload={onDownload} submitting={submitting} />
              </TabsContent>
            )}
            {hasImages && (
              <TabsContent value="images">
                <ImageOptions analysis={analysis} onDownload={onDownload} submitting={submitting} />
              </TabsContent>
            )}
          </Tabs>
        )}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Header                                                                      */
/* -------------------------------------------------------------------------- */

function MediaHeader({ analysis }: { analysis: Analysis }) {
  const [thumbFailed, setThumbFailed] = useState(false)
  const showThumb = Boolean(analysis.thumbnail) && !thumbFailed

  return (
    <div className="flex min-w-0 flex-col gap-5 p-4 sm:p-6">
      <div className="relative w-full shrink-0 overflow-hidden rounded-xl border bg-muted">
        <div className="aspect-video w-full">
          {showThumb ? (
            <img
              src={analysis.thumbnail as string}
              alt=""
              loading="lazy"
              decoding="async"
              // Thumbnails come from third-party CDNs; do not leak our URL.
              referrerPolicy="no-referrer"
              onError={() => setThumbFailed(true)}
              className="size-full object-cover"
            />
          ) : (
            <div className="grid size-full place-items-center">
              <Film className="size-8 text-muted-foreground/40" aria-hidden />
            </div>
          )}
        </div>
        {analysis.duration_label && (
          <span className="absolute bottom-2 right-2 rounded-md bg-black/75 px-1.5 py-0.5 font-mono text-xs text-white">
            {analysis.duration_label}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <PlatformBadge platform={analysis.platform} label={analysis.platform_label} />
          <Badge variant="muted">{MEDIA_TYPE_LABELS[analysis.media_type] ?? analysis.media_type}</Badge>
          {analysis.is_live && (
            <Badge variant="destructive">
              <Radio aria-hidden />
              Live
            </Badge>
          )}
        </div>

        <h2 className="mt-4 text-balance text-xl font-semibold leading-snug tracking-[-0.025em] sm:text-2xl">
          {analysis.title}
        </h2>

        {analysis.author && (
          <p className="mt-1.5 flex items-center gap-1.5 text-sm text-muted-foreground">
            <User className="size-3.5" aria-hidden />
            <span className="truncate">{analysis.author}</span>
          </p>
        )}

        {(analysis.view_count || analysis.like_count) && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {analysis.view_count ? <span>{formatCompact(analysis.view_count)} views</span> : null}
            {analysis.like_count ? <span>{formatCompact(analysis.like_count)} likes</span> : null}
          </div>
        )}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Option rows                                                                 */
/* -------------------------------------------------------------------------- */

interface OptionsProps {
  analysis: Analysis
  onDownload: ResultCardProps['onDownload']
  submitting?: boolean
}

function OptionRow({
  primary,
  secondary,
  meta,
  selected,
  onSelect,
}: {
  primary: string
  secondary?: string
  meta?: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'flex min-h-14 w-full items-center justify-between gap-3 rounded-xl border border-transparent bg-muted/35 px-4 py-3 text-left transition-[background-color,border-color,transform] duration-200 ease-smooth',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected
          ? 'border-foreground/20 bg-accent/70'
          : 'hover:border-input hover:bg-muted/65',
      )}
    >
      <span className="flex min-w-0 items-center gap-3">
        <span
          className={cn(
            'grid size-5 shrink-0 place-items-center rounded-full border transition-colors',
            selected ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card',
          )}
          aria-hidden
        >
          {selected && <Check className="size-3" strokeWidth={3} />}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{primary}</span>
          {secondary && (
            <span className="block truncate text-xs text-muted-foreground">{secondary}</span>
          )}
        </span>
      </span>
      {meta && (
        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{meta}</span>
      )}
    </button>
  )
}

function VideoOptions({ analysis, onDownload, submitting }: OptionsProps) {
  const [quality, setQuality] = useState(analysis.video_options[0]?.quality ?? 'best')
  const [container, setContainer] = useState<'mp4' | 'webm'>('mp4')

  const selected = analysis.video_options.find((option) => option.quality === quality)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {analysis.video_options.length} quality{analysis.video_options.length === 1 ? '' : ' options'} available
        </p>
        <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Container">
          {(['mp4', 'webm'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setContainer(value)}
              aria-pressed={container === value}
              className={cn(
                'rounded-md px-2.5 py-1 text-xs font-medium uppercase transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                container === value
                  ? 'bg-secondary text-secondary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div className="grid max-h-[21rem] gap-2 overflow-y-auto pr-1">
        {analysis.video_options.map((option) => (
          <OptionRow
            key={option.quality}
            primary={option.label}
            secondary={option.note ?? undefined}
            meta={
              option.filesize
                ? `${option.filesize_is_estimate ? '≈' : ''}${formatBytes(option.filesize)}`
                : undefined
            }
            selected={quality === option.quality}
            onSelect={() => setQuality(option.quality)}
          />
        ))}
      </div>

      <Button
        variant="brand"
        size="lg"
        className="w-full"
        loading={submitting}
        onClick={() => onDownload({ mode: 'video', quality, container })}
      >
        {!submitting && <Download aria-hidden />}
        Download {selected?.label ?? 'video'} · {container.toUpperCase()}
      </Button>
    </div>
  )
}

function AudioOptions({ analysis, onDownload, submitting }: OptionsProps) {
  const [quality, setQuality] = useState(analysis.audio_options[0]?.quality ?? 'best')
  const selected = analysis.audio_options.find((option) => option.quality === quality)

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Converted to MP3. Bitrates above the source are not offered, because
        re-encoding upward cannot add detail.
      </p>

      <div className="grid gap-2">
        {analysis.audio_options.map((option) => (
          <OptionRow
            key={option.quality}
            primary={option.label}
            secondary={option.capped ? 'Will be capped to the source bitrate' : undefined}
            selected={quality === option.quality}
            onSelect={() => setQuality(option.quality)}
          />
        ))}
      </div>

      <Button
        variant="brand"
        size="lg"
        className="w-full"
        loading={submitting}
        onClick={() => onDownload({ mode: 'audio', quality, container: 'mp3' })}
      >
        {!submitting && <Music aria-hidden />}
        Download MP3 · {selected?.label ?? 'best'}
      </Button>
    </div>
  )
}

function ImageOptions({ analysis, onDownload, submitting }: OptionsProps) {
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [failed, setFailed] = useState<Set<number>>(new Set())

  const allSelected = selected.size === 0 || selected.size === analysis.images.length
  const chosen = useMemo(() => Array.from(selected).sort((a, b) => a - b), [selected])

  const toggle = (index: number) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const downloadLabel =
    selected.size === 0 || selected.size === analysis.images.length
      ? `Download all ${analysis.images.length} images (ZIP)`
      : selected.size === 1
        ? 'Download 1 image'
        : `Download ${selected.size} images (ZIP)`

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {analysis.images.length} images in this post
          {selected.size > 0 && ` · ${selected.size} selected`}
        </p>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set(analysis.images.map((image) => image.index)))}
          >
            Select all
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set())}
            disabled={selected.size === 0}
          >
            Clear
          </Button>
        </div>
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {analysis.images.map((image) => {
          const isSelected = selected.has(image.index)
          return (
            <li key={image.index}>
              <button
                type="button"
                onClick={() => toggle(image.index)}
                aria-pressed={isSelected}
                aria-label={`Image ${image.index + 1}`}
                className={cn(
                  'group relative block w-full overflow-hidden rounded-lg border bg-muted transition-all duration-200 ease-smooth',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  isSelected ? 'border-primary ring-2 ring-primary/30' : 'hover:border-input',
                )}
              >
                <div className="aspect-square w-full">
                  {failed.has(image.index) ? (
                    <div className="grid size-full place-items-center">
                      <ImageIcon className="size-6 text-muted-foreground/40" aria-hidden />
                    </div>
                  ) : (
                    <img
                      src={image.url}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      referrerPolicy="no-referrer"
                      onError={() =>
                        setFailed((current) => new Set(current).add(image.index))
                      }
                      className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                    />
                  )}
                </div>

                <span
                  className={cn(
                    'absolute left-2 top-2 grid size-5 place-items-center rounded-full border transition-colors',
                    isSelected
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-white/60 bg-black/40 text-transparent',
                  )}
                  aria-hidden
                >
                  <Check className="size-3" strokeWidth={3} />
                </span>

                <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">
                  {image.index + 1}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          variant="brand"
          size="lg"
          className="flex-1"
          loading={submitting}
          onClick={() =>
            onDownload({
              mode: 'image',
              quality: 'best',
              container: 'zip',
              imageIndexes: allSelected ? undefined : chosen,
            })
          }
        >
          {!submitting && <Download aria-hidden />}
          {downloadLabel}
        </Button>

        {analysis.audio_available && analysis.audio_options.length > 0 && (
          <Button
            variant="outline"
            size="lg"
            onClick={() => onDownload({ mode: 'audio', quality: 'best', container: 'mp3' })}
            disabled={submitting}
          >
            <Music aria-hidden />
            Audio as MP3
          </Button>
        )}
      </div>
    </div>
  )
}
