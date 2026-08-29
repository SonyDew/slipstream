# API reference

Base path `/api`. Interactive OpenAPI at **`/api/docs`** — not `/docs`, which the SPA owns
as a user-facing help page.

Everything below was read off the route decorators rather than reconstructed from memory,
but the OpenAPI schema on a running instance is always the final authority.

---

## Conventions

**Authentication** is a session cookie, `slipstream_session`, set by
`POST /api/auth/login`. It is HttpOnly, so JavaScript cannot read it, and only its
SHA-256 hash is stored server-side.

**CSRF**: every mutating request (`POST`, `PATCH`, `DELETE`) must echo the
`slipstream_csrf` cookie in an `X-CSRF-Token` header. The value is also returned in the
login and register response body as `csrf_token`. A mismatch is `csrf_failed`.

**Guests.** Endpoints marked *guest* work without a session when
`guest_downloads_enabled` is on. A guest is identified by an opaque key derived from the
request, and can only see their own jobs.

**Errors** are always this shape:

```json
{
  "error": {
    "code": "media_unavailable",
    "message": "This video is no longer available.",
    "retryable": false,
    "meta": null
  }
}
```

Switch on `code`, never on `message`. Codes are contract; wording is not.

**Timestamps** are ISO 8601 UTC. **Sizes** are bytes. **Durations** are seconds.

---

## Health and configuration

### `GET /api/health`
Public. Liveness plus a summary of the extractor and ffmpeg state.

### `GET /api/health/ready`
Public. Readiness — the database is reachable and the schema is present. This is what the
container `HEALTHCHECK` and every deployment script polls.

### `GET /api/health/storage`
Temp-area usage, for the admin dashboard and monitoring.

```json
{ "temp_bytes": 148236541, "temp_files": 3, "disk_free_bytes": 41203986432 }
```

### `GET /api/version`
Build information.

### `GET /api/config`
Public. Everything the frontend needs before anyone signs in — the app name, version,
environment, the public subset of runtime settings, the platform list, whether ffmpeg is
available, and the size and duration ceilings.

```json
{
  "app_name": "Slipstream",
  "version": "0.1.0",
  "environment": "production",
  "registration_enabled": true,
  "guest_downloads_enabled": true,
  "maintenance_mode": false,
  "max_file_size": 2147483648,
  "max_video_duration": 10800,
  "allowed_platforms": [],
  "platforms": [{ "platform": "youtube", "label": "YouTube", "...": "..." }],
  "ffmpeg_available": true,
  "limits": { "max_file_size": 2147483648, "max_video_duration": 10800 }
}
```

Only the whitelisted subset of settings appears here. Adding a field to `public_settings`
in `settings_store.py` publishes it to anonymous callers, so think before you do.

---

## Authentication

### `POST /api/auth/register`
Guest. `201`. Fails with `registration_disabled` when registration is off.

```json
{ "username": "alice", "email": "alice@example.com", "password": "correct-horse-9" }
```

Password policy, enforced identically on both sides: at least 10 characters, at least 3 of
the 4 character classes (lower, upper, digit, symbol), and it must not contain the
username. Violations are `weak_password`.

Returns a `SessionResponse` and sets both cookies.

### `POST /api/auth/login`
Guest. `{ "username": "...", "password": "..." }` — the username field accepts an email
address too.

```json
{
  "user": {
    "id": 1, "username": "alice", "email": "alice@example.com",
    "role": "user", "is_active": true, "is_admin": false,
    "must_change_password": false,
    "created_at": "2026-08-01T09:12:44Z", "last_login_at": "2026-08-25T14:03:19Z"
  },
  "csrf_token": "…"
}
```

Rate-limited per IP by `RATE_LIMIT_AUTH`. Failures are `authentication_failed` regardless of
whether the username exists — distinguishing them would confirm which accounts are real.
A disabled account gets `account_disabled`.

### `POST /api/auth/logout`
`204`. Revokes the current session only.

### `GET /api/auth/me`
Returns the current user. `401` when there is no session — the frontend treats this as
"signed out" rather than an error.

### `POST /api/auth/change-password`
`204`. `{ "current_password": "...", "new_password": "..." }`. Same policy as register.

This is what clears `must_change_password` on the seeded admin, which is what unlocks
admin mutations. Also revokes every *other* session for the account: a password change
should end any session an attacker holds.

### `POST /api/auth/logout-all`
`204`. Revokes every session including the current one.

---

## Media

### `POST /api/media/analyze`
Guest. The core endpoint: inspects a URL and returns what can genuinely be delivered.

```json
{ "url": "https://www.youtube.com/watch?v=…", "container": "mp4" }
```

`container` is `mp4` or `webm` and affects which video options are offered.

