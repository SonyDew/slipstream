# Architecture

How Slipstream is put together, and why it is put together that way. Read this before
changing anything structural — several of the shapes here are deliberate and look like
oversights until you know the reason.

---

## The one-sentence version

A FastAPI process serves both the JSON API and the compiled React SPA from a single
origin, runs an in-process job queue that shells out to yt-dlp and ffmpeg, and keeps its
state in a SQLite database in WAL mode.

---

## Request flow

```
                         ┌─────────────────────────────────────┐
  browser  ──────────────▶  nginx (TLS, rate limits, headers)  │   optional
                         └──────────────────┬──────────────────┘
                                            │  127.0.0.1:8000
                         ┌──────────────────▼──────────────────┐
                         │  uvicorn — exactly one worker       │
                         │                                     │
                         │  middleware stack (outermost first) │
                         │    RequestContext  → request id     │
                         │    SecurityHeaders                  │
                         │    MaintenanceMode                  │
                         │    CSRF                             │
                         │    CORS (only if CORS_ORIGINS set)  │
                         │                                     │
                         │  /api/health   health router        │
                         │  /api/auth/*   auth router          │
                         │  /api/*        media router         │
                         │  /api/admin/*  admin router         │
                         │  /assets/*     StaticFiles          │
                         │  /*            index.html (SPA)     │
                         │                                     │
                         │  ┌───────────────────────────────┐  │
                         │  │ in-process job queue          │  │
                         │  │   worker → yt-dlp → ffmpeg    │  │
                         │  │ cleanup loop (asyncio task)   │  │
                         │  └───────────────────────────────┘  │
                         └──────────────────┬──────────────────┘
                                            │
                         ┌──────────────────▼──────────────────┐
                         │  data/db/slipstream.db  (SQLite WAL)│
                         │  data/temp/             (in flight) │
                         │  data/logs/                         │
                         └─────────────────────────────────────┘
```

nginx is optional. The app is a complete HTTP server on its own; the Windows and
development paths run it directly. nginx exists to terminate TLS, apply a second layer of
rate limiting, and serve as the thing you point a certificate at.

---

## Single origin, path-based routing

Everything is one hostname. `/api/*` is the JSON API; every other path is the SPA.

This is a decision, not a default. The obvious alternative — an API subdomain — costs a
cross-origin cookie problem, which costs `SameSite=None`, which costs the CSRF protection
that `SameSite=Lax` gives for free. Keeping one origin means the session cookie is simply
first-party and the browser's own rules do most of the work.

Two consequences worth knowing:

- **OpenAPI is mounted at `/api/docs`**, not `/docs`, because the SPA owns `/docs` as a
  user-facing help page. If you go looking for the schema at `/docs` you will find the
  React app.
- **A missing asset returns a real 404**, not the SPA shell. `app/main.py` checks whether
  the requested path exists under `FRONTEND_DIST` before falling back to `index.html`. A
  catch-all that returns HTML for `/assets/index-abc123.js` produces a
  "Unexpected token '<'" console error that tells you nothing; a 404 tells you the asset
  is missing.

---

## The layers

### `app/api/routes/` — HTTP only

Routers parse input, call a service, and shape the response. They hold no business logic.
Four of them:

| Router | Prefix | Notes |
| --- | --- | --- |
| `health` | none | `/api/health`, `/api/health/ready`, `/api/health/storage`, `/api/version`, `/api/config` |
| `auth` | `/auth` | register, login, logout, me, change-password, logout-all |
| `media` | none | analyze, platforms, download, jobs, history |
| `admin` | `/admin` | stats, users, downloads, jobs, audit, settings, cleanup |

The media router deliberately has **no prefix**, which is why the endpoints are
`/api/download` and `/api/jobs/{id}` rather than `/api/media/download`. Only the two
metadata endpoints live under `/api/media/`. If you are writing an nginx location or a
CI assertion, check the decorators rather than guessing — this trips people up.

### `app/services/` — the actual work

- `analyze.py` — orchestrates a URL into a `NormalizedMedia` plus option lists.
- `extractor.py` — the only module that talks to yt-dlp. Runs it in a thread so the event
  loop is not blocked, and translates yt-dlp's exception text into typed `AppError`s.
- `formats.py` — derives the video and audio option lists, and translates a validated
  quality token back into a yt-dlp format selector.
- `downloader.py` — runs the download and any ffmpeg muxing or conversion.
- `slideshow.py` — TikTok and Douyin image posts.
- `jobs.py` — job lifecycle and persistence.
- `queue/` — `base.py` defines the interface, `local.py` is the in-process
  implementation. The interface exists so a future Redis-backed queue is a substitution
  rather than a rewrite; nothing else assumes the local one.
- `cleanup.py` — expires temp files and prunes history.
- `storage.py` — path construction, disk accounting, safe deletion.
- `auth.py` — sessions, password verification, the lockout counter.

### `app/providers/` — per-platform knowledge

