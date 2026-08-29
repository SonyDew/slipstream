# Development

Setting up, working on, and testing Slipstream locally.

---

## Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| Python | 3.11+ | `X \| Y` unions and `tomllib` are used unconditionally |
| Node | 20+ | Vite 6 requires it |
| FFmpeg | any recent | Muxing adaptive streams and MP3 conversion |
| Git | any | |

FFmpeg is technically optional and the app degrades honestly without it — MP3 options
disappear, adaptive-only video rungs are hidden, and the analyze response explains why. But
you cannot meaningfully test the download pipeline without it, and CI installs it
deliberately so that CI exercises real behaviour rather than the degraded path.

Check: `ffmpeg -version` and `ffprobe -version` must both resolve.

---

## Setup

```bash
git clone <url> slipstream && cd slipstream

# Backend
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
# Windows: .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt

# Frontend
cd ../frontend
npm install
```

No `.env` is needed for development — every setting has a default that lets the app boot.
Create one when you want to change something:

```bash
cp .env.example .env      # repo root, or backend/.env
```

`.env.example` carries **names only, no values**, on purpose. A value in the example file
gets committed and then copied into production by everyone following the quick start.
`.github/workflows/security.yml` fails the build if a value appears there.

---

## Running

Two terminals:

```bash
# Terminal 1 — backend on :8000
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — Vite on :5173
cd frontend && npm run dev
```

Work against **http://127.0.0.1:5173**. Vite proxies `/api` to the backend, so the browser
sees a single origin exactly as it will in production. Cookie, CSRF and CORS behaviour is
therefore identical between development and deployment, which is the entire reason the
proxy exists rather than setting `CORS_ORIGINS`.

The proxy target is `VITE_API_TARGET`, defaulting to `http://127.0.0.1:8000`. Override it
if your backend is elsewhere — the dev compose overlay sets it to `http://app:8000`, since
inside that container `localhost` is Node itself.

The database is created and the initial admin seeded on first boot.

### Single-origin mode

Production serves the built SPA from the backend, with no Vite involved. Test it
occasionally, because it is the only mode where the SPA fallback, the asset mount and the
404-not-shell behaviour are actually exercised:

```bash
npm --prefix frontend run build
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000
# everything on http://127.0.0.1:8000
```

`FRONTEND_DIST` overrides where the backend looks for `dist/`.

### First sign-in

`INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD`, defaulting to the documented
development fallback in `backend/app/core/config.py`. The account is flagged
`must_change_password`, so it can read the admin panel but not mutate anything until you
change the password. That is not a bug — it is what stops a deployment sitting on a default
credential with full write access.

---

## Checks

Everything below must pass before a PR. They are the same commands CI runs, so there are no
surprises waiting in the pipeline.

```bash
cd backend
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy app
.venv/bin/python -m pytest -q          # 324 passed, 1 skipped
.venv/bin/python -m app.cli verify

cd ../frontend
npm run typecheck
npm run lint                            # --max-warnings 0
npm run build
```

`npm run lint` uses `--max-warnings 0` deliberately. A warning nobody has to fix
accumulates until the output is noise and real problems hide in it.

`npm run build` runs `tsc -b` first, so a type error fails the build rather than producing
a bundle with broken types.

### Tests

```bash
.venv/bin/python -m pytest -q                       # everything
.venv/bin/python -m pytest tests/test_formats.py -v # one file
.venv/bin/python -m pytest -k slideshow             # by name
.venv/bin/python -m pytest -m live                  # hits real sites; excluded by default
```

The `live` marker exists for tests that talk to real platforms. They are excluded from CI
because a third-party site changing its markup is not a reason to fail your build — that
belongs in a scheduled check, not a merge gate.

