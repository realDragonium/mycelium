# Deployment guide

End-to-end setup for running Mycelium on a fresh Linux VPS so Claude
Desktop and Claude Code can connect to it remotely.

Target: Ubuntu 22.04 / 24.04 or Debian 12. Smallest reasonable spec is
1 vCPU, 1 GB RAM, 20 GB disk (Ollama for embeddings can need more — see
the Ollama section below).

The end state:

```
   Internet ──HTTPS──> nginx (443) ──HTTP──> uvicorn (127.0.0.1:8765)
                         │                           │
                         └── Let's Encrypt cert      └── /var/lib/mycelium (SQLite + history + vectors)
```

---

## 1. Prerequisites you do once

- **A domain name** pointing at the VPS's public IP (an A record).
  Mycelium needs HTTPS — Claude Desktop refuses plaintext bearer auth
  in production, and Auth0 will refuse non-HTTPS callbacks. A subdomain
  like `mycelium.yourcompany.com` is fine.
- **An Auth0 account** (free tier is more than enough). See
  [AUTH0.md](AUTH0.md) for the application setup; you can do that
  in parallel.
- **SSH access to the VPS** as root (or a sudoer).

---

## 2. Bootstrap the server (run once, on the server)

SSH in, then run the bootstrap script. It installs nginx, certbot,
build tools, creates a `mycelium` system user, sets up directories,
drops a systemd unit and an nginx site template, and installs `uv`
for the service user.

```bash
ssh root@your-vps.example.com

# Pull the bootstrap script (or copy it via scp from your laptop)
curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/mycelium/main/deploy/install-server.sh \
    -o install-server.sh
sudo bash install-server.sh
```

If you don't want to fetch from GitHub, just `scp` the file:

```bash
scp deploy/install-server.sh root@your-vps:/root/
ssh root@your-vps "bash /root/install-server.sh"
```

After it finishes you'll see a "Next steps" summary. We'll walk through
those next.

---

## 3. Ship the code from your laptop

The first deploy uploads everything; subsequent deploys are incremental.

```bash
# from your local mycelium checkout
MYC_SSH_HOST=root@your-vps.example.com deploy/deploy.sh
```

This does three things:

1. `rsync`s the source tree to `/opt/mycelium` on the server (excluding
   `.git`, tests, the local `.mycelium` data dir, caches).
2. Runs `uv sync --frozen` on the server, which installs the exact
   dependency versions from `uv.lock` into a venv owned by the
   `mycelium` user.
3. Restarts the `mycelium` systemd service.

On the **first** deploy the service won't be enabled yet (we haven't
written the env file), so the restart step will silently fail. That's
fine — we'll start it for real at the end.

```bash
# First deploy only — skip the restart attempt
MYC_SSH_HOST=root@your-vps.example.com deploy/deploy.sh --skip-restart
```

---

## 4. Configure the environment

On the server, edit `/etc/mycelium.env`:

```bash
sudo nano /etc/mycelium.env
```

Minimum viable config for a hosted, auth-on deployment:

```ini
MYCELIUM_AUTH=on

# Generate with: openssl rand -base64 48
MYCELIUM_SESSION_SECRET=<paste the random string>

# From your Auth0 application — see AUTH0.md
MYCELIUM_OIDC_ISSUER=https://your-tenant.us.auth0.com
MYCELIUM_OIDC_CLIENT_ID=<from Auth0>
MYCELIUM_OIDC_CLIENT_SECRET=<from Auth0>
MYCELIUM_OIDC_REDIRECT_URI=https://mycelium.example.com/auth/callback

# First login matching this email becomes admin (one-shot, only when
# no admin exists yet). Set it to your own email.
MYCELIUM_BOOTSTRAP_ADMIN_EMAIL=you@example.com
```

The file is mode `0640`, owned `root:mycelium` — the service user can
read it but nobody else can.

> **Want to try it without Auth0 first?** Leave `MYCELIUM_AUTH=off`,
> leave the OIDC fields blank, skip step 6, and just expose the UI over
> HTTPS. Every caller will be `local-admin`. Useful for a single-user
> setup or a sanity check.

---

## 5. Set up nginx + TLS

Edit the site template — replace `mycelium.example.com` with your
actual domain in two places (`server_name` near the top):

```bash
sudo nano /etc/nginx/sites-available/mycelium
```