A registry of provider classes. Each declares which URL patterns it claims and can
override normalisation for its platform's quirks — Douyin's image posts, Reddit's
crossposts, SoundCloud's audio-only shape. `generic.py` is the fallback and covers
everything else yt-dlp supports.

Adding a platform means adding a provider, not touching the services.

### `app/core/` — cross-cutting primitives

`config.py` (environment settings), `settings_store.py` (database-backed runtime
overrides), `security.py` (Argon2, tokens, CSRF), `ratelimit.py`, `ssrf.py`,
`filenames.py`, `errors.py`, `logging.py`, `version.py`.

### `app/models/` and `app/db/`

SQLAlchemy 2.0 declarative models with `Mapped[...]` annotations. Five tables: `users`,
`sessions`, `download_jobs`, `download_history`, `admin_audit_log`, `app_settings`.
Alembic owns the schema; `0001_initial_schema.py` is the baseline.

---

## Configuration: two layers

**Environment** (`app/core/config.py`) provides defaults for everything and is the only
place secrets live. Read once at import.

**Database** (`app/core/settings_store.py`) holds administrator overrides for the subset
of settings that are safe to change at runtime — registration on/off, guest downloads,
maintenance mode, allowed platforms, size and duration ceilings, rate limits. A database
value wins over the environment value.

Reads go through a 10-second cache so the rate-limit lookup on every request does not hit
SQLite. That TTL is the reason an admin settings change takes a few seconds to appear
everywhere rather than being instant, and it is the right trade: the alternative is a
database read on the hot path of every single request.

Settings that are **not** runtime-editable — `SECRET_KEY`, `DATABASE_URL`, `DATA_DIR`,
cookie names, `TRUSTED_PROXY_COUNT` — are environment-only on purpose. Letting an admin
panel rewrite the secret key or the database path turns a compromised admin account into
a compromised host.

---

## Authentication

Server-side sessions. On login the server generates a token, stores **only its SHA-256
hash** in the `sessions` table, and sets it as an HttpOnly cookie
(`slipstream_session`). A database dump therefore does not yield usable session tokens.

Passwords are Argon2id via `argon2-cffi`.

CSRF is a double-submit cookie: `slipstream_csrf` is readable by JavaScript, and the SPA
echoes it in `X-CSRF-Token` on every mutating request. The middleware compares the two.
Combined with `SameSite=Lax` this is two independent defences.

**No JWTs, and nothing sensitive in `localStorage`.** A JWT cannot be revoked without
building the server-side session table you were trying to avoid, and a token in
`localStorage` is readable by any successful XSS. The cookie is not.

### Admin permissions

Admin mutations require `RequireAdminVerified`, not merely `RequireAdmin`. An admin who is
still on their seeded temporary password (`must_change_password`) can *read* the admin
panel but cannot change anything. This closes the window where a deployment sits on a
default credential with full write access.

Two further guards:

- **Last-admin protection.** The final active admin cannot be disabled, demoted or
  deleted. An instance with no way to administer it is unrecoverable through the UI.
- **Self-protection.** An admin cannot disable, demote or delete their own account, which
  is the most common way to lock yourself out by accident.

---

## The job queue, and the single-worker constraint

The queue and the cleanup loop are **in-process**. The queue is a Python structure held in
the worker's memory; the cleanup loop is an asyncio task started in the lifespan handler.

This means **uvicorn must run exactly one worker.** With two, each process gets its own
queue and its own cleanup loop. A job submitted to worker A is invisible to worker B, so
roughly half of all status polls return 404 and the job appears to vanish. Two cleanup
loops also race over the same temp tree.

Scale with `MAX_CONCURRENT_DOWNLOADS`, which raises parallelism inside the one process.
Downloads are I/O-bound, so this works well; the CPU-bound part is ffmpeg, which is a
subprocess and uses other cores anyway.

The constraint is enforced in three places, and all three should stay:
`docker/entrypoint.sh` overrides `WEB_CONCURRENCY` and logs why, the systemd unit hardcodes
`--workers 1`, and each carries a comment explaining the consequence.

---

## Honesty invariants

These are product-defining, not stylistic.

**Never offer a video rung the source does not have.** The option list is derived from the
formats the extractor actually returned. `_bucket_height` maps real pixel heights onto
standard rungs with a 5% tolerance, because a 1078px re-encode should appear as 1080p — but
a source whose best stream is 720p never shows a 1080p option. Offering a 4K rung that
silently delivers 1080p is worse than offering no 4K rung, because the user cannot tell.

**Never advertise an MP3 bitrate above the source.** The ladder is capped at the true
source bitrate. Upsampling 128 kbps to "320 kbps" produces a bigger file with no more
information, labelled with a lie.

**Never claim a size you cannot substantiate.** Estimates are marked as estimates.

If you change `services/formats.py`, the tests covering these are the ones that matter.

---

## Bytes never pass through JavaScript

`GET /api/jobs/{job_id}/file` is the only endpoint that streams media, and the frontend
reaches it by setting `href` on a real anchor element and clicking it. The browser
streams to disk.

