<!--
Thanks for contributing. This template mirrors the checklist in CONTRIBUTING.md.
Delete the sections that do not apply — an honest short PR description beats a
fully-filled template of "n/a".
-->

## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem being solved. Link the issue if there is one: Fixes #123 -->

## Scope check

- [ ] This does not add access to media that is not publicly accessible (no DRM,
      paywall, private-account, login, age-gate or CAPTCHA circumvention), and
      does not handle anyone's credentials for a third-party site.

## What you verified

<!--
Say what you actually ran, not what should pass. "I ran the backend suite" is
useful; "all tests pass" without having run them wastes a reviewer's time.
-->

- [ ] `ruff check .` and `ruff format --check .`
- [ ] `mypy app`
- [ ] `pytest -q` — result:
- [ ] `npm run typecheck`, `npm run lint`, `npm run build`
- [ ] `python -m app.cli verify`

Manually exercised:

<!-- Which pages or endpoints you clicked through, and against what kind of URL. -->

## If this touches any of these, describe the impact

<!-- Delete the lines that do not apply. -->

- **Authentication or sessions** — what changes about cookie handling, CSRF, or
  session lifetime? Did you confirm an anonymous caller still gets 401/403 on the
  admin API?
- **Admin permissions** — does a temporary-password admin still get read-only
  access? Are the last-admin and self-protection guards intact?
- **Format lists or quality options** — how does this stay truthful about what
  will actually be delivered? Confirm no rung is offered that the source lacks
  and no MP3 bitrate exceeds the source.
- **Audit log or download ledger** — confirm `meta` contains no credentials and
  the ledger still records `source_domain` rather than full URLs.
- **Database schema** — is there an Alembic migration, and does it apply to an
  existing populated database as well as an empty one?
- **The job queue or cleanup loop** — both are in-process and the app runs a
  single worker. Does this assumption still hold?
- **Configuration** — new settings added to `config.py` need a documented entry
  in `.env.example` (name only, no value) and a mention in `docs/DEPLOYMENT.md`.

## Notes for the reviewer

<!--
Anything you are unsure about, deliberately left out of scope, or would like a
second opinion on. Flagging a known rough edge is better than hoping it is not
noticed.
-->
