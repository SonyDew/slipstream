# Contributing to Slipstream

Thanks for taking an interest. This document covers how to get set up, what the code
expects of a change, and — importantly — the categories of contribution that will be
declined regardless of quality.

---

## Scope: what will not be merged

Slipstream processes **publicly accessible** media only. The following are out of scope by
design, not by oversight:

- DRM circumvention of any kind.
- Paywall, subscription, or rental bypass.
- Access to private, restricted, or follower-only accounts.
- Automated login, credential handling for third-party sites, or cookie injection to
  reach gated content.
- CAPTCHA solving, age-gate defeat, or other access-control evasion.
- Anything whose purpose is to disguise the tool from the site being accessed.

A patch that adds these will be closed without a code review. This boundary is what makes
the project defensible to self-host, and it is not up for negotiation in an issue thread.

Also declined: bulk/mass-download features aimed at scraping an entire channel or site,
and anything that removes the "honesty" behaviour described below.

---

## The honesty invariants

Two rules run through the whole codebase. Breaking either is a bug, even if the change
otherwise works:

1. **Never advertise a format that cannot be delivered.** The video rung list is derived
   from what the extractor actually returned for that specific item. Do not add a fixed
   ladder of resolutions and fall back silently.
2. **Never advertise an MP3 bitrate above the source.** Upsampling produces a larger file
   that is not a better one; the UI must not claim otherwise.

Related: the admin download ledger records `source_domain`, never the full URL, because
pasted links routinely carry share tokens. The audit log records *that* a password reset
happened, never any part of the credential. Keep both properties intact.

---

## Development setup

Python 3.11+, Node 20+, FFmpeg on `PATH`.

```bash
# Backend
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Frontend (separate shell)
cd frontend
npm install
npm run dev
```

Configuration is environment-driven; copy `.env.example` to `.env` if you need to change
anything. Full notes in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

---

## Before you open a pull request

Everything below must pass. CI runs the same commands, so a local run saves a round trip.

```bash
cd backend
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy app
.venv/bin/python -m pytest -q

cd ../frontend
npm run typecheck
npm run lint          # --max-warnings 0; warnings fail
npm run build
```

New behaviour needs a test. Bug fixes need a test that fails before the fix. The backend
suite is the project's safety net — it is currently 324 tests and should stay that way or
grow.

What each workflow gates, and which checks are advisory rather than blocking, is in
[docs/GITHUB.md](docs/GITHUB.md). The endpoint contract you are changing against is in
[docs/API.md](docs/API.md).

---

## Code expectations

**Match the surrounding code.** Naming, structure, comment density, and library choices
should look like what is already there rather than importing a new idiom. If a file does
something in a way that seems odd, read the comment above it first; the non-obvious
choices generally have one.

**Comments explain constraints, not mechanics.** Write a comment when the code cannot show
why something must be this way — an ordering requirement, a protocol quirk, a security
property. Do not annotate what the next line does.

**Backend.** Type hints throughout; `mypy app` is clean and must stay clean. Ruff config
lives in `backend/pyproject.toml` (line length 100, double quotes). Database access goes
through SQLAlchemy sessions; schema changes need an Alembic migration in
`backend/alembic/versions/`.

**Frontend.** TypeScript with no `any` escapes. All server calls go through the typed
client in `src/lib/api.ts` — do not call `fetch` from a component. Styling is Tailwind
using the CSS-variable tokens; do not hardcode colours. Interactive elements need
accessible labels and visible focus states, and new UI must work in both themes.

**Security-relevant surfaces** — auth, sessions, CSRF, rate limiting, the SSRF guard,
admin authorization — deserve extra care and a note in the PR description saying what you
verified. Passwords never leave the JSON request body; nothing sensitive goes in a URL,
query string, or `localStorage`.

---

## Commits and pull requests

Keep commits focused; one logical change per commit. A short imperative subject line
(under ~70 characters) and a body explaining *why* is ideal.

In the pull request, describe what changed, how you tested it, and anything you
deliberately left out. If the change touches the format list, the audit log, or auth,
say so explicitly.

---

## Reporting bugs

Open an issue with the platform, the shape of the URL (redact any token), what you
expected, what happened, and the relevant log excerpt from `data/logs/slipstream.log`.
Do not paste session cookies or full URLs containing share tokens.

For anything that looks like a **vulnerability**, do not open a public issue — follow
[SECURITY.md](SECURITY.md).

---

## Licence

Contributions are accepted under the project's licence, **AGPL-3.0-or-later**. By opening
a pull request you confirm you have the right to contribute the code and agree to it being
distributed under those terms.
