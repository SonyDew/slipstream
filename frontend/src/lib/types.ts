/** Shared types mirroring the backend contract.
 *
 * Kept hand-written rather than generated so the shapes the UI actually depends
 * on are explicit and reviewable.
 */

export type MediaType = 'video' | 'audio' | 'image' | 'image_set' | 'unknown'

export type JobStatus =
  | 'queued'
  | 'analyzing'
  | 'downloading'
  | 'processing'
  | 'ready'
  | 'failed'
  | 'expired'
  | 'cancelled'

export type DownloadMode = 'video' | 'audio' | 'image'

export interface VideoOption {
  quality: string
  label: string
  height: number | null
  fps: number | null
  ext: string
  filesize: number | null
  filesize_is_estimate: boolean
  needs_merge: boolean
  note: string | null
}

export interface AudioOption {
  quality: string
  label: string
  bitrate: number | null
  ext: string
  capped: boolean
}

export interface MediaImage {
  index: number
  url: string
  width: number | null
  height: number | null
  ext: string
}

export interface Analysis {
  platform: string
  platform_label: string
  original_url: string
  media_id: string | null
  title: string
  description: string | null
  author: string | null
  author_url: string | null
  thumbnail: string | null
  duration: number | null
  duration_label: string | null
  upload_date: string | null
  view_count: number | null
  like_count: number | null
  media_type: MediaType
  is_slideshow: boolean
  extractor: string
  is_live: boolean
  video_options: VideoOption[]
  audio_options: AudioOption[]
  images: MediaImage[]
  audio_available: boolean
  ffmpeg_available: boolean
  warnings: string[]
  metadata: Record<string, unknown>
}

export interface Job {
  id: string
  status: JobStatus
  platform: string
  media_type: MediaType
  title: string | null
  author: string | null
  thumbnail: string | null
  duration: number | null
  quality: string
  output_format: string
  progress: number
  progress_label: string | null
  eta_seconds: number | null
  speed_bps: number | null
  file_name: string | null
  file_size: number | null
  mime_type: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  expires_at: string | null
  is_downloadable: boolean
  download_url: string | null
}

export interface User {
  id: number
  username: string
  email?: string | null
  role: 'user' | 'admin'
  is_active: boolean
  is_admin: boolean
  must_change_password: boolean
  created_at: string
  last_login_at: string | null
}

export interface Platform {
  platform: string
  label: string
  domains: string[]
  is_fallback: boolean
  operational: boolean
}

export interface PublicConfig {
  app_name: string
  version: string
  environment: string
  registration_enabled: boolean
  guest_downloads_enabled: boolean
  maintenance_mode: boolean
  max_file_size: number
  max_video_duration: number
  allowed_platforms: string[]
  platforms: Platform[]
  ffmpeg_available: boolean
  limits: { max_file_size: number; max_video_duration: number }
}

export interface HistoryItem {
  id: number
  job_id: string | null
  platform: string
  source_domain: string
  title: string | null
  author: string | null
  thumbnail: string | null
  media_type: MediaType
  quality: string | null
  output_format: string | null
  file_size: number | null
  status: string
  error_code: string | null
  created_at: string
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

/* -------------------------------------------------------------------------- */
/* Admin                                                                       */
/* -------------------------------------------------------------------------- */

export interface AdminStats {
  users: {
    total: number
    active: number
    disabled: number
    admins: number
    new_this_week: number
  }
  downloads: {
    total: number
    today: number
    week: number
    month: number
    successful: number
    failed: number
    success_rate: number
  }
  platforms: { platform: string; count: number }[]
  media_types: { media_type: string; count: number }[]
  statuses: { status: string; count: number }[]
  daily: { date: string; total: number; successful: number; failed: number }[]
  recent_users: {
    id: number
    username: string
    email: string
    role: string
    is_active: boolean
    created_at: string
  }[]
  recent_downloads: {
    id: number
    platform: string
    title: string | null
    media_type: string
    status: string
    created_at: string
    user_id: number | null
  }[]
  system: {
    version: string
    database: { status: string; detail: string }
    database_size_bytes: number | null
    extractor: { available: boolean; name?: string; version?: string }
    ffmpeg: { available: boolean; version: string; ffprobe_available?: boolean }
    queue: {
      backend: string
      running: boolean
      workers: number
      active: number
      queued: number
      processed: number
      failed: number
    }
    storage: { temp_bytes: number; temp_files: number; disk_free_bytes: number | null }
    active_jobs: number
  }
}

export interface AdminUser extends User {
  download_count?: number
  failed_login_count?: number
  recent_activity?: {
    id: number
    platform: string
    title: string | null
    media_type: string
    status: string
    created_at: string
  }[]
}

export interface AdminDownload {
  id: number
  job_id: string | null
  user_id: number | null
  username: string | null
  is_guest: boolean
  platform: string
  source_domain: string
  title: string | null
  author: string | null
  media_type: string
  quality: string | null
  output_format: string | null
  file_size: number | null
  status: string
  error_code: string | null
  duration_ms: number | null
  created_at: string
}

export interface AdminActiveJob {
  id: string
  status: JobStatus
  platform: string
  source_domain: string
  title: string | null
  media_type: string
  quality: string
  progress: number
  progress_label: string | null
  user_id: number | null
  is_guest: boolean
  created_at: string
  started_at: string | null
}

export interface AuditEntry {
  id: number
  admin_username: string
  admin_user_id: number | null
  action: string
  target_type: string | null
  target_id: string | null
  target_label: string | null
  meta: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface SettingSpec {
  key: string
  type: 'bool' | 'int' | 'string' | 'list'
  value: unknown
  default: unknown
  description: string
  minimum: number | null
  maximum: number | null
  group: string
}

export interface HealthReport {
  status: 'healthy' | 'degraded' | 'unhealthy'
  version: string
  environment: string
  components: Record<string, Record<string, unknown>>
}
