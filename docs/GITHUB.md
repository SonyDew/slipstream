# GitHub configuration

What lives in `.github/`, what each piece gates, and how a release is cut. Relevant if you fork
the project, maintain it, or are trying to work out why CI is red.

---

## Before the first push

Four files carry `OWNER` placeholders that GitHub and Docker both render as working links to a
repository that does not exist:

| File | Placeholder |
| --- | --- |
| `.github/ISSUE_TEMPLATE/config.yml` | `OWNER/REPO` in three contact-link URLs |
| `CHANGELOG.md` | `OWNER/slipstream` in the two link references at the end |
| `Dockerfile` | `OWNER/slipstream` in `org.opencontainers.image.source` |
| `deploy/linux/systemd/slipstream.service` | `OWNER/slipstream` in `Documentation=` |

```bash
grep -rl 'github.com/OWNER' . --exclude-dir=node_modules --exclude-dir=.venv \
  | xargs sed -i -e 's|OWNER/REPO|your-user/your-repo|g' \
                 -e 's|OWNER/slipstream|your-user/your-repo|g'
grep -rn 'github.com/OWNER' . --exclude-dir=node_modules --exclude-dir=.venv   # expect nothing
```

The `image.source` label is the one worth getting right: GHCR uses it to link the published
package back to the repository, and a wrong value produces a package page with a dead link.

Then, in repository settings:

- **Security → Private vulnerability reporting: enable.** The security policy tells reporters to
  use it. If it is off, the link 404s and they open a public issue instead — the exact outcome
  the policy exists to prevent.
- **Actions → General → Workflow permissions:** read-only by default. Each workflow requests what
  it needs (`packages: write` for the GHCR push, `contents: write` for the release,
  `security-events: write` for SARIF upload).
- **Code scanning: enable.** CodeQL and Trivy both upload SARIF; without it those steps fail on
  the upload.
- **Actions → Variables:** nothing required. No secret beyond the automatic `GITHUB_TOKEN` is
  used anywhere.

---

## Workflows

Five, each with a narrow trigger so an unrelated change does not run everything.

| Workflow | Triggers | Gate |
| --- | --- | --- |
| `backend.yml` | push/PR touching `backend/**` | Hard |
| `frontend.yml` | push/PR touching `frontend/**` | Hard |
| `docker.yml` | push to main, `v*` tags, PR touching Docker files | Hard; pushes only on a tag |
| `security.yml` | push, PR, weekly cron | Mixed — see below |
| `release.yml` | `v*` tags, manual dispatch | Hard |

All four non-release workflows set `concurrency` with `cancel-in-progress`, so a new push
supersedes an in-flight run on the same ref rather than queueing behind it.

### `backend.yml`

Two jobs.

**`test`** runs the same commands `CONTRIBUTING.md` asks contributors to run, on a
3.11 / 3.12 matrix — 3.11 is the floor in `pyproject.toml`, 3.12 is what the Docker image
ships, and both have to stay green. In order: `ruff check .`, `ruff format --check .`,
`mypy app`, `pytest -q`, then `python -m app.cli verify`.

FFmpeg is installed deliberately. Several tests exercise the muxing and MP3 paths, which report
themselves unavailable without it; installing it means CI checks the real behaviour rather than
the degraded one.

The `verify` smoke test is there because it touches the database, the admin seed and the
toolchain check — the paths an operator hits first, and the ones unit tests mock out.

**`startup`** boots the app with `ENVIRONMENT=production`, waits for `/api/health/ready`, then
checks `/api/health`, `/api/config` and `/api/media/platforms` answer, and that
`/api/admin/stats` returns 401 or 403 to an anonymous caller. That last assertion is duplicated
from the unit tests on purpose: a regression that opens the admin API is the worst thing this
project could ship, so it is asserted against a real running server as well.

### `frontend.yml`

`npm ci` (falling back to `npm install` only if the lockfile is absent), then `typecheck`,
`lint`, `build`, on Node 20 and 22. The lint script passes `--max-warnings 0`, so a warning
fails the job.

Then the check worth knowing about:

