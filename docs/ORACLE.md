# Oracle Cloud (Always Free, ARM64)

Deploying to an Oracle Cloud Ampere A1 instance. The free tier gives you 4 OCPU and 24 GB
of RAM permanently, which is far more machine than this app needs — the constraints are
elsewhere.

Read this rather than [UBUNTU.md](UBUNTU.md). Oracle Linux differs in three ways that break
a naive deployment, and one step cannot be scripted at all.

---

## The three divergences

**1. Two firewall layers, and both block by default.** The instance ships an iptables
ruleset that REJECTs everything except SSH, saved to `/etc/iptables/rules.v4` so it survives
reboots. Separately, the VCN security list in Oracle's console blocks inbound traffic. Both
must allow 80 and 443. Opening only one leaves you debugging a connection that times out
with no log entry anywhere, because the packet never arrives.

**2. SELinux is enforcing.** `httpd_can_network_connect` must be on or nginx cannot open a
socket to the app. Every request returns 502, and the reason appears in the SELinux audit log
— never in the nginx error log. This is the single most confusing failure on this platform.

**3. ffmpeg is not in the base repositories.** It comes from RPM Fusion, which needs EPEL
first.

The deploy script handles all three. The VCN security list is the one that cannot be
scripted from inside the instance — you have to do it in the web console.

---

## Creating the instance

In the Oracle Cloud console:

1. **Compute → Instances → Create instance**
2. **Shape**: change it. The default is AMD micro. Pick **Ampere** → `VM.Standard.A1.Flex`,
   then **4 OCPU / 24 GB**. That is the whole free ARM allocation; using less does not save
   you anything.
3. **Image**: Oracle Linux 9, or Ubuntu 22.04 if you would rather use the Ubuntu path. This
   guide assumes Oracle Linux.
4. **Boot volume**: 50 GB is the free maximum. Take all of it.
5. **SSH keys**: upload your public key. Save the private key.
6. Create, and note the public IP.

Capacity for A1 shapes is often exhausted in popular regions. "Out of host capacity" means
try again later or pick another availability domain — it is not a configuration error and
retrying does eventually work.

### The VCN security list — do this before deploying

**Networking → Virtual Cloud Networks → your VCN → Subnets → your subnet → Security Lists →
Default Security List → Add Ingress Rules**

Two rules:

| Source CIDR | Protocol | Destination port |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

Leave "Stateless" unchecked.

This is the step everyone forgets. The deploy script cannot do it — it runs inside the
instance and this is account-level cloud configuration. Skip it and certbot fails the http-01
challenge with a timeout that looks like a DNS problem.

### DNS

Point an A record at the instance's public IP and let it propagate:

```bash
dig +short your-domain.com     # must equal the instance IP
```

---

## Deploying

```bash
ssh opc@<instance-ip>
sudo dnf update -y

git clone <url> slipstream && cd slipstream
sudo scripts/oracle/deploy.sh --domain your-domain.com --email you@example.com
```

Fifteen to twenty-five minutes — slower than x86 because some Python wheels are compiled
from source on aarch64.

In order, it:

1. Installs base packages, EPEL, and RPM Fusion for ffmpeg.
2. Opens 80 and 443 in firewalld if present, and in iptables regardless.
3. Persists the iptables rules to `/etc/iptables/rules.v4`.
4. Sets `httpd_can_network_connect` and labels the ACME webroot for SELinux.
5. Runs `scripts/linux/install.sh` with `BIND_HOST=127.0.0.1`.
6. Installs nginx and certbot, with an EPEL fallback if certbot is not in the enabled repos.
7. Writes a temporary ACME server block, obtains the certificate, removes the block.
8. Installs `00-slipstream-limits.conf` and `10-slipstream.conf`.
9. `nginx -t`, then reload.
10. Creates a `certbot-renew.timer` if the packaged certbot has none.
11. Tunes `.env` for the free tier.
12. Waits for health, runs `verify`, prints the credentials.

### The iptables detail

New ACCEPT rules are **inserted at position 5**, not appended:

```bash
iptables -I INPUT 5 -p tcp --dport 80 -m state --state NEW -j ACCEPT
```

Oracle's ruleset ends with a blanket REJECT. Appending puts your ACCEPT after it, where it
never matches, and the port stays closed while `iptables -L` appears to show it open. This is
a genuinely confusing failure mode and it is why the position is explicit.

Rules are saved so they survive a reboot. If the script cannot persist them it says so and
gives you the command.

### The SELinux detail

```bash
sudo setsebool -P httpd_can_network_connect 1
```

Without it: 502 on every request, nothing useful in the nginx log, and an audit denial you
will only find if you know to look.

```bash
sudo getsebool httpd_can_network_connect          # should be "on"
sudo ausearch -m avc -ts recent                   # denials, if any
```

---

## Free-tier tuning

The script sets:

```ini
MAX_CONCURRENT_DOWNLOADS=2
TEMP_FILE_TTL=3600
```

Not because the CPU cannot cope — 4 Ampere cores handle more than that — but because the
**boot volume is 50 GB total** and shared with the OS, and `data/temp/` is the only directory
that grows. Its ceiling is roughly concurrency × max file size, plus whatever finished files
are still inside their TTL. A full disk takes the database down with it, and SQLite failing
to write is a harder outage to recover from than a slow queue.

