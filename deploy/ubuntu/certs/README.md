# Certificate directory (Ubuntu deployment)

The Docker overlay `docker-compose.ubuntu.yml` mounts this directory at
`/etc/nginx/certs` inside the nginx container. nginx expects exactly two files:

```
fullchain.pem
privkey.pem
```

Nothing here is committed — the directory exists so the bind mount resolves.

## Getting certificates

**Let's Encrypt on the host** is the usual route. Point `CERT_DIR` at the live
directory instead of copying, so renewals are picked up automatically:

```bash
sudo certbot certonly --standalone -d slipstream.example.com
echo "CERT_DIR=/etc/letsencrypt/live/slipstream.example.com" >> .env
```

The files there are symlinks into `../../archive/`, and Docker follows symlinks
only within the mount. Mount the parent instead if you hit a broken-link error:

```yaml
- /etc/letsencrypt:/etc/letsencrypt:ro
```

and adjust the certificate paths in the nginx template accordingly.

**Self-signed**, for testing only — browsers will warn, and the warning is
correct:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=slipstream.local"
```

## Renewal

A certificate that expires takes the whole site down, since the app is
HTTPS-only in this configuration. `scripts/ubuntu/deploy.sh` installs a deploy
hook that reloads nginx after each renewal; if you set this up by hand, add one
yourself. A renewed certificate that nginx has not reloaded is still the old
certificate.

Private keys belong here at mode 600 and must never be committed. See
`docs/UBUNTU.md`.
