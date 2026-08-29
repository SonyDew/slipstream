# Security for operators

The root [SECURITY.md](../SECURITY.md) is the reporting policy: how to disclose a
vulnerability, what is in scope, and which design decisions are deliberate. This document is
for the person running an instance — what you are defending, what the code already does for
you, what only you can do, and what to watch.

---

## Threat model

What a self-hosted Slipstream instance actually faces, in the order it matters.

**An untrusted user with an account.** The most likely adversary, because if registration is
open you have handed one out. They can submit URLs, which means they can make your server issue
outbound HTTP requests, consume your CPU on muxing, and fill your disk. Defences: the SSRF
guard on resolved addresses, per-role rate limits, `MAX_FILE_SIZE` and `MAX_VIDEO_DURATION`
ceilings, and the temp-file sweep. None of them are optional in a public deployment.

**An unauthenticated visitor.** Reaches the SPA, the health endpoints, `/api/version`,
`/api/config` and the auth endpoints, plus analysis and download while
`GUEST_DOWNLOADS_ENABLED` is on. Everything else is 401. Auth endpoints have their own tighter
rate limit because they are the credential-stuffing surface.

**A non-admin user reaching for admin.** Every `/api/admin/*` route requires an admin session,
and every *mutating* one additionally requires `RequireAdminVerified` — an admin still on a
temporary password can read and cannot change anything.

**A compromised admin account.** Assume it happens. This is why `SECRET_KEY`, `DATABASE_URL`,
`DATA_DIR`, the cookie names and `TRUSTED_PROXY_COUNT` are **environment-only** and cannot be
rewritten through the settings API. An attacker with admin cannot relocate your database,
rotate your signing key, or silently raise their own trusted-proxy depth to defeat rate
limiting. They can change the 14 runtime settings, and that is the intended blast radius.

**Someone who has your disk or your backup.** Passwords are Argon2id, session tokens are stored
only as SHA-256 hashes, and the download ledger holds `source_domain` rather than full URLs. A
stolen database does not yield usable sessions or plaintext credentials, but it does yield
usernames, email addresses, hashes and browsing domains. Treat backups accordingly.

**XSS.** There is no token in `localStorage` and the session cookie is HttpOnly, so script
execution does not directly yield a portable credential. The CSP is restrictive. React escapes
by default and nothing in the app uses `dangerouslySetInnerHTML`.

**Not in the model.** Volumetric denial of service against a single self-hosted box; a hostile
kernel or hypervisor; a hostile operator. If you do not trust your admins, this is the wrong
architecture.

---

## What the code enforces

You get these without configuring anything.

### Authentication

Server-side sessions, referenced by an HttpOnly `slipstream_session` cookie. The database
stores only a SHA-256 hash of the token, so reading the sessions table does not let you
impersonate anyone. Sessions carry an absolute expiry and are revoked on logout;
`POST /api/auth/logout-all` revokes every session for the account, which is the correct
response to "I think someone has my password".

Passwords are Argon2id via `argon2-cffi`. The policy — at least 10 characters, at least 3
character classes, must not contain the username — is implemented once on the server and
mirrored in the UI so the client can give immediate feedback without being the thing that
enforces it.

There is deliberately no JWT. A stateless token cannot be revoked before it expires; a session
row can be deleted.

### CSRF

Double-submit. `slipstream_csrf` is a readable cookie whose value the client echoes as
`X-CSRF-Token`. The middleware rejects state-changing requests where the two do not match.
This works because an attacker's page can cause a request to your origin but cannot read your
cookie to populate the header.

### Authorization

`RequireAdmin` gates reads; `RequireAdminVerified` gates writes. Beyond that:

- The last remaining admin cannot be disabled, demoted or deleted.
- No account can disable, demote or delete itself.

Both exist to prevent an instance being locked out of its own administration — a support
problem that is much worse than the mistake it prevents.

### SSRF

Submitted URLs are resolved and the resulting address checked before yt-dlp is invoked.
Private, loopback, link-local and multicast targets are refused with `blocked_target`. This is
the guard that stops "download this video" from becoming "fetch
`http://169.254.169.254/latest/meta-data/` and tell me what it says".

`ALLOW_PRIVATE_NETWORK_TARGETS=true` disables it. It exists so the test suite can talk to a
local fixture server. **On a reachable instance this is a critical misconfiguration**, not a
convenience toggle.

### Command execution

yt-dlp and ffmpeg are invoked as argument lists — no shell, no string interpolation of
user input. Users choose from an enumerated set of quality options; they never supply a raw
yt-dlp format selector, because a format selector is expressive enough to be an injection
surface of its own.

### File serving

