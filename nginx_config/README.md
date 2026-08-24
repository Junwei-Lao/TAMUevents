# Deploying tamuevent.com

This folder holds everything needed to serve the React frontend and FastAPI
backend from one server behind Nginx, with free HTTPS via Let's Encrypt.

Files:

- `tamuevent.com.bootstrap.conf` - temporary HTTP-only Nginx config, used
  once to obtain the first certificate.
- `tamuevent.com.conf` - the real Nginx config (HTTP->HTTPS redirect,
  static frontend, `/api/` reverse proxy to the backend).
- `tamuevent-backend.service` - systemd unit that runs the FastAPI backend
  under uvicorn.
- `cloudflare-realip.conf` / `update-cloudflare-ips.sh` - optional: makes
  Nginx logs/rate-limits see the real visitor IP instead of Cloudflare's.

Assumed deploy layout on the server (adjust paths in the configs above if
you use different ones):

```
/var/www/tamuevent/
├── frontend/dist/     <- `npm run build` output
└── backend/           <- src/, requirements.txt, .venv/, .env
```

Assumed OS: Debian/Ubuntu. Commands below use `apt`; substitute your
distro's package manager if different.

---

## 0. Before you start - Cloudflare SSL mode

In the Cloudflare dashboard, set **SSL/TLS -> Overview** to **Full (strict)**.
Once Let's Encrypt is issuing you a real, valid certificate (below), this is
the correct mode - it encrypts Cloudflare<->origin too and avoids redirect
loops. Don't use "Flexible" (Cloudflare talks plain HTTP to your server,
which fights with the HTTPS redirect in `tamuevent.com.conf`).

Whether the DNS record is proxied (orange cloud) or DNS-only (grey cloud)
both work with the steps below; proxied is the normal choice since you're
already using Cloudflare.

## 1. Install Nginx, Certbot, and app runtimes

```bash
sudo apt update
sudo apt install -y nginx certbot python3 python3-venv postgresql-client curl

# Node.js (build the frontend on the server) - or build locally and scp
# the dist/ folder up instead, if you'd rather not install Node on the box.
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## 2. Create the app user and directories

```bash
sudo useradd --system --home /var/www/tamuevent --shell /usr/sbin/nologin tamuevent
sudo mkdir -p /var/www/tamuevent/frontend /var/www/tamuevent/backend /var/www/certbot
sudo chown -R tamuevent:tamuevent /var/www/tamuevent
```

## 3. Deploy the code

From your machine (or directly on the server via `git clone`):

```bash
# Backend: copy the whole repo minus node_modules/dist, e.g.
rsync -av --exclude node_modules --exclude frontend/dist ./ user@server:/tmp/tamuevent-src/
ssh user@server "sudo rsync -av --exclude node_modules --exclude frontend/dist /tmp/tamuevent-src/ /var/www/tamuevent/backend/"
```

Then on the server:

```bash
cd /var/www/tamuevent/backend
sudo -u tamuevent python3 -m venv .venv
sudo -u tamuevent .venv/bin/pip install -r requirements.txt

# Copy your local .env (DEEPSEEK_API_KEY, db_username, db_password) up
# separately - it's gitignored on purpose, don't put secrets through git.
```

Copy `.env` up with `scp` (not through the rsync above, and never through
git):

```bash
scp .env user@server:/tmp/tamuevent.env
ssh user@server "sudo mv /tmp/tamuevent.env /var/www/tamuevent/backend/.env && \
  sudo chown tamuevent:tamuevent /var/www/tamuevent/backend/.env && \
  sudo chmod 600 /var/www/tamuevent/backend/.env"
```

Build the frontend for production. It needs `VITE_API_BASE_URL=/api`
(same-origin, since Nginx proxies `/api/` on this domain) rather than the
`http://localhost:9191/api` in your local `frontend/.env`, which is dev-only:

```bash
cd frontend
VITE_API_BASE_URL=/api npm ci
VITE_API_BASE_URL=/api npm run build
```

Then deploy the output:

```bash
rsync -av dist/ user@server:/tmp/tamuevent-dist/
ssh user@server "sudo rsync -av --delete /tmp/tamuevent-dist/ /var/www/tamuevent/frontend/dist/ && \
  sudo chown -R tamuevent:tamuevent /var/www/tamuevent/frontend/dist"
```

## 4. Get the Let's Encrypt certificate

Nginx can't load `tamuevent.com.conf` yet - it references a certificate
that doesn't exist. Start with the bootstrap config instead:

```bash
sudo cp nginx_config/tamuevent.com.bootstrap.conf /etc/nginx/sites-available/tamuevent.com.conf
sudo ln -s /etc/nginx/sites-available/tamuevent.com.conf /etc/nginx/sites-enabled/tamuevent.com.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Confirm `http://tamuevent.com` loads (plain text bootstrap message) before
continuing - that proves DNS + port 80 are actually reachable.

```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot \
  -d tamuevent.com -d www.tamuevent.com
```

Now swap in the real config:

```bash
sudo cp nginx_config/tamuevent.com.conf /etc/nginx/sites-available/tamuevent.com.conf
sudo nginx -t && sudo systemctl reload nginx
```

Certbot's systemd timer (`certbot.timer`, installed automatically by the
package) handles renewal. Add a reload hook so Nginx picks up renewed
certs:

```bash
echo 'systemctl reload nginx' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
sudo certbot renew --dry-run   # sanity check
```

## 5. Start the backend

```bash
sudo cp nginx_config/tamuevent-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tamuevent-backend
sudo systemctl status tamuevent-backend   # should be "active (running)"
curl -s -X POST http://127.0.0.1:9191/api/events/search \
  -H 'Content-Type: application/json' \
  -d '{"start_date":"2026-01-01","end_date":"2026-12-31"}'   # sanity check
```

If the DB isn't reachable from this box yet, fix that first (`postgre_io.py`
reads connection info from the same `.env`) - `journalctl -u
tamuevent-backend -f` shows the error.

## 6. (Optional) Restore real visitor IPs behind Cloudflare

```bash
chmod +x nginx_config/update-cloudflare-ips.sh
sudo nginx_config/update-cloudflare-ips.sh
sudo cp nginx_config/cloudflare-realip.conf /etc/nginx/cloudflare-realip.conf
```

Then uncomment the `include /etc/nginx/cloudflare-realip.conf;` line near
the top of `/etc/nginx/sites-available/tamuevent.com.conf` and
`sudo nginx -t && sudo systemctl reload nginx`. Re-run the update script
monthly (cron) since Cloudflare's ranges change occasionally.

## 7. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # 80 + 443
sudo ufw enable
```

## 8. Verify

- `https://tamuevent.com` loads the frontend over a valid cert (padlock,
  no warnings).
- Searching in the UI hits `/api/events/search` (check the Network tab)
  and gets results back - proves the Nginx proxy -> uvicorn -> Postgres
  path all works end to end.
- `sudo systemctl status tamuevent-backend nginx` both show active.

## Redeploying later

- Frontend change: rebuild (`VITE_API_BASE_URL=/api npm run build`), rsync
  `dist/` up again, no Nginx/backend restart needed.
- Backend change: rsync the updated `src/`, then
  `sudo systemctl restart tamuevent-backend`.
- Nginx config change: edit the file in this repo, `scp`/rsync it to
  `/etc/nginx/sites-available/tamuevent.com.conf`, then
  `sudo nginx -t && sudo systemctl reload nginx`.