| File | Covers |
| --- | --- |
| `test_formats.py` | The honesty invariants. **The most important file here.** |
| `test_auth.py` | Sessions, password policy, hashing, CSRF |
| `test_admin.py` | Permissions, last-admin and self-protection guards |
| `test_media_api.py` | analyze, download, job lifecycle |
| `test_providers.py` | URL claiming and per-platform normalisation |
| `test_security_ssrf.py` | The private-address guard |
| `test_ratelimit.py` | Windows, identity keying, proxy handling |
| `test_jobs_cleanup.py` | TTL expiry, temp sweeping |
| `test_filenames.py` | Sanitisation, Unicode, length caps |
| `test_health.py` | Health and config endpoints |

Tests use an in-memory SQLite database and set `ALLOW_PRIVATE_NETWORK_TARGETS` so they can
point at a local fixture server. **That flag is test-only.** In production it disables the
SSRF guard, turning any submitted URL into a request from inside your network.

---

## Project layout

```
backend/
├── app/
│   ├── api/routes/       HTTP only — parse, call a service, shape the response
│   ├── core/             config, security, rate limiting, SSRF, errors, logging
│   ├── db/               engine, session, init
│   ├── middleware/       request context, security headers, CSRF, maintenance
│   ├── models/           SQLAlchemy 2.0 declarative
│   ├── providers/        per-platform knowledge + registry
│   ├── schemas/          Pydantic request/response models
│   ├── services/         the actual work
│   ├── cli.py
│   └── main.py           app factory, middleware, SPA mounting
├── alembic/
└── tests/

frontend/src/
├── components/{ui,layout,media,admin}/
├── hooks/
├── lib/                  api client, auth context, theme, types
├── pages/                including pages/admin/
└── styles/
```

[ARCHITECTURE.md](ARCHITECTURE.md) explains why the layers are drawn where they are.

---

## Common tasks

### Add a platform provider

1. Create `app/providers/newsite.py` subclassing the base provider. Declare which URL
   patterns it claims; override normalisation only for that platform's quirks.
2. Register it in `app/providers/registry.py`.
3. Add cases to `tests/test_providers.py` — the URL patterns it should and should not
   claim, and any normalisation you added.
4. `GET /api/media/platforms` picks it up automatically.

Do not touch the services. If a platform needs a service change, that is a signal the
provider abstraction is missing something, and the fix belongs in the abstraction.

### Add an API endpoint

1. Request and response models in `app/schemas/api.py`.
2. The route in the appropriate `app/api/routes/*.py` — parsing and shaping only.
3. Logic in a service.
4. Tests.
5. Document it in [API.md](API.md), including any new error code.

Check the router's prefix before assuming a path. The media router has none, which is why
`/api/download` is not `/api/media/download`.

### Add a setting

**Runtime-editable** (admins can change it without a restart): add a `SettingSpec` to
`SPECS` in `app/core/settings_store.py` with a type, a default that reads from the
environment, a description, and bounds for numerics. The admin settings page renders it
from the spec — no frontend change needed.

**Environment-only** (secrets, paths, anything that must not be admin-writable): add it to
`app/core/config.py`, then to `.env.example` as a bare name with a comment explaining what
it does and what goes wrong if it is set incorrectly.

Deciding between the two: could a compromised admin account cause real damage by changing
it? `SECRET_KEY`, `DATABASE_URL`, `DATA_DIR` and `TRUSTED_PROXY_COUNT` are environment-only
for exactly that reason.

To publish a setting to anonymous callers, add it to `public_settings()` — and think first,
because that puts it in `/api/config` for the whole internet.

### Change the schema

```bash
cd backend
.venv/bin/python -m alembic revision -m "add thing to jobs"
# edit the generated file
.venv/bin/python -m alembic upgrade head
```

Write the migration by hand rather than trusting autogenerate. SQLite's `ALTER TABLE` is
limited, and autogenerate produces operations it cannot perform.

Test against a **populated** database, not just an empty one. A migration that works on
`init-db` output and fails on real data is worse than no migration, because it fails during
an upgrade when the operator has already stopped the service.

