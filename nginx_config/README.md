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
├── frontend/           <- Vite project; frontend/dist/ is the built output nginx serves
├── src/                <- FastAPI backend (src/helpers/backend.py)
├── data/, docs/        <- rest of the repo, along for the ride
├── requirements.txt
├── .env
└── .venv/              <- created fresh on the server, not copied from /mnt
```

There's no separate `backend/` subfolder - this mirrors the repo root
exactly (`src/`, `requirements.txt`, `.env` live at the top level, same as
in `tamuevent_mobile_backend/`).

Assumed OS: Debian/Ubuntu. Commands below use `apt`; substitute your
distro's package manager if different.

This guide assumes the project currently lives at `/mnt/TAMUevents` on the
server (backend source plus an already-built `frontend/dist/`) and walks
through moving it into `/var/www/tamuevent` - no `npm run build` on the
server needed, since `dist/` is already built.

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

## 1. Install Nginx, Certbot, and the Python runtime

Node/npm isn't needed on the server - `frontend/dist/` is already built and
just needs to be copied into place.

```bash
sudo apt update
sudo apt install -y nginx certbot python3 python3-venv postgresql-client rsync
```

## 2. Create the app user and target directories

```bash
sudo useradd --system --home /var/www/tamuevent --shell /usr/sbin/nologin tamuevent
sudo mkdir -p /var/www/tamuevent /var/www/certbot
```

## 3. Move the code from /mnt/TAMUevents into place

This is a one-time move on the server itself (`/mnt` and `/var` are
typically separate filesystems, so use `rsync` rather than `mv` - `mv`
across filesystems silently falls back to a slow copy+delete anyway, and
rsync gives you resumability and exclusions for free).

`/mnt/TAMUevents` mirrors the repo root directly - `src/`,
`requirements.txt`, `.env`, and `frontend/` all sit at the top level,
there's no `backend/` subfolder. One rsync brings it all across, excluding
the things that shouldn't move as-is:

```bash
sudo rsync -av \
  --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
  --exclude frontend/node_modules \
  /mnt/TAMUevents/ /var/www/tamuevent/
```

`frontend/dist/` (already built) and `.env` are both plain files under
that tree, so they come along automatically. Lock down `.env`'s
permissions and recreate the venv fresh at the new path - a venv's scripts
hardcode their own location (e.g. the `.venv/bin/uvicorn` shebang would
still point at `/mnt/TAMUevents/.venv`), so copying it verbatim breaks it:

```bash
sudo chmod 600 /var/www/tamuevent/.env

cd /var/www/tamuevent
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
```

If `frontend/dist/` was built with the dev default (`VITE_API_BASE_URL`
unset or pointing at `http://localhost:9191/api`), the deployed site will
try to call `localhost` from the visitor's browser and fail. Check what's
baked in:

```bash
grep -o 'localhost:9191[^"]*' /var/www/tamuevent/frontend/dist/assets/*.js
```

If that matches, the build needs to be redone with
`VITE_API_BASE_URL=/api npm run build` (on any machine with Node - your
laptop is fine) and the corrected `dist/` copied up instead, since Vite
bakes `VITE_*` values into the JS at build time, not at serve time.

**Ownership**, once everything is in place:

```bash
sudo chown -R tamuevent:tamuevent /var/www/tamuevent
```

(If this doesn't stick - files stay owned by whoever ran `rsync` - check
`mount | grep /var` and `mount | grep /mnt`: it usually means one side is a
filesystem, like NTFS via `ntfs-3g` or a network share, that doesn't support
per-file Unix ownership.)

Once you've confirmed the app works from `/var/www/tamuevent` (step 8
below), the `/mnt/TAMUevents` copy is redundant - remove it whenever you're
comfortable, there's no rush.

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

- Frontend change: rebuild locally (`VITE_API_BASE_URL=/api npm run
  build`), rsync the new `dist/` to `/var/www/tamuevent/frontend/dist/`
  (`--delete` so removed files don't linger), `sudo chown -R
  tamuevent:tamuevent /var/www/tamuevent/frontend/dist`. No Nginx/backend
  restart needed.
- Backend change: rsync the updated `src/` into `/var/www/tamuevent/src/`,
  then `sudo systemctl restart tamuevent-backend`.
- Nginx config change: edit the file in this repo, `scp`/rsync it to
  `/etc/nginx/sites-available/tamuevent.com.conf`, then
  `sudo nginx -t && sudo systemctl reload nginx`.