```bash
entry=$(ls dist/assets/index-*.js)
if grep -q 'recharts' "$entry"; then
  echo "FAIL: recharts is bundled into the entry chunk."
  exit 1
fi
test -n "$(ls dist/assets/charts-*.js 2>/dev/null)"
```

recharts plus its d3 dependencies is by far the largest thing in the tree. A single static
import outside the `lazy()` boundary puts it in the entry chunk, and then every visitor
downloads a charting library to view the home page. The job fails both if recharts appears in
the entry chunk and if no separate `charts-*.js` chunk was emitted, because the second means the
`manualChunks` configuration stopped working even though nothing looks wrong.

The built bundle is uploaded as an artifact from the Node 20 leg only — two identical artifacts
would collide.

### `docker.yml`

**`build`** is a matrix over `linux/amd64` and `linux/arm64`. QEMU is set up only for arm64.
Emulated arm64 builds are slow, mostly in the frontend stage, but they catch the
wheel-availability problems that only appear on aarch64 — which is the whole reason for testing
it, since the Oracle free tier is ARM.

`load: true` only for amd64, because you cannot load a foreign-architecture image into the local
daemon for testing. The amd64 leg then smoke-tests the actual container:

- readiness within 90 seconds, dumping `docker logs` if not
- `/api/health` answers
- `GET /` serves the SPA
- `GET /assets/nope.js` returns **404**, not the SPA shell — the single-origin routing rule
- `GET /api/admin/stats` returns 401 or 403
- `ffmpeg -version` runs inside the image
- `id -u` is not 0

**`push`** is a separate job gated on `if: startsWith(github.ref, 'refs/tags/v')`. Main does not
push, because main should not overwrite a published `:latest` that operators are pulling. It
builds both architectures in one `build-push-action` invocation so GHCR receives a proper
manifest list rather than two images racing for the same tag.

Tags come from `docker/metadata-action@v5`:

| Tag | Example for `v0.1.0` |
| --- | --- |
| `{{version}}` | `0.1.0` |
| `{{major}}.{{minor}}` | `0.1` |
| `latest` | `latest` |

```bash
docker pull ghcr.io/OWNER/REPO:0.1.0
```

### `security.yml`

Runs on push and PR, and on a weekly cron at `17 6 * * 1` — Mondays 06:17 UTC. Off the hour
because top-of-hour cron on GitHub's shared runners queues behind everyone else's schedules and
can be delayed ten minutes or more. The scheduled run matters because a dependency becomes
vulnerable while the code sits untouched; without it, a CVE published after the last commit goes
unnoticed.

Which jobs can actually fail the run:

| Job | Behaviour | Why |
| --- | --- | --- |
| `python-deps` (pip-audit) | Advisory | yt-dlp moves fast enough that a hard gate blocks unrelated work, and the fix is usually "update yt-dlp", already a documented task. **Read the step summary.** |
| `node-deps`, production | **Hard**, `--audit-level=high` | These ship to users. |
| `node-deps`, dev | Advisory | A vulnerability in vite or eslint does not reach a user — the build output is static files and the dev server never runs in production. |
| `codeql` | **Hard** | python + javascript-typescript, `security-and-quality`. |
| `secrets` | **Hard** | gitleaks plus two project-specific checks. |
| `image` (Trivy) | Advisory, uploads SARIF | `ignore-unfixed: true`, `exit-code: 0`. The Debian base and ffmpeg's dependency tree carry unfixed CVEs at any moment; failing on something with no upstream patch is not actionable. |

pip-audit's advisory result appears in the job's step summary and as a downloadable artifact. It
is the one thing here that needs reading rather than trusting.

gitleaks is given `fetch-depth: 0`. It scans commits, not just the tree — a shallow clone
reports a clean repo even when a key was committed and later removed.

#### The two project-specific secret checks

**`.env.example` must carry names only.**

```bash
bad=$(grep -vE '^\s*(#|$)' .env.example | grep -E '=\s*\S' || true)
```

Any line with an assigned value fails the job. The example file documents variable *names*; a
real value pasted into it gets committed and then copied into production by everyone who follows
the quick start.