### Change what qualities are offered

`app/services/formats.py`, and read the honesty invariants in
[ARCHITECTURE.md](ARCHITECTURE.md) first. `tests/test_formats.py` is the gate. Never offer
a rung the source lacks; never advertise an MP3 bitrate above the source.

### Add a frontend page

1. `src/pages/thing.tsx`.
2. Route it in `src/App.tsx`. Admin pages go under `pages/admin/` behind the existing lazy
   boundary.
3. Compose from `components/ui/` primitives rather than adding a component library.
4. Call the API through `lib/api.ts`, never bare `fetch` — the wrapper attaches CSRF,
   unwraps the error envelope, and handles 401.

**Do not statically import `recharts` outside the lazy chart boundary.** recharts plus d3
is the largest dependency in the tree; a static import lands it in the entry chunk and
every visitor downloads it to view the home page. CI fails the build if it appears there.

---

## Operational CLI

```bash
cd backend
.venv/bin/python -m app.cli verify        # schema, admin account, toolchain
.venv/bin/python -m app.cli init-db
.venv/bin/python -m app.cli create-admin --username alice --email alice@example.com
.venv/bin/python -m app.cli reset-password --username admin
.venv/bin/python -m app.cli stats
.venv/bin/python -m app.cli cleanup
.venv/bin/python -m app.cli settings
.venv/bin/python -m app.cli settings --set registration_enabled=false
```

Omit `--password` on `create-admin` and `reset-password` to be prompted. Passing it on the
command line puts it in your shell history and in `ps` output for anyone on the box.

`verify` is the fastest way to answer "is this install sane" and is what every deployment
script runs last.

---

## Debugging

**Nothing at `/`, JSON at `/api/health`.** `frontend/dist` does not exist. Run
`npm --prefix frontend run build`, or use the Vite dev server.

**`Unexpected token '<'` in the console.** An asset request returned HTML. In this app that
should not happen — the SPA fallback checks for the file first and returns a real 404 — so
suspect a proxy in front rewriting the path.

**Jobs stay `queued` forever.** The queue is in-process. Either the worker task did not
start (check startup logs) or you are running more than one uvicorn worker, in which case
the job is in another process's memory. Development must use one worker; `--reload` implies
one.

**CSRF failures on every mutation.** The `slipstream_csrf` cookie is not reaching the
browser, or the client is not echoing it as `X-CSRF-Token`. Cross-origin requests are the
usual cause — use the Vite proxy rather than hitting `:8000` directly from `:5173`.

**`blocked_target` on a URL that obviously works.** The SSRF guard rejected the resolved
address. Expected for anything on your LAN. `ALLOW_PRIVATE_NETWORK_TARGETS=true` lifts it
for local testing; never in production.

**`ffmpeg_missing`, or no MP3 options.** ffmpeg is not on `PATH` as seen by the *server
process*, which is not always the same `PATH` as your shell. Set `FFMPEG_PATH` and
`FFPROBE_PATH` to absolute paths.

**Logging.** `LOG_LEVEL=DEBUG` for verbose output, `LOG_JSON=true` for structured lines.
Files land in `data/logs/`.

More in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Style

Ruff and mypy settings live in `backend/pyproject.toml`; ESLint config in `frontend/`. Run
the formatters rather than arguing with them.

Two things the tools cannot check:

**Comment the constraint, not the code.** A comment earns its place by recording something
the code cannot show — why a value is what it is, what breaks if it changes, which
non-obvious failure it prevents. `# increment the counter` above `count += 1` is noise. So
is `# fixed in this PR`, which is you talking to a reviewer about a moment that ends when
the PR merges.

**Errors should be honest and specific.** `MediaUnavailableError` and `PrivateContentError`
are different situations and the user can act on the difference. Reaching for a generic
failure because it is less work makes the product worse in a way no test catches.
