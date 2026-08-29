# Certificate directory (Oracle Cloud deployment)

`docker-compose.oracle.yml` mounts this directory at `/etc/nginx/certs` inside
the nginx container, which expects:

```
fullchain.pem
privkey.pem
```

Nothing here is committed — the directory exists so the bind mount resolves.

## Before requesting a certificate

On Oracle Cloud the http-01 challenge fails unless **both** firewall layers
allow port 80:

1. **VCN security list** — Console → Networking → Virtual Cloud Networks → your
   VCN → Subnet → Security List → Add Ingress Rules. Source `0.0.0.0/0`,
   protocol TCP, destination ports 80 and 443.
2. **The instance's own iptables** — Oracle Linux images ship rules that reject
   everything except SSH, and they persist across reboots.
   `scripts/oracle/deploy.sh` opens them; by hand it is
   `sudo iptables -I INPUT 5 -p tcp --dport 80 -m state --state NEW -j ACCEPT`
   followed by `sudo iptables-save > /etc/iptables/rules.v4`.

Opening only the VCN is the single most common reason a deployment here appears
to hang. Full walkthrough in `docs/ORACLE.md`.

## Getting certificates

```bash
sudo certbot certonly --standalone -d slipstream.example.com
echo "CERT_DIR=/etc/letsencrypt/live/slipstream.example.com" >> .env
```

## Renewal

Oracle Linux's certbot package does not include a renewal timer, unlike
Debian's. `scripts/oracle/deploy.sh` creates `certbot-renew.timer` with an nginx
reload hook. Check it is running:

```bash
systemctl list-timers 'certbot*'
```

A renewed certificate that nginx has not reloaded is still the old certificate.

Private keys belong here at mode 600 and must never be committed.