```json
{
  "platform": "youtube",
  "platform_label": "YouTube",
  "original_url": "https://www.youtube.com/watch?v=…",
  "media_id": "…",
  "title": "…",
  "description": "…",
  "author": "…",
  "author_url": "…",
  "thumbnail": "https://…",
  "duration": 213,
  "duration_label": "3:33",
  "upload_date": "20260714",
  "view_count": 918243,
  "like_count": 41022,
  "media_type": "video",
  "is_slideshow": false,
  "extractor": "youtube",
  "is_live": false,
  "video_options": [
    { "quality": "best", "label": "Best available", "height": 1080, "fps": 30,
      "ext": "mp4", "filesize": 48210394, "filesize_is_estimate": true,
      "needs_merge": true, "note": null },
    { "quality": "1080", "label": "1080p", "height": 1080, "...": "..." },
    { "quality": "720",  "label": "720p",  "height": 720,  "...": "..." }
  ],
  "audio_options": [
    { "quality": "128", "label": "128 kbps", "bitrate": 128, "ext": "mp3", "capped": true }
  ],
  "images": [],
  "audio_available": true,
  "ffmpeg_available": true,
  "warnings": [],
  "metadata": {}
}
```

Read the option lists literally. **`video_options` contains only rungs the source
actually has** — if 1080p is absent, the source does not have it, and requesting it will
be rejected rather than silently downgraded. **`audio_options` is capped at the true
source bitrate**, and `capped: true` means the ladder stopped below where you might
expect because the source itself is that bitrate. A 128 kbps source offers 128 and
nothing above it.

`filesize_is_estimate` distinguishes a size the extractor reported from one derived from
bitrate and duration.

Without ffmpeg on the server, `audio_options` is empty (MP3 output is impossible) and
adaptive-only video rungs are dropped, with an explanatory entry in `warnings`. The API
would rather tell you it cannot do something than accept a job that will fail.

Rate-limited by `rate_limit_guest` or `rate_limit_user`.

### `GET /api/media/platforms`
Public. Registered providers, filtered by the admin allow-list.

```json
{ "platforms": [{ "platform": "youtube", "label": "YouTube", "...": "..." }] }
```

### `POST /api/download`
Guest. `202`. Queues a job. Note the path: the media router has no prefix, so this is
`/api/download`, **not** `/api/media/download`.

```json
{
  "url": "https://…",
  "mode": "video",
  "quality": "1080",
  "container": "mp4",
  "image_indexes": null
}
```

- `mode` — `video`, `audio`, or `image`.
- `quality` — `best`, or a 2–4 digit token (`1080` for video, `320` for audio). Validated
  against `^(best|\d{2,4})$` *and* against what the source offers.
- `container` — `mp4`, `webm`, or `mp3`. Forced to `mp3` when `mode` is `audio`, and away
  from `mp3` when it is not, so an inconsistent pair cannot be submitted.
- `image_indexes` — for slideshow posts, which images to fetch. Up to 200.

**The client never sends a yt-dlp format selector.** It sends a token from a closed set
which the server translates. yt-dlp's selector syntax is expressive enough that accepting
it from a request would be an injection surface.

```json
{ "job_id": "b0f1…", "status": "queued", "poll_url": "/api/jobs/b0f1…" }
```

The URL is re-analysed server-side — usually a cache hit from the preceding analyze call —
so the requested quality is validated against reality. A rung the source lacks is
`no_suitable_format`, not a silent downgrade.

### `GET /api/jobs/{job_id}`
Guest, own jobs only. Poll for status.

```json
{
  "id": "b0f1…",
  "status": "downloading",
  "platform": "youtube",
  "media_type": "video",
  "title": "…", "author": "…", "thumbnail": "https://…", "duration": 213,
  "quality": "1080", "output_format": "mp4",
  "progress": 62,
  "progress_label": "Downloading video",
  "eta_seconds": 14,
  "speed_bps": 4218880,
  "file_name": null, "file_size": null, "mime_type": null,
  "error_code": null, "error_message": null,
  "created_at": "2026-08-25T14:31:02Z",
  "started_at": "2026-08-25T14:31:03Z",
  "finished_at": null,
  "expires_at": null,
  "is_downloadable": false,
  "download_url": null
}
```

Statuses: `queued`, `analyzing`, `downloading`, `processing`, `ready`, `failed`,
`expired`, `cancelled`. The last four are terminal — stop polling.

When `status` is `ready`, `download_url` is populated and `expires_at` says when the file
will be swept. Polling a `ready` job past its TTL flips it to `expired` on read, so a
client that comes back late sees the truth rather than a link that 404s.

`GET /api/jobs/{id}` on someone else's job is a 404, not a 403 — a 403 would confirm the
job exists.

### `DELETE /api/jobs/{job_id}`
Cancels a running job, or discards a finished one and deletes its bytes immediately rather
than waiting for cleanup.