**The development admin fallback must not appear on a deployment surface.**

```bash
hits=$(grep -rIln '<the development default>' \
         .env.example docker-compose*.yml Dockerfile \
         docker/ scripts/ deploy/ nginx/ docs/ \
         README.md README_WINDOWS.txt 2>/dev/null || true)
```

The real pattern is in `security.yml` — it is not repeated here, because `docs/` is one of the
directories the check scans, so writing the literal value into this file would fail the job.

Note the scope. The string legitimately appears in five places in backend code and tests —
`app/core/config.py` (the `INITIAL_ADMIN_PASSWORD` default), `app/db/init_db.py` (the fallback,
documented in the README on purpose), and three test assertions including ones checking it is
*not* what gets stored. The check is scoped to deployment surfaces, not the whole repo, so it
fails only when the value has reached somewhere an operator would copy it from.

If you rename that fallback, update this grep pattern with it or the check silently passes
forever.

### `release.yml`

Three jobs, each gating the next.

**`verify`** derives the version from the tag by stripping `v`, then checks two things:

1. The tag matches `version` in `backend/pyproject.toml`. A tag that disagrees produces an image
   reporting one number and a release page claiming another, which is impossible to debug from a
   bug report six months later.
2. `CHANGELOG.md` contains a `## [<version>]` section.

**`build`** runs `npm ci && npm run build` and packages `frontend/dist` as
`slipstream-frontend-<version>.tar.gz` with a `.sha256` alongside it. Operators deploying from
source without Node — both the Windows and bare-systemd paths allow this — drop the archive in
as `frontend/dist` and skip the toolchain.

**`release`** extracts the notes from the changelog rather than from commit messages, so the
release page says what changed for an operator instead of what changed in the tree:

```bash
awk -v v="$version" '
  index($0, "## [" v "]") == 1 { inside = 1; next }
  inside && /^## / { exit }
  inside && /^\[[^]]+\]: / { exit }
  inside { print }
' CHANGELOG.md > notes-body.md
```

`index()` rather than a regex, deliberately. The heading contains `[` and `]`, and awk applies
its own escape processing to a dynamic regex string before the regex engine ever sees it — so
`"^## \\[" v "\\]"` arrives as a bare `[`, opening a character class that never matches the
heading. It fails silently, producing empty release notes. The second `exit` stops at the
trailing link-reference block so those lines do not land in the notes, and the step fails
outright if the extraction came back empty.

It appends the `docker pull` line, the per-target upgrade commands and a pointer to
`SECURITY.md`, then calls `gh release create`. Any `0.*` version is published with
`--prerelease`, so nobody reads a pre-1.0 tag as a stability promise the project has not made.

`workflow_dispatch` accepts an existing tag, which is how you re-run a release whose workflow
failed after the tag was already pushed.

---

## Cutting a release

```bash
# 1. Bump the version — this is the one the workflow checks.
$EDITOR backend/pyproject.toml            # version = "0.2.0"

# 2. Add the changelog section. The heading must be exactly ## [0.2.0]
$EDITOR CHANGELOG.md

# 3. Confirm the two things verify checks, before pushing the tag.
grep -m1 '^version' backend/pyproject.toml
grep -E '^## \[0\.2\.0\]' CHANGELOG.md

# 4. Commit, tag, push.
git commit -am 'Release 0.2.0'
git tag -a v0.2.0 -m 'Slipstream 0.2.0'
git push origin main --follow-tags
```

The tag triggers `release.yml` and `docker.yml` in parallel. When both finish there is a GitHub
release with the frontend archive attached, and a two-architecture image on GHCR tagged
`0.2.0`, `0.2` and `latest`.

If `verify` fails, the tag is already pushed and points at the wrong state. Delete it, fix, and
re-tag:

```bash
git tag -d v0.2.0
git push origin :refs/tags/v0.2.0
```

Do this promptly. Once anyone has fetched the tag, moving it is worse than releasing a `.1`.

---

## Dependabot

