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

This does four things:

1. `rsync`s the source tree to a staging dir on the server (excluding
   `.git`, tests, the local `.mycelium` data dir, caches).
2. Stops the service and snapshots the data dir — see
   [Deploy snapshots](#deploy-snapshots). If the snapshot fails, the deploy
   stops here and the running build is started again.
3. Installs the build into `/opt/mycelium` and runs `uv sync --frozen`,
   which installs the exact dependency versions from `uv.lock` into a venv
   owned by the `mycelium` user. If this fails, the previous build's code is
   put back from the snapshot and started, and the deploy exits non-zero.
4. Starts the `mycelium` systemd service and checks it is still running a
   few seconds later, so a migration that refuses at startup fails the
   deploy.

On the **first** deploy there is no env file and no data yet, so skip the
restart — we'll start the service for real at the end:

```bash
# First deploy only
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
  `sudo -u mycelium sqlite3 /var/lib/mycelium/mycelium-auth.db "SELECT email,role FROM users"`
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

### Protocol revisions at `/mcp`

The one `/mcp` endpoint answers both MCP revisions, and which one a client
speaks is its choice, not a server setting:

- **2026-07-28** — one self-describing POST per call. No `initialize`
  handshake and no `Mcp-Session-Id`, so nothing pins a client to a
  particular worker: these requests survive a plain round-robin load
  balancer with no session affinity.
- **2025-era** — the `initialize` handshake, with an `Mcp-Session-Id`
  echoed on later requests. Sessions live in the serving process, so a
  deployment running more than one replica still needs affinity for
  these clients.

A 2026-07-28 request is routed by its `MCP-Protocol-Version` header and
carries `Mcp-Method` (plus `Mcp-Name` for tool calls), which must agree
with the body. nginx forwards hyphenated headers untouched, so the site
template needs no change — but a proxy that filters request headers must
pass all three through, or modern clients land on the legacy path and fail
for want of a session id.

Request bodies are capped at 4 MiB by the MCP transport. nginx's own
`client_max_body_size` default of 1 MiB is the tighter limit and bites
first; raise it in the site template if large `ingest` payloads get a 413.

### Set `MYCELIUM_PUBLIC_URL` if OAuth is in use

This is the deployment's OAuth issuer and its resource identifier, and
both have to be one stable string: a client records the issuer during
discovery and then compares it byte-for-byte against the `iss` on every
authorization response.

Unset, it is derived from each request's `Host` header. That works while
there is exactly one hostname, and breaks the moment there are two — a
client that discovered `https://mycelium.example.com` and later reaches
an alias sees a different `iss` and rejects the response, correctly.

```
MYCELIUM_PUBLIC_URL=https://mycelium.example.com
```

Scheme included, no trailing slash.

### Outbound requests from the OAuth endpoints

A client may identify itself with a Client ID Metadata Document — an HTTPS
URL it hosts — instead of registering. Resolving one means Mycelium makes an
outbound HTTPS request to a URL chosen by the caller, so an egress-filtered
deployment needs to allow that, and an operator should know it happens.

The fetch is fenced: HTTPS only, redirects not followed, a 5s timeout, a
64 KiB cap, and every address the hostname resolves to must be on the public
internet. Documents are cached per process, honouring `Cache-Control` within
a 1-minute to 1-hour bound.

Registration (`/register`) still works for clients that predate the
mechanism; it is deprecated upstream, not removed.

---

## Subsequent deploys

Just run the deploy script again:

```bash
MYC_SSH_HOST=root@your-vps.example.com deploy/deploy.sh
```

The data dir (`/var/lib/mycelium`) is never shipped or overwritten.
Schema migrations run when the new build starts, after the deploy has
snapshotted the data. A start also brings untouched seeded AI instructions
up to the new build's defaults — see
[Startup changes that are not migrations](#startup-changes-that-are-not-migrations).

---

## Data and backups

Everything an instance knows lives in `/var/lib/mycelium`:

| File | Holds |
|---|---|
| `mycelium.db` | Knowledge: statements, entities, names, links and conditions, vocabularies, knowledge gaps |
| `mycelium-history.db` | Audit log of substrate changes |
| `mycelium-auth.db` | Users, MCP tokens, invites, OAuth clients |
| `mycelium-drafts.db` | Drafts and their reviews, research and documentation runs, generated documents |
| `mycelium-prompts.db` | AI instructions and their history, model, review and product settings, GitHub connections |
| `mycelium-ops.db` | Only on instances that predate its removal: tool-call telemetry that is no longer written or read, and not archived |
| `mycelium.vec`, `mycelium-names.vec` | Vector indexes; rebuilt by re-embedding if missing |
| `entity-positions.json` | Entity layout cache; rebuilt if missing |
| `.uv-cache/` | uv's package cache, not data |

The databases run in WAL mode, so copying a live `.db` file can produce a
torn copy. Use one of the two methods below.

### Backups: `mycelium export`

`mycelium export` writes one archive holding every database above, the
audit log and the vector indexes. Run it as the service user; it is safe
while the service runs and reads each database as one consistent snapshot.

```bash
# once: the CLI wrapper and somewhere the service user may write
sudo install -m 0755 /opt/mycelium/deploy/myc /usr/local/bin/myc
sudo install -d -o mycelium -g mycelium -m 0700 /var/lib/mycelium-backups

sudo myc export /var/lib/mycelium-backups/mycelium-$(date -u +%F).tar.gz
```

It prints a row count per table. Copy archives off the VPS on a schedule,
for example from root's crontab:

```cron
0 3 * * * /usr/local/bin/myc export /var/lib/mycelium-backups/mycelium-$(date -u +\%F).tar.gz && find /var/lib/mycelium-backups -name '*.tar.gz' -mtime +14 -delete
```

followed by your off-site copy (rsync to S3, restic, borg — your call).

The archive is written owner-only and must be treated like the data dir:
it holds token hashes, invite links and all knowledge. It deliberately
leaves out OAuth authorization codes and consent screens (they expire
within minutes), tool-call telemetry, and two internal bookkeeping tables;
`UNARCHIVED_TABLES` in `src/mycelium/backup.py` lists them with reasons.
It also does not hold anything outside the data dir: back up
`/etc/mycelium.env` (session secret, OIDC and GitHub App secrets), the
GitHub App private key, and your nginx and systemd edits separately.

To check a backup, restore it into a scratch directory and compare the
row counts it prints with the ones `export` printed:

```bash
sudo -u mycelium /opt/mycelium/.local/bin/uv --project /opt/mycelium run \
  mycelium --data-dir /tmp/restore-check import /var/lib/mycelium-backups/<archive>
sudo rm -rf /tmp/restore-check
```

### Deploy snapshots

Every deploy that restarts the service first stops it and copies the data
dir (without `.uv-cache`) to `/var/lib/mycelium-snapshots/<UTC time>/data/`,
checks every database in it, keeps the previous build's code (without its
venv) in `app/` beside it, and records the build that wrote the data in
`/var/lib/mycelium-snapshots/<UTC time>/BUILD`. The newest five are kept
(`MYC_KEEP_SNAPSHOTS`). Each is a full copy, so leave room for five data
dirs on the disk.

A snapshot is an exact copy of the files the previous build last wrote,
for [Rolling back a deploy](#rolling-back-a-deploy). It lives on the same
disk as the data, so it is not a backup.

---

## Moving to a fresh instance (export → import)

Use this to move hosts, or when a change is too awkward to migrate in
place: export with the current build, then import with the new build into
an empty data dir. An archive imports into the build that wrote it or any
newer build; an older build refuses it.

1. Stop writes so nothing is lost between export and switch-over, then
   export:

   ```bash
   sudo systemctl stop mycelium
   sudo myc export /var/lib/mycelium-backups/move.tar.gz
   ```

2. On the new host, bootstrap and deploy as in sections 2–3 (with
   `--skip-restart`), install `myc` and `/var/lib/mycelium-backups` as in
   [Backups](#backups-mycelium-export), and copy over `/etc/mycelium.env`.
   Keeping `MYCELIUM_SESSION_SECRET` keeps browser sessions valid; MCP
   tokens are in the archive either way.
3. Copy the archive into `/var/lib/mycelium-backups/` on the new host,
   owned by `mycelium` and mode `0600`, so the service user can read it.
4. Import into the empty data dir. Import refuses a dir that already holds
   an instance; move such a dir aside rather than passing `--force`, whose
   safety export is written beside the data dir in `/var/lib`, where the
   service user cannot write.

   ```bash
   sudo myc import /var/lib/mycelium-backups/move.tar.gz
   ```

5. Start the service. If the archive was exported with `--no-vectors`, or
   import reported that an index disagrees with the archived data (a write
   landed while a live export copied the index), the first start re-embeds
   every statement or name, which needs Ollama with the same embedding
   model and takes time proportional to the knowledge base.

   ```bash
   sudo systemctl start mycelium
   sudo journalctl -u mycelium -n 50 --no-pager
   ```

6. Compare the row counts `import` printed with those `export` printed,
   sign in, and run a search you know the answer to.

GitHub App connections come back disabled; re-enable them under
**Settings**. OAuth clients mid-authorization must start again.

---

## Rolling back a deploy

When a deploy has started a new build and you need the previous one back:

**If the substrate schema did not change**, deploy the previous build
like any other — check it out and run `deploy/deploy.sh`. It snapshots
first, as always. Whether the schema changed is visible in the startup
log, and in `sudo -u mycelium sqlite3 /var/lib/mycelium/mycelium.db
'PRAGMA user_version'` compared with the version the previous build
expects.

**If a migration ran**, the previous build will not start on the migrated
data: it stops with `database schema version N is newer than this build's
latest known version M`. That refusal is deliberate — there is no schema
downgrade. Restore the snapshot the deploy took, then start the previous
build:

1. Find the snapshot. The newest one is from the deploy you are undoing;
   its `BUILD` file names the build that wrote the data (`unknown` when
   that build predates build recording — use your deploy history).

   ```bash
   sudo ls /var/lib/mycelium-snapshots/
   sudo cat /var/lib/mycelium-snapshots/<time>/BUILD
   ```

2. If anything written since the deploy matters, export it now with the
   new build (`sudo myc export /var/lib/mycelium-backups/after-deploy.tar.gz`).
   The previous build cannot import that archive; keep it to recover those
   records by hand or to re-import once the new build is fixed.
3. Stop the service and set the current data aside. The `failed-` name
   keeps it out of snapshot pruning.

   ```bash
   sudo systemctl stop mycelium
   sudo rsync -a --exclude=.uv-cache/ /var/lib/mycelium/ \
     /var/lib/mycelium-snapshots/failed-$(date -u +%Y%m%dT%H%M%SZ)/
   ```

4. Restore the snapshot over the data dir. `--delete` removes files the
   new build created; the uv cache stays.

   ```bash
   sudo rsync -a --delete --exclude=.uv-cache/ \
     /var/lib/mycelium-snapshots/<time>/data/ /var/lib/mycelium/
   sudo chown -R mycelium:mycelium /var/lib/mycelium
   ```

5. From your laptop, deploy the build named in `BUILD` without restarting
   (a normal deploy would snapshot again and could prune the snapshot you
   just used), then start it on the server:

   ```bash
   git checkout <build>
   MYC_SSH_HOST=root@your-vps.example.com deploy/deploy.sh --skip-restart
   ```

   ```bash
   sudo systemctl start mycelium
   sudo journalctl -u mycelium -n 50 --no-pager
   ```

**What comes back:** everything in the data dir as it was when the
previous build stopped — knowledge, history, users and tokens, drafts,
documents, AI instructions and settings, vector indexes.

**What does not:** anything written after the deploy — knowledge, drafts,
prompt edits, users, and tokens minted since (those tokens stop working;
OAuth clients sign in again). Changes outside the data dir —
`/etc/mycelium.env`, nginx, the systemd unit — are not in snapshots; undo
them by hand. Snapshots older than the newest five are gone, so keep
off-box exports for anything further back.

A migration that fails partway leaves the database at the last version
that completed, not the one it started from, so restoring the snapshot is
also the way back from a failed migration.

### Startup changes that are not migrations

Each start also updates AI instructions (see
[AI prompts](AI_PROMPTS.md#when-a-release-changes-a-default)): Ingestion,
Research and Document generation instructions still authored by `seed` get
the new build's default appended as a new version, and saved instructions
that predate a newer default are logged as a warning. The first start of a
build with this behaviour also creates `shipped_prompt_texts` in
`mycelium-prompts.db` and records the defaults it saw.

Restoring a snapshot undoes these with everything else. A code-only
rollback does not: the previous build serves the appended versions and
ignores the new table. To return to the earlier wording, restore it from
**Version history** in **AI settings → Prompts**.

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
| Service stops right after a deploy with `database schema version N is newer than this build's latest known version M` | An older build is running on migrated data. See [Rolling back a deploy](#rolling-back-a-deploy). |
| Deploy aborts with `snapshot failed` | A database in `/var/lib/mycelium` failed its check, or the disk is full. The running build was restarted unchanged; read the message above it. |
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
