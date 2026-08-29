# Changelog

All notable changes to Slipstream are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] — 2026-08-25

First release. Everything below is new, so the usual Added/Changed/Fixed split would be
noise; the sections group by area instead.

### Media handling

- URL analysis through a provider registry with dedicated handling for YouTube, TikTok,
  Douyin, Instagram, X/Twitter, Facebook, Reddit, Vimeo, and SoundCloud, plus a generic
  yt-dlp fallback.
- Video downloads offering Best plus only the resolutions the source genuinely has;
  unavailable rungs are never listed.
- MP3 extraction at 320/256/192/128 kbps, capped at the true source bitrate rather than
  upsampled.
- TikTok and Douyin photo slideshows: single image, all images, ZIP archive, or the
  soundtrack as MP3.
- In-process job queue with progress reporting, concurrency limits, per-job timeouts, and
  cancellation.
- Finished files stream to the browser through a real anchor element and expire from disk
  after a configurable TTL.
- SSRF guard rejecting private, loopback, and link-local targets before the extractor
  runs.

### Accounts and security

- Server-side sessions behind an HttpOnly cookie, with only a SHA-256 hash of the token
  stored.
- Argon2id password hashing; policy of at least 10 characters, at least 3 character
  classes, and no username substring, enforced identically on server and client.
- CSRF protection via double-submit cookie echoed as `X-CSRF-Token`.
- Per-role hourly rate limits on analysis, downloads, and authentication attempts.
- Seeded admin account flagged as temporary: read-only in the admin panel until the
  password is rotated.
- Last-admin protection and self-protection on disable, role change, and delete.

### Admin panel

- Dashboard with usage charts (recharts, lazy-loaded so it stays out of the initial
  payload).
- User management: search and filter, activate/deactivate, promote/demote, delete,
  per-user detail with activity, and password reset with a generated handover password.
- Download ledger recording `source_domain` rather than full URLs, with history purge
  windows.
- Live job monitor with cancellation, showing an indeterminate bar for queued work instead
  of a fabricated percentage.
- Audit log with action filtering, readable diffs for settings changes, and flagged
  sensitive actions. Credentials are never written to it.
- Runtime settings editor covering access, platforms, limits, privacy, and rate limits,
  applied without a restart.

### Application

- Single-origin, path-based routing: `/api/*` is the JSON API, every other path is the
  SPA. OpenAPI moved to `/api/docs` so the SPA owns `/docs`.
- SPA deep-link fallback that excludes `/assets/`, so a stale content-hashed asset
  reference returns a real 404 instead of HTML the browser would try to parse as
  JavaScript.
- Light and dark themes with the preference persisted locally.
- Operational CLI: `verify`, `init-db`, `create-admin`, `reset-password`, `stats`,
  `cleanup`, `settings`.
- SQLite in WAL mode with Alembic migrations.
- Backend suite of 319 tests; `ruff`, `mypy`, and the frontend `typecheck`/`lint`/`build`
  all clean.

### Deployment

- Three-stage Docker image, amd64 and arm64, running unprivileged with tini reaping
  ffmpeg and yt-dlp children. Compose base plus dev, Ubuntu, and Oracle overlays.
- nginx configuration as a single server block with security headers, rate-limit zones,
  and buffering disabled on the file endpoint so large downloads stream.
- Bare-metal systemd install with a hardened unit, plus disabled-by-default timers for
  backups and unattended yt-dlp updates.
- One-command deploy scripts for Ubuntu and Oracle Linux, including TLS provisioning and
  firewall configuration; Oracle's script also handles SELinux, the second firewall layer,
  and the certbot renewal timer its packages omit.
- Windows scripts for setup, start, scheduled-task installation, backup, and update.
- Backup and restore through SQLite's online backup API rather than a file copy, so a
  backup taken during a write is consistent.

### Repository and CI

- GitHub Actions: backend lint/type/test on Python 3.11 and 3.12 with a boot-and-serve
  job, frontend build on Node 20 and 22 with a check that recharts stays out of the entry
  chunk, a two-architecture Docker build with a container smoke test, weekly dependency
  and static analysis, and a tag-driven release.
- Dependabot with grouped updates; yt-dlp deliberately ungrouped so a bump is reviewed
  against the format-honesty tests on its own.
- Issue and pull request templates that require confirming the media was publicly
  accessible and that yt-dlp was updated first.
- Twelve documentation guides under `docs/`, covering architecture, the API, development,
  deployment, each target platform, security, backups, updates, troubleshooting, and CI.

[Unreleased]: https://github.com/OWNER/slipstream/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/slipstream/releases/tag/v0.1.0