```json
{ "cancelled": true, "status": "cancelled" }
```

### `GET /api/jobs/{job_id}/file`
**The only endpoint that returns media bytes.** A `FileResponse`, chunked via sendfile,
with range-request support so a browser can resume.

Send the user here with a real anchor element. Do not `fetch` it into a Blob: that buffers
the whole file in the tab, which for a 2 GiB video is a crash, and it discards range
support.

Response headers include `Content-Disposition` with the derived filename,
`Cache-Control: no-store, must-revalidate`, and `X-Content-Type-Options: nosniff`.

Failures: `download_expired` if the TTL passed or the bytes are gone, `job_not_ready` if
it has not finished, `media_unavailable` if it failed or was cancelled.

Proxy note: this needs `proxy_buffering off` and a long `proxy_read_timeout`. See
[DEPLOYMENT.md](DEPLOYMENT.md).

### `GET /api/history`
Signed in. Paginated download history.

```json
{
  "items": [{
    "id": 412, "job_id": "b0f1…", "platform": "youtube",
    "source_domain": "youtube.com",
    "title": "…", "author": "…", "thumbnail": "https://…",
    "media_type": "video", "quality": "1080", "output_format": "mp4",
    "file_size": 48210394, "status": "ready", "error_code": null,
    "created_at": "2026-08-25T14:31:02Z"
  }],
  "total": 412, "page": 1, "per_page": 25, "pages": 17
}
```

### `DELETE /api/history`
Clears the caller's history.

### `DELETE /api/history/{item_id}`
Removes one entry.

---

## Admin

Every endpoint under `/api/admin` requires an admin session. **Mutations additionally
require a verified admin** — one who is not still on the seeded temporary password. A
temp-password admin gets read access and `password_change_required` on any write.

### `GET /api/admin/stats`
Dashboard aggregates: user and job counts, jobs by status, downloads over time, top
platforms, storage usage.

Anonymous access to this endpoint returning anything other than 401 or 403 is the worst
regression this project could ship, which is why both `backend.yml` and `docker.yml`
assert it explicitly rather than trusting the unit tests.

### `GET /api/admin/users`
Paginated, with search and filters.

### `GET /api/admin/users/{user_id}`
One user plus their sessions and recent activity.

### `POST /api/admin/users`
`201`. Creates an account.

```json
{ "username": "bob", "email": "bob@example.com", "password": "…", "role": "user" }
```

The password goes in the **JSON body**. It must never be moved to a query parameter or
path segment, where it would land in access logs, browser history and proxy logs.

### `PATCH /api/admin/users/{user_id}`
```json
{ "is_active": false, "role": "admin", "new_password": "…" }
```
All fields optional. Setting `new_password` revokes the user's sessions.

Guarded: `last_admin` if this would leave no active admin, and an admin cannot disable,
demote or delete themselves.

### `DELETE /api/admin/users/{user_id}`
Same guards.

### `GET /api/admin/downloads`
The download ledger, paginated and filterable.

**Shows `source_domain`, not the full URL.** This is deliberate. An operator needs to know
that someone pulled from `youtube.com` — enough to spot abuse, respond to a complaint, and
understand load. Which specific video a named user watched is not information the operator
needs, and putting it on a screen makes the admin panel a surveillance tool. Do not
"improve" this by surfacing the URL column.

### `GET /api/admin/jobs`
Live and recent jobs across all users.

### `DELETE /api/admin/jobs/{job_id}`
Cancels any user's job.

### `GET /api/admin/audit`
The audit log: who did what, when, from where.

Entries carry a `meta` object. **`meta` must never contain credentials** — not a password,
not a hash, not a session token, not a CSRF token. It records that a password was changed,
never what it was changed to.

### `GET /api/admin/settings`
Every runtime setting with its current value, type, default, bounds, description and
group.

### `PATCH /api/admin/settings`
```json
{ "settings": { "registration_enabled": false, "max_concurrent_downloads": 4 } }
```

Validated against the `SPECS` table in `settings_store.py` — unknown keys, wrong types and
out-of-range values are rejected. Takes effect within the 10-second cache TTL, no restart.

Only settings in `SPECS` are editable here. `SECRET_KEY`, `DATABASE_URL`, `DATA_DIR`,
cookie configuration and `TRUSTED_PROXY_COUNT` are environment-only, so a compromised
admin account cannot rewrite the secret key or repoint the database.

### `POST /api/admin/cleanup`
Runs a cleanup sweep immediately.

### `DELETE /api/admin/history`
Clears history globally. Destructive and irreversible.

---

## Error codes