Enable the site and reload nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/mycelium /etc/nginx/sites-enabled/mycelium
sudo nginx -t
sudo systemctl reload nginx
```

Obtain a Let's Encrypt cert. Certbot will rewrite the nginx config to
add the SSL block automatically and set up a renewal timer:

```bash
sudo certbot --nginx -d mycelium.example.com
```

When asked whether to redirect HTTP to HTTPS, say **yes**.

Verify:

```bash
curl -I https://mycelium.example.com/
# Expect: HTTP/2 307 (the root redirects to /ui/)
```

---

## 6. Start the service

```bash
sudo systemctl enable --now mycelium
sudo systemctl status mycelium     # should be 'active (running)'
sudo journalctl -u mycelium -f     # tail logs to catch any startup errors
```

A healthy startup log looks like:

```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     StreamableHTTP session manager started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

---

## 7. First login (claim the admin role)

1. Open `https://mycelium.example.com/` in a browser.
2. The UI loads. Visiting any authenticated page kicks you to Auth0.
   You can also go straight to `https://mycelium.example.com/auth/login`.
3. Log in with the **same email** you put in
   `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL`.
4. You're now the admin. Visit **Settings** in the top nav — you should
   see the "Users & invites" admin section.

If you see a 403 "this account is not authorized — request an invite"
instead, double-check that:

- `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` matches the verified email in your
  Auth0 profile exactly (case-insensitive).
- No other admin exists in the database. The bootstrap only fires when
  there are zero admins. Run
  `sudo sqlite3 /var/lib/mycelium/main.db "SELECT email,role FROM users"`
  to inspect.

---

## 8. Connect your first MCP client

See the in-app guide at `https://mycelium.example.com/connect` (also
reachable from the **Connect** button in the top nav).

Short version:

1. Settings → MCP tokens → create a token named `laptop`.
2. Copy the secret immediately (shown once).
3. Run:

   ```bash
   claude mcp add --transport http mycelium https://mycelium.example.com/mcp \
     --header "Authorization: Bearer myc_..."
   ```

4. `claude mcp list` should show `mycelium` as connected.

---

## Subsequent deploys

Just run the deploy script again — the systemd service restarts
automatically:

```bash
MYC_SSH_HOST=root@your-vps.example.com deploy/deploy.sh
```

The data dir (`/var/lib/mycelium`) is excluded from the rsync, so
substrate state survives deploys cleanly. Migrations (`store.migrate()`)
run on startup so any schema additions are applied automatically.

---

## Backups

The substrate is a single SQLite file at `/var/lib/mycelium/main.db`
(plus `history.db` for the audit log). Back it up the way you back
up any small file:

```bash
# Take an online snapshot — SQLite handles concurrent reads safely.
sudo -u mycelium sqlite3 /var/lib/mycelium/main.db ".backup /tmp/mycelium-$(date +%F).db"
```

For a real backup story, copy that snapshot off the VPS on a cron
(rsync to S3, restic, borg — your call).

---

## Updating Ollama / embeddings

Mycelium's MVP defaults to `nomic-embed-text` via Ollama. If you're
embedding new content on this server, you'll also need Ollama running.

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
sudo -u mycelium ollama pull nomic-embed-text
```

Ollama needs ~2 GB RAM headroom on top of Mycelium itself, so size your
VPS accordingly. If you're only consuming pre-built indexes (read-only
hosting), you can skip Ollama entirely.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `503` from nginx | Service isn't running. `sudo systemctl status mycelium`, check journal. |
| `502` from nginx | Service is up but uvicorn isn't bound to `127.0.0.1:8765`. Confirm `MYCELIUM_HTTP_HOST/PORT` in the systemd unit aren't being overridden by the env file. |
| `403` on every login | `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` doesn't match, or the database already has an admin. Inspect with sqlite3. |
| MCP `/mcp` 401 with a token | Token might be revoked or the user suspended. Check via the Settings UI. |
| MCP `/mcp` hangs | nginx is buffering. Confirm `proxy_buffering off` is in the `/mcp` location block. |
| Auth0 callback "redirect URI mismatch" | The URL in Auth0's allowed callbacks must be an exact match for `MYCELIUM_OIDC_REDIRECT_URI`, scheme included. |

Logs:

```bash
sudo journalctl -u mycelium -n 200 --no-pager
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```
