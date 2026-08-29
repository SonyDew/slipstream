# Security Policy

## Reporting a vulnerability

Do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability), which creates a private advisory thread visible only
to maintainers. If that is unavailable to you, open a public issue containing nothing but
a request for a private contact channel.

Please include: what the issue is, the affected version or commit, reproduction steps, the
impact you believe it has, and anything you already tried. A proof of concept helps, but
only run it against an instance you own.

**What to expect.** An acknowledgement within a few days, an assessment of severity and
scope after that, a fix in a release with the advisory published alongside it, and credit
in the advisory unless you prefer otherwise. This is a small self-hosted project with no
bug bounty — the response is best-effort, not contractual.

Please give a reasonable window before public disclosure so operators can update.

---

## Supported versions

Only the latest release receives security fixes. Slipstream is at `0.1.0` and pre-1.0, so
there is no long-term support branch.

---

## Scope

**In scope** — the code in this repository: the FastAPI backend, the React frontend, the
Docker images, the nginx configuration, and the deployment scripts. Examples of what is
worth reporting: authentication or session flaws, CSRF gaps, privilege escalation to
admin, SSRF past the URL guard, path traversal in file serving, SQL injection, stored or
reflected XSS, leakage of another user's data, and rate-limit bypass that enables abuse.

**Out of scope** — findings in yt-dlp, FFmpeg, or other dependencies (report those
upstream; tell us if a fix requires a change here), issues that only occur under a
deliberately insecure configuration, missing hardening headers with no demonstrated
impact, automated scanner output without a working exploit, denial of service through
sheer volume against a self-hosted instance, and social engineering of maintainers or
users.

Test only against instances you control. Do not attack third-party deployments.

---

## Design decisions relevant to security

These are intentional; understanding them prevents false reports and misconfiguration.

**Sessions, not tokens.** Authentication is a server-side session referenced by an
HttpOnly, SameSite cookie (`slipstream_session`). Only a SHA-256 hash of the session token
is stored, so a database read does not yield usable sessions. There is no JWT and no token
in `localStorage`, which removes the usual XSS-to-account-takeover path.

**Passwords.** Argon2id. The policy is at least 10 characters, at least 3 character
classes, and the password must not contain the username — enforced identically on the
server and in the UI.

**CSRF.** Double-submit: a `slipstream_csrf` cookie whose value the client echoes in the
`X-CSRF-Token` header. State-changing requests without a matching pair are rejected.

**Temporary admin.** The seeded admin account is flagged as requiring a password change.
It can read the admin panel but cannot perform privileged mutations until rotated, so an
unrotated default credential cannot be used to reconfigure the instance. **The development
default password in `backend/app/core/config.py` must be overridden before deployment** —
it is documented, not secret.

**Last-admin and self-protection.** The last remaining admin cannot be disabled, demoted,
or deleted, and no account can disable, demote, or delete itself. This prevents locking an
instance out of its own administration.

**SSRF guard.** Submitted URLs are resolved and checked before the extractor touches them;
private, loopback, and link-local targets are refused. `ALLOW_PRIVATE_NETWORK_TARGETS`
disables this and exists only for the test suite. Never enable it on a reachable instance.

**Rate limiting.** Per-role hourly limits on analysis, downloads, and authentication
attempts. Client IP is derived from `X-Forwarded-For` only as far as
`TRUSTED_PROXY_COUNT` allows; setting it higher than your actual proxy depth lets clients
spoof their address and bypass the limits.

**Privacy of stored data.** The admin download ledger stores `source_domain`, not the full
URL, because pasted links frequently carry share tokens that would otherwise be readable
by every admin. The audit log records that a password reset occurred and never any part of
the credential.

**Downloaded files.** Finished files live under `data/` with generated names, are served
only to the requesting session, and are removed by a background sweep after
`TEMP_FILE_TTL`. `data/` must never be exposed by the web server directly.

---

## Operator hardening checklist

1. Set a strong random `SECRET_KEY`. In development one is generated per boot; in
   production it is required.
2. Set `ENVIRONMENT=production`, which turns on `COOKIE_SECURE` and strict error handling.
3. Override `INITIAL_ADMIN_PASSWORD`, then rotate it in the UI on first sign-in.
4. Terminate TLS at nginx and never serve the app over plain HTTP — the session cookie
   depends on it.
5. Set `TRUSTED_PROXY_COUNT` to your real proxy depth, no higher.
6. Leave `ALLOW_PRIVATE_NETWORK_TARGETS` false.
7. Turn off `REGISTRATION_ENABLED` if the instance is for you and not the public.
8. Keep `data/` out of any web-server document root and back it up as sensitive data — it
   contains password hashes and session records.
9. Update yt-dlp regularly; extractor breakage is the most common cause of failures and
   updates often carry fixes.

---

## A note on what this tool is for

Slipstream retrieves publicly accessible media. It contains no access-control
circumvention — no DRM, paywall, private-account, login, CAPTCHA, or age-gate bypass — and
requests to add any are declined. If you find code in this repository that does defeat an
access control, that is a bug worth reporting under this policy.