Raise concurrency if you monitor disk usage:

```bash
df -h /
du -sh /opt/slipstream/data/temp
```

The Docker overlay applies the same reasoning: `MAX_FILE_SIZE` capped at 2 GiB,
`TEMP_FILE_TTL` at one hour, `CPU_LIMIT` 1.5, `MEMORY_LIMIT` 3g, and tmpfs `/tmp` at 512 MiB
rather than the base file's 1 GiB — tmpfs *is* RAM, and there is no reason to let scratch
files claim a gigabyte of it.

---

## ARM64 notes

Everything here is arm64-native. Two consequences:

**Some Python wheels compile from source.** `argon2-cffi` in particular has fewer prebuilt
aarch64 wheels, which is why the Docker `deps` stage installs `build-essential` and
`libffi-dev`. It makes the first install slower, not harder.

**Container images must be arm64.** `docker-compose.oracle.yml` sets
`platforms: [linux/arm64]`. An amd64 image either refuses to start or runs under emulation at
a fraction of the speed. Build with:

```bash
PLATFORMS=linux/arm64 ./docker/build.sh
```

Building arm64 on an x86 machine goes through QEMU and is slow. Building on the Oracle
instance itself is native and faster despite the smaller machine.

---

## After deploying

```bash
curl https://your-domain.com/api/health
curl -o /dev/null -w '%{http_code}\n' https://your-domain.com/api/admin/stats   # 401 or 403
curl -sI https://your-domain.com/ | grep -iE 'strict-transport|content-security'
```

Then sign in, change the admin password, and complete one real download. Admin mutations stay
locked until the password is changed.

Verify the platform-specific pieces too:

```bash
sudo getsebool httpd_can_network_connect     # on
sudo iptables -L INPUT -n | grep -E ':80|:443'
sudo systemctl list-timers | grep certbot
ffmpeg -version | head -1
```

Set up backups ([BACKUPS.md](BACKUPS.md)) and read the hardening checklist in
[SECURITY.md](../SECURITY.md).

---

## Operations

Same as any systemd install:

```bash
sudo systemctl status slipstream
sudo journalctl -u slipstream -f
sudo scripts/linux/backup.sh
sudo scripts/linux/update.sh --ytdlp-only
```

`dnf` instead of `apt` for system packages. Otherwise identical to [UBUNTU.md](UBUNTU.md).

### Certificate renewal

Oracle Linux's certbot package ships **no timer**, unlike Debian's. The deploy script creates
`certbot-renew.timer` when it finds none. Confirm it exists:

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

Without a timer the certificate silently expires in 90 days.

The renewal hook must reload nginx. A renewed certificate that nginx has not reloaded is
still the old certificate — renewal succeeds, the site keeps serving the expiring cert, and
nothing looks wrong until it does not work.

---

## Troubleshooting

**Connection times out, nothing in any log.** The VCN security list. The packet is dropped
before it reaches the instance, so there is nothing to log. Check the console:
Networking → VCN → Subnets → Security Lists → ingress rules for 80 and 443.

**502 on every request.** SELinux, almost certainly.

```bash
sudo getsebool httpd_can_network_connect     # must be "on"
sudo setsebool -P httpd_can_network_connect 1
sudo ausearch -m avc -ts recent
```

**Port shows as open in `iptables -L` but nothing connects.** The ACCEPT rule is after the
blanket REJECT. Check the ordering:

```bash
sudo iptables -L INPUT -n --line-numbers
```

Your rule must appear above the REJECT line. Reinsert it with `-I INPUT 5`.

**Ports closed again after a reboot.** The rules were not persisted.

```bash
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

**certbot fails.** In order of likelihood: the VCN security list, then iptables, then DNS.

```bash
curl -I http://your-domain.com/.well-known/acme-challenge/test   # from elsewhere
dig +short your-domain.com
```

**"Out of host capacity" when creating the instance.** Oracle has no free ARM capacity in
that availability domain right now. Try another AD, another region, or later. Not a
configuration error.

**ffmpeg not found after install.** RPM Fusion did not get enabled.

```bash
sudo dnf install -y epel-release
sudo dnf install -y --nogpgcheck \
  https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-9.noarch.rpm
sudo dnf install -y ffmpeg ffmpeg-devel
```

**Instance was reclaimed.** Oracle reclaims idle Always-Free instances. A running web server
with a health check normally counts as active, but read the current policy — it changes, and
this is Oracle's decision, not something the app controls.

More in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Docker instead

```bash
cp .env.example .env
# SECRET_KEY, DOMAIN, APP_URL, COOKIE_SECURE=true
docker compose -f docker-compose.yml -f docker-compose.oracle.yml up -d
```

You still have to do the platform work yourself: VCN rules, iptables, and — because the nginx
container talks to the app container over a Docker network rather than through the host —
SELinux for the container runtime.

Certificates go where `CERT_DIR` points, default `./deploy/oracle/certs`. See
`deploy/oracle/certs/README.md`, and note that `/etc/letsencrypt/live/<domain>/` holds
symlinks into `../../archive/`; mounting just `live` gives the container dangling links.