Weekly for pip (`/backend`), npm (`/frontend`) and docker (`/`); monthly for github-actions, all
grouped so the queue stays readable:

| Ecosystem | Groups |
| --- | --- |
| pip | `dev-tooling` (by `dependency-type: development`), `fastapi-stack` (fastapi, starlette, uvicorn\*, pydantic\*) |
| npm | `react`, `build-tooling` (vite, typescript, eslint), `tailwind` |
| github-actions | everything in one |

**yt-dlp matches no group, on purpose.** It arrives as its own pull request because a bump can
change which formats a site reports — which is exactly what the format-honesty tests exist to
pin down. Batched with five other packages, a behaviour change in the format list is invisible
in review. Do not add it to a group.

`dev-tooling` batches ruff, mypy and pytest: they churn constantly and never affect runtime
behaviour.

---

## Issue and pull request templates

`blank_issues_enabled: false`, so every issue goes through a form or a contact link.

**`bug_report.yml`** opens with two required checkboxes:

- yt-dlp was updated first, because that fixes most extraction reports
- "The media I was downloading is publicly accessible — no login, paywall, DRM, age gate or
  private account involved."

The second one filters out bypass requests dressed as bug reports before anyone spends time on
them. A deployment dropdown enumerates the six real deployment paths, and the log field warns:
**redact URLs you would rather not publish, and never paste a `SECRET_KEY`, cookie or session
token.**

**`feature_request.yml`** has a scope checkbox, an area dropdown, and a required
"How it interacts with the honesty invariants" field — `n/a` is an acceptable answer, but it has
to be a deliberate one. The invariants (never list a video rung the source lacks, never
advertise an MP3 bitrate above source) are the kind of thing a feature erodes by accident.

**`config.yml`** offers four contact links instead of issue forms: the private security advisory,
an explicit "Request for an access-control bypass" link that states such requests will be closed
and that this is not negotiable, the troubleshooting guide, and yt-dlp upstream for site
breakage.

The bypass link exists so the answer is visible before the issue is filed, rather than being
delivered as a closure that reads as hostile.

**`PULL_REQUEST_TEMPLATE.md`** has a scope check, a "What you verified" checklist mirroring the
commands in `CONTRIBUTING.md` — *"Say what you actually ran, not what should pass"* — and
per-area impact prompts for auth and sessions, admin permissions, format lists, the audit log
and ledger (`meta` carries no credentials; the ledger records `source_domain`), schema and
Alembic changes, the single-worker queue assumption, and new configuration needing a names-only
`.env.example` entry.

---

## Running CI locally

Everything the workflows run is available without pushing:

```bash
cd backend
ruff check . && ruff format --check . && mypy app && pytest -q
python -m app.cli verify

cd ../frontend
npm run typecheck && npm run lint && npm run build
grep -c recharts dist/assets/index-*.js        # expect 0
ls dist/assets/charts-*.js                     # expect one file

cd ..
grep -vE '^\s*(#|$)' .env.example | grep -E '=\s*\S'    # expect no output
docker compose build && docker compose up -d && curl -fsS http://127.0.0.1:8000/api/health
```

---

## When something is red

**Backend, one Python version only** — a version-specific API. Reproduce with that interpreter
rather than assuming CI is wrong.

**`ruff format --check` fails** — run `ruff format .` and commit the result. Formatting is not a
matter of opinion here.

**Frontend lint** — `--max-warnings 0` means a warning is a failure. Fix it, or add a targeted
disable comment with a reason.

**recharts check** — something imports it statically. `grep -rn recharts frontend/src`; only
`components/admin/charts.tsx` should match, reached through `lazy()`.

**arm64 Docker build only** — usually a Python package with no aarch64 wheel, now building from
source and failing on a missing header. Check the build log for the compile step.

**Docker smoke test never becomes ready** — read the `docker logs` output the step dumps on
failure. Usually a missing `SECRET_KEY` or a startup exception.

**CodeQL upload fails** — code scanning is not enabled in repository settings.

**gitleaks flags something** — assume it is right until proven otherwise. If a real secret was
ever committed, rotate it; removing the commit does not un-publish it.