| Code | Status | Retryable | Meaning |
| --- | --- | --- | --- |
| `invalid_url` | 400 | no | Not a usable URL |
| `unsupported_url` | 400 | no | No provider claims it and the fallback cannot handle it |
| `blocked_target` | 400 | no | SSRF guard: resolves to a private or loopback address |
| `platform_disabled` | 403 | no | Excluded by the admin allow-list |
| `media_unavailable` | 404 | no | Deleted, or never existed |
| `private_content` | 403 | no | Not publicly accessible |
| `auth_required_content` | 403 | no | Requires a login Slipstream will not perform |
| `geo_restricted` | 403 | no | Not available from this server's location |
| `drm_protected` | 403 | no | DRM. Not circumvented, by design |
| `extractor_failure` | 502 | yes | yt-dlp failed unexpectedly |
| `platform_temporarily_unsupported` | 503 | yes | The site changed; update yt-dlp |
| `no_suitable_format` | 400 | no | The requested rung does not exist for this source |
| `ffmpeg_failure` | 500 | yes | Muxing or conversion failed |
| `ffmpeg_missing` | 503 | no | ffmpeg is not installed on the server |
| `network_timeout` | 504 | yes | Upstream did not respond in time |
| `file_too_large` | 413 | no | Exceeds `max_file_size` |
| `video_too_long` | 413 | no | Exceeds `max_video_duration` |
| `job_not_ready` | 409 | yes | Still running |
| `job_not_found` | 404 | no | No such job, or it belongs to another session |
| `job_cancelled` | 409 | no | Cancelled before it finished |
| `queue_full` | 503 | yes | `max_concurrent_downloads` reached; retry shortly |
| `download_expired` | 410 | no | TTL passed; the bytes are gone |
| `not_authenticated` | 401 | no | No session; sign in |
| `authentication_failed` | 401 | no | Wrong username or password |
| `permission_denied` | 403 | no | Insufficient role |
| `account_disabled` | 403 | no | Disabled by an admin |
| `registration_disabled` | 403 | no | Registration is off |
| `guest_downloads_disabled` | 403 | no | An account is required |
| `duplicate_account` | 409 | no | Username or email taken |
| `weak_password` | 400 | no | Fails the policy |
| `password_change_required` | 403 | no | Temporary password must be changed first |
| `csrf_failed` | 403 | no | Missing or mismatched `X-CSRF-Token` |
| `last_admin` | 409 | no | Would leave the instance with no admin |
| `rate_limited` | 429 | yes | `meta` carries the retry window |
| `maintenance_mode` | 503 | yes | Non-admin requests are being rejected |
| `validation_error` | 422 | no | Request body failed validation |
| `internal_error` | 500 | yes | Unhandled |

Anything in the `403` block above that concerns access control — `private_content`,
`auth_required_content`, `drm_protected` — is a final answer, not a problem to route
around. There is no flag, no cookie file and no credential parameter that changes it. That
is the point.

---

## A complete download

```bash
BASE=http://127.0.0.1:8000
JAR=$(mktemp)

# 1. Sign in, keeping the cookies.
curl -sc "$JAR" -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"…"}' > /dev/null

# 2. The CSRF token is a cookie; every mutation must echo it.
CSRF=$(awk '/slipstream_csrf/ {print $7}' "$JAR")

# 3. Ask what is actually available.
curl -sb "$JAR" -X POST "$BASE/api/media/analyze" \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
  -d '{"url":"https://www.youtube.com/watch?v=…"}' \
  | python -m json.tool

# 4. Queue a rung that appeared in video_options.
JOB=$(curl -sb "$JAR" -X POST "$BASE/api/download" \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
  -d '{"url":"https://www.youtube.com/watch?v=…","mode":"video","quality":"1080"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')

# 5. Poll until terminal.
while :; do
  s=$(curl -sb "$JAR" "$BASE/api/jobs/$JOB" \
      | python -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "$s"
  case "$s" in ready|failed|expired|cancelled) break ;; esac
  sleep 2
done

# 6. Collect the file.
curl -sb "$JAR" -OJ "$BASE/api/jobs/$JOB/file"
```

---

## Rate limits

Per identity — user id when signed in, client IP otherwise — on a one-hour window. `0`
means unlimited. All six are runtime-editable in the admin panel.

| Setting | Default | Applies to |
| --- | --- | --- |
| `rate_limit_guest` | 20 | analyses, anonymous |
| `rate_limit_guest_download` | 10 | downloads, anonymous |
| `rate_limit_user` | 120 | analyses, signed in |
| `rate_limit_user_download` | 60 | downloads, signed in |
| `rate_limit_admin` | 1000 | admins |
| `RATE_LIMIT_AUTH` | 10 | login and register, per IP — environment-only |

`429` responses carry the retry window in `meta`.

If a reverse proxy is in front, `TRUSTED_PROXY_COUNT` must equal the number of proxies you
control. At `0` behind a proxy, every client shares the proxy's IP and one user exhausts
everyone's quota. Set too high, a client can forge `X-Forwarded-For` and reset its own
counter at will.