Finished files live under `DATA_DIR` with generated names, are served only to the session that
created the job, and are deleted by the background sweep after `TEMP_FILE_TTL`. Job identifiers
are opaque. The file endpoint resolves paths and rejects anything that escapes the temp root.

**`data/` must never be inside a web-server document root.** Nothing in the shipped nginx
config exposes it; if you add a `location` that does, you have published your database.

### Rate limiting

Two independent layers, and they are not redundant:

- **nginx** — coarse per-IP zones (`slipstream_api` 30 r/m, `slipstream_auth` 10 r/m,
  `slipstream_static` 300 r/m). Cheap, and rejects before the request reaches Python.
- **the app** — per-role hourly limits on analysis, downloads and auth attempts, editable at
  runtime. Understands *who* is asking, not just from where.

### Error handling

A single envelope: `{"error": {"code", "message", "retryable", "details"}}`. Codes are stable
and safe to branch on. Internal exception text and stack traces are not returned in
production — the code tells the client what happened without describing your filesystem.

---

## What only you can do

The code cannot do these for you. Every one of them has been the cause of a real
misconfiguration.

### 1. A persistent `SECRET_KEY`

```bash
python -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Required in production; the app refuses to start without it rather than generating one per
boot, because a per-boot key logs everyone out on every restart and presents as an intermittent
bug rather than a configuration error. Store it once, back it up with the database — a restore
with a different key invalidates every session.

### 2. TLS, or no public exposure

The session cookie is the credential. Over plain HTTP it is readable by anything on the path.
There is no configuration that makes an HTTP-exposed instance safe; either terminate TLS or
keep the instance off the public internet.

### 3. `COOKIE_SECURE=true`

Set it explicitly in production rather than relying on it being implied. With it set and TLS
broken, users are signed out on every page load — a loud failure. Without it and TLS working,
the cookie is merely willing to travel in the clear — a silent one. Prefer the loud failure.

### 4. `TRUSTED_PROXY_COUNT` exactly right

This is the setting people get wrong in both directions:

| Value | Effect |
| --- | --- |
| Too low (0 behind a proxy) | Every client appears to be the proxy. One shared rate-limit bucket; one user's downloads throttle everybody. |
| Too high | A client can inject `X-Forwarded-For` and choose its own identity, resetting its own rate limit at will. |

Count only the proxies **you** control. One nginx in front means `1`. It is environment-only so
a compromised admin cannot raise it.

### 5. Close the app port

The app should bind loopback and nginx should reach it there. If `:8000` is open to the
internet, every protection nginx provides — TLS, the rate-limit zones, the security headers —
is bypassable by talking to the app directly.

```bash
sudo ss -tlnp | grep :8000        # expect 127.0.0.1:8000, not 0.0.0.0:8000
curl -sI http://<public-ip>:8000/api/health   # from elsewhere: must fail
```

### 6. Decide about registration

`REGISTRATION_ENABLED=false` if the instance is for you. Every open-registration instance is
an open proxy for outbound requests and an open claim on your CPU and disk.

`GUEST_DOWNLOADS_ENABLED` defaults to on and goes further: it lets unauthenticated visitors
consume resources, with no account to disable when one abuses it. Only reasonable behind other
access controls. It is also editable at runtime as `guest_downloads_enabled` in the admin
settings, so turning it off does not need a restart.

### 7. Bound the resource ceilings

`MAX_FILE_SIZE`, `MAX_VIDEO_DURATION`, `MAX_CONCURRENT_DOWNLOADS` and `TEMP_FILE_TTL` are what
stand between a user and your disk. The worst case for temp usage is roughly
`MAX_CONCURRENT_DOWNLOADS × MAX_FILE_SIZE`, held for up to `TEMP_FILE_TTL`. Check that number
against your free space; a full disk takes SQLite down with it.

### 8. Treat backups as sensitive

The database holds password hashes, session records, email addresses, the audit log and the
ledger's `source_domain` values. Back it up with the same care you would give the instance —
encrypted at rest, restricted permissions, and not in a public bucket. See
[BACKUPS.md](BACKUPS.md).

### 9. Keep yt-dlp current

Mostly a functionality concern, but it is also third-party code parsing hostile input on your
server. See [UPDATES.md](UPDATES.md).

---

## Privacy of what you store

Deliberate choices worth knowing about, because they are easy to undo by accident.

**The ledger stores `source_domain`, not the URL.** Pasted links routinely carry share tokens,
playlist context and referrer parameters. Storing full URLs would make every admin able to read
every user's exact viewing history, forever. Do not "improve" the ledger by surfacing the URL
column.

**The audit log never contains credentials.** It records that a password was reset, by whom and
when — never any part of the old or new value. When adding an audit entry, the `meta` field must
carry no credential material. This is a hard rule, not a preference.

**Admin `createUser` keeps the password in the JSON request body.** Never move it to a query
parameter or path segment: those land in the nginx access log, in browser history and in any
intermediate proxy's logs.

**Logs.** `data/logs/slipstream.log` and the nginx access log contain paths and IP addresses.
The nginx format deliberately omits query strings from the logged request where it can. Rotate
and retain deliberately, and redact before pasting anything into an issue.

**`HISTORY_RETENTION_DAYS`** bounds how long per-user history persists. The cleanup sweep
enforces it. Lower it if you would rather hold less.

---

## Hardening beyond the defaults

### systemd

The bare-metal unit already sets `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
`ProtectHome`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectKernelLogs`,
`ProtectControlGroups`, `RestrictAddressFamilies` (AF_INET, AF_INET6, AF_UNIX),
`RestrictNamespaces`, `LockPersonality`, `RestrictSUIDSGID`, and a `SystemCallFilter` of
`@system-service` minus `@privileged @obsolete @resources`, with `ReadWritePaths` limited to the
data directory — necessary because `ProtectSystem=strict` makes everything else read-only.

`MemoryDenyWriteExecute` is **not** set, and should not be added: CPython's JIT-adjacent
allocations and some native extension loading need writable-then-executable pages, and the unit
simply fails to start with it on.

### Container

Runs as uid 10001, non-root. Add what your environment allows:

```yaml
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
```

`read_only: true` needs every writable path to be a volume or tmpfs — the data volume and
`/tmp`. Test it before relying on it.

### nginx

The shipped config sets HSTS, `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, a restrictive `Content-Security-Policy` and a `Permissions-Policy`.