The alternative — `fetch` into a Blob and `URL.createObjectURL` — buffers the entire file
in the tab's memory. For a 2 GiB video that is a tab crash on any modest machine, and it
breaks range requests and resumption.

If you are configuring a proxy, this endpoint is the one that needs `proxy_buffering off`
and a long read timeout.

---

## Security boundaries

**SSRF guard** (`core/ssrf.py`) resolves every target and rejects private, loopback,
link-local and multicast addresses before yt-dlp is invoked. Without it, a submitted URL
becomes a request from inside your network — cloud metadata endpoints being the obvious
prize. `ALLOW_PRIVATE_NETWORK_TARGETS` disables this and exists **only** so the test suite
can point at a local fixture server. Never set it in production.

**No shell interpolation.** yt-dlp is used as a library and ffmpeg is invoked as an
argument list. A URL never becomes part of a shell string.

**No raw format selectors from the client.** The client sends a token from a closed set
(`best`, `1080`, `320`) which is validated against what the source offers. yt-dlp's
selector syntax is expressive enough that accepting it from a request would be an
injection surface.

**Rate limiting** is per-identity, keyed on user id when signed in and client IP
otherwise. The IP comes from `X-Forwarded-For` only as far in as `TRUSTED_PROXY_COUNT`
allows. Leaving that at `0` when a proxy *is* in front means everyone shares the proxy's
IP; setting it above the real proxy count lets a client spoof its own address and defeat
the limit entirely. Set it to the exact number of proxies you control.

**Privacy in the ledger.** `download_history.source_domain` is what the admin panel
displays. The full URL is stored but not surfaced in the ledger view: an operator needs to
know that someone downloaded from `youtube.com`, not which video they watched. Audit log
`meta` must never contain credentials.

---

## Frontend

React 18 + TypeScript 5.7 + Vite 6 + Tailwind 3. `@/` aliases to `src/`.

- `lib/api.ts` — the single fetch wrapper. Attaches the CSRF header, unwraps the error
  envelope into a typed error, handles 401 by clearing auth state.
- `lib/auth-context.tsx` — session state from `/api/auth/me`.
- `hooks/use-polling.ts` — job status polling with backoff.
- `components/ui/` — the primitives. Hand-written rather than pulled from a component
  library, so there is no runtime dependency to keep current.
- `pages/admin/` — six pages behind a lazy boundary.

**Chunking is load-bearing.** `vite.config.ts` splits `recharts` and `d3-*` into a
`charts` chunk, `react-router` into `router`, `lucide-react` into `icons`. recharts plus
d3 is by far the largest dependency and it is only needed on the admin dashboard. A static
import of it anywhere in the eager tree lands it in the entry chunk and every visitor
downloads it to view the home page. `.github/workflows/frontend.yml` fails the build if
that happens — it greps the entry chunk for `recharts`.

Note the ordering in `manualChunks`: `lucide-react` is checked *before* the generic
`react` match, which would otherwise swallow it.

---

## Storage layout

```
data/
├── db/
│   ├── slipstream.db        SQLite, WAL mode
│   ├── slipstream.db-wal    write-ahead log
│   └── slipstream.db-shm    shared memory index
├── logs/
└── temp/                    in-flight and recently finished downloads
```

**WAL mode means the three database files are only consistent together.** Copying just
the `.db` file gives you a database missing every committed-but-not-checkpointed
transaction. Every backup path in this repo therefore uses the `sqlite3` online backup
API (`src.backup(dst)`), which produces a single consistent file while the app keeps
running. See [BACKUPS.md](BACKUPS.md).

`data/temp/` is the only directory that grows without bound if the cleanup loop stops.
`TEMP_FILE_TTL` governs how long a finished file stays downloadable; `CLEANUP_INTERVAL`
governs how often the sweep runs.

---

## Error handling

Every failure is an `AppError` subclass carrying a stable machine-readable `code`, an HTTP
status, a `retryable` flag, and optional `meta`. The handler in `main.py` renders them as:

```json
{ "error": { "code": "media_unavailable", "message": "...", "retryable": false } }
```

The frontend switches on `code`, never on `message`, so wording can improve without
breaking the UI. Codes are part of the API contract — see [API.md](API.md) for the list.

Distinguishing `private_content`, `auth_required_content`, `drm_protected` and
`geo_restricted` from a generic failure is what lets the UI say "this is not publicly
accessible, and Slipstream will not try to get around that" instead of "something went
wrong".

---

## Where to look

| Change | Start here |
| --- | --- |
| Add a platform | `app/providers/`, then register it |
| Change what qualities are offered | `app/services/formats.py` |
| Change the download pipeline | `app/services/downloader.py` |
| Add an API endpoint | `app/api/routes/`, `app/schemas/api.py` |
| Add a runtime setting | `SPECS` in `app/core/settings_store.py` |
| Add an env-only setting | `app/core/config.py`, then `.env.example` |
| Change the schema | a new Alembic revision |
| Change auth | `app/services/auth.py`, `app/core/security.py`, `app/api/deps.py` |