Two things to know:

- **`add_header` inside a `location` replaces the entire inherited set.** If you add one header
  to a location, re-include the security-headers snippet in that location or you have silently
  removed all of them for those responses. Verify with `curl -sI` against `/` *and* `/assets/`.
- **`upgrade-insecure-requests` is deliberately omitted from the CSP.** It breaks local and LAN
  deployments that legitimately run without TLS, and on a properly TLS-terminated instance HSTS
  already covers the case.

HSTS ships without `preload`. Preloading is effectively irreversible and not something a
deployment script should decide on your behalf.

### Fail2ban

Optional, and reasonable on a public instance. The app returns 401 for a failed sign-in and
logs it; a jail on the nginx access log watching for repeated 401s against `/api/auth/login`
adds an IP-level ban on top of the rate limit.

---

## What to monitor

Nothing here requires a monitoring stack; these are the things worth looking at.

**The audit log** (`/api/admin/audit`) is the security-relevant one. Watch for user creation you
did not perform, role changes, settings changes — particularly registration being re-enabled or
limits being raised — and password resets.

**Failed sign-ins.**

```bash
sudo journalctl -u slipstream --since '1 day ago' | grep -i 'login failed'
sudo awk '$9 == 401' /var/log/nginx/access.log | wc -l
```

**Storage.** `/api/health/storage` reports temp usage and free space. Alert on free space, not
temp size — the sweep is supposed to grow and shrink temp.

**Disk and process.**

```bash
df -h /
du -sh /opt/slipstream/data/*
ps aux | grep uvicorn        # exactly one; more than one breaks the queue and the sweep
```

**Certificate expiry.**

```bash
sudo certbot certificates
sudo systemctl list-timers | grep certbot
```

A renewed certificate that nginx has not reloaded is still the old certificate. Confirm the
deploy hook exists.

**Dependency advisories.** The `security.yml` workflow runs pip-audit, `npm audit`, CodeQL, a
secret scan and Trivy weekly. On a fork, check the Actions summaries; the Python audit is
advisory and will not fail the run, so it needs reading rather than trusting.

---

## Incident response

If you believe an account is compromised:

1. Disable it in the admin panel — this invalidates its sessions.
2. `POST /api/auth/logout-all` for any account whose password you reset, or reset via the CLI:
   `python -m app.cli reset-password --username <name>`.
3. Read the audit log for what the account did.
4. Check for users you did not create and roles you did not grant.
5. Check the runtime settings against what you intended — registration, guest downloads,
   limits.

If you believe the host is compromised, rotating `SECRET_KEY` invalidates every session on the
instance at once. Users sign in again; nothing else is lost. That is the blunt instrument, and
it is available.

---

## Reporting

Vulnerabilities go through a **private advisory**, never a public issue. See
[SECURITY.md](../SECURITY.md) for what to include and what to expect.

Requests to add access-control circumvention — DRM, paywalls, private accounts, logins,
CAPTCHAs, age gates — are declined. That is not a security gap awaiting a fix; it is what the
project is. If you find code here that *does* defeat an access control, that is a bug worth
reporting.
