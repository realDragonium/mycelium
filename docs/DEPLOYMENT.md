# Deployment guide

> **Which deployment this describes.** This guide covers the self-hosted VPS
> path: `deploy/deploy.sh`, systemd and nginx on one Linux server. The live
> production instance does not run this way. It runs as a container on AWS ECS
> Fargate, with Litestream replicating its SQLite databases to S3, and is
> deployed by CDK from a separate private repository. The commands below, the
> service and file paths, and the deploy-snapshot and rollback procedures apply
> only to a VPS install. What holds for every deployment: the environment
> variables, the data files, `mycelium export` / `mycelium import`, and the
> fact that schema migrations run on startup.

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

### Less common settings

None of these are needed for a normal deployment. Model choice, limits,
concurrency and draft review are not environment settings; they live in AI
settings (see [AI model configuration](AI_MODELS.md)).

| Variable | Default | Effect |
| --- | --- | --- |
| `MYCELIUM_ALLOWED_EMAIL_DOMAINS` | unset (any domain) | Comma-separated email domains. When set, only people whose email is in one of them can log in or use a session or token; invites to other domains are refused. Exact match, no subdomains; service accounts are exempt. See [Restricting access to your email domains](USERS.md#restricting-access-to-your-email-domains). |
| `MYCELIUM_JIT_DOMAINS` | unset (invite-only) | Comma-separated email domains. A login whose email is in one of them gets an account without an invite. With `MYCELIUM_ALLOWED_EMAIL_DOMAINS` set, each must also be allowed or the server refuses to start. |
| `MYCELIUM_JIT_DEFAULT_ROLE` | `reader` | Role those users receive. The retired `asker` is read as `reader`, with a deprecation warning; any other unknown role disables just-in-time provisioning. |
| `EMBED_TIMEOUT_S` | `30` | Seconds before one embedding request fails instead of hanging. A failed request is retried twice with backoff. |
| `MYCELIUM_SLOW_REQUEST_MS` | `2000` | A request or background job that takes at least this long, fails, or whose client leaves before the response ends logs one `MYCELIUM_SLOW_REQUEST` line with its route and where the time went. The `503`s answered while the server is starting are not logged. |
| `MYCELIUM_TRACE_ENABLED` | off | Start with profiling traces on; otherwise they are switched on and off at runtime through `/api/tracing`. |
| `MYCELIUM_TRACE_DIR` | `<data dir>/traces` | Where profiling flamegraphs and metadata sidecars are written. |
| `MYCELIUM_{ASK,INGEST,DOCGEN}_TRACE_LOG` | unset; Ask and Ingest use `<data dir>/ask_trace.jsonl` and `ingest_trace.jsonl` | JSONL file that receives one record per run. The connect pass always writes to `<data dir>/connect_trace.jsonl`. |
| `MYCELIUM_TRACE_LOG_MAX_BYTES` | `10000000` (10 MB) | Rotate JSONL trace logs before exceeding this size; keep one older generation. `0` disables rotation. |
| `MYCELIUM_TRACE_KEEP` | `200` | Keep this many newest traces per directory by mtime; a flamegraph and sidecar count as one. `0` disables pruning. |
| `MYCELIUM_{INGEST,DOCGEN}_DOCTRINE_PATH` | the packaged file | Instruction file used when no edited instructions are saved in [AI prompts](AI_PROMPTS.md). |
| `MYCELIUM_OAUTH_ACCESS_TOKEN_TTL_SECONDS` | `3600` | Lifetime of an access token issued through the OAuth flow. See [OAuth token lifetime](#oauth-token-lifetime). |
| `MYCELIUM_DISABLE_MCP_HTTP` | unset | `1` serves HTTP without the `/mcp` endpoint. |
| `MYCELIUM_DISABLE_MENTION_WORKER` | unset | `1` stops the background worker that recomputes mentions after name changes. Meant for tests. |
| `MYCELIUM_DISABLE_EMBED_WORKER` | unset | `1` stops the background worker that embeds statements and names saved without a vector (see [When the provider is unavailable](#when-the-provider-is-unavailable)); they then stay out of semantic search. Meant for tests. |
| `MYCELIUM_DISABLE_REVIEW_SWEEP` | unset | `1` stops the sweep that retries failed draft reviews. Meant for tests. |
| `MYCELIUM_DISABLE_AUDIENCE_WORKER` | unset | `1` stops the background worker that labels statements with audiences. Meant for tests. |
| `MYCELIUM_DISABLE_MAINTENANCE_WORKER` | unset | `1` stops the background worker that keeps generated documents current. Meant for tests. |
| `MYCELIUM_DISABLE_LAYOUT_BAKE` | unset | `1` stops recomputing the entity graph layout after entity changes. Meant for tests. |

`MYCELIUM_INGEST_INPUT_PER_MTOK` and `MYCELIUM_INGEST_OUTPUT_PER_MTOK` are no
longer read. Mycelium keeps no prices; runs report tokens instead.

> **Leave `MYCELIUM_AUTH=on` on anything reachable from a network.** With
> auth off every caller is `local-admin`, so it is for a single user on their
> own machine, bound to `127.0.0.1`. The server then answers only requests
> addressed to a loopback name (`localhost`, `127.0.0.1`, `[::1]`), so a web
> page cannot reach it by pointing its own domain at your machine (DNS
> rebinding).

### Hostnames the server answers

Every route refuses a request whose `Host` header names a host it was not
told about, with `421`. It always accepts the loopback names, plus:

- each entry in `MYCELIUM_ALLOWED_HOSTS`, comma-separated, such as
  `mycelium.example.com,kb.example.com`. A port in an entry is ignored;
  only the hostname is compared.
- the host of `MYCELIUM_PUBLIC_URL`, when it is set.

With `MYCELIUM_AUTH=off` the check always applies. With auth on it applies
once either variable is set, so a deployment that never listed its
hostname keeps working; set them anyway. `/api/server-info` is exempt,
because load balancers probe it by the instance's address.

### Request size

Request bodies over 4 MiB get `413` before the server reads the rest.
`MYCELIUM_MAX_BODY_BYTES` changes the cap, for `/mcp` as well as every
other route except media uploads, which are capped by the media size limits
in **Settings → Limits** (20 MB for video by default). nginx's own `client_max_body_size` default of 1 MiB is
tighter still and bites first; raise it in the site template if large
`ingest` payloads get a 413 from nginx.

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
... INFO mycelium.server.startup: startup finished in 0.4s
```

The server listens straight away and finishes starting in the background.
Each migration it runs is logged with its version, name and duration, and
an index rebuild logs its progress:

```
... INFO mycelium.migrations: substrate migration v21 (audience labels): starting
... INFO mycelium.migrations: substrate migration v21 (audience labels): done in 3.2s
... INFO mycelium.server.indexes: rebuilding statement vector index: 1200/6000 re-embedded (40s)
```

Until startup finishes, `/api/server-info` answers `200` with the state
(`starting`, `migrating` or `indexing`), or `503` once it is `failed`, with the
reason. A health check on it therefore passes during a long migration or index
rebuild instead of restarting the server mid-way. Browsers get a page that
reloads itself, and every other request gets `503` with a `Retry-After`
header. Nothing reaches a database before the migrations are
done. Once ready, `/api/server-info` answers `200` with `"state": "ready"`.
If startup fails, the error is logged as a `MYCELIUM_ERROR` line and the
process exits with status 1, so systemd restarts it.

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

Request bodies are capped as described under [Request size](#request-size).

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

An `https://` value also marks the browser session cookie `Secure`, so it
is never sent over plain HTTP; without `MYCELIUM_PUBLIC_URL`, an `https://`
`MYCELIUM_OIDC_REDIRECT_URI` does the same.

### Outbound requests from the OAuth endpoints

A client may identify itself with a Client ID Metadata Document — an HTTPS
URL it hosts — instead of registering. Resolving one means Mycelium makes an
outbound HTTPS request to a URL chosen by the caller, so an egress-filtered
deployment needs to allow that, and an operator should know it happens.

The fetch is fenced: HTTPS only, redirects not followed, a 5s timeout per
network operation and 10s for the whole fetch, a 64 KiB cap, and every address
the hostname resolves to must be on the public internet. Documents are cached
per process, at most 256 at a time (the soonest to expire goes first), for 5
minutes unless `Cache-Control` says otherwise: a `max-age` is held to a
1-minute to 1-hour bound, and a document sent with `no-store`, `no-cache` or
`max-age=0` is not cached at all.

Registration (`/register`) still works for clients that predate the
mechanism; it is deprecated upstream, not removed.

### OAuth token lifetime

An access token issued through the OAuth flow expires after an hour
(`MYCELIUM_OAUTH_ACCESS_TOKEN_TTL_SECONDS`), and comes with a refresh token
the client uses to get the next one. Each refresh replaces the refresh token
and gives it 30 more days, so a client in regular use never has to sign in
again; one left unused for 30 days does. A refresh token presented a second
time means someone else holds a copy, so the whole grant is revoked and the
client must authorize again. Refresh tokens are stored hashed, like access
tokens.

OAuth tokens issued before expiry existed carry no refresh token. Starting
this version gives each a deadline 30 days from that first startup; after
it their clients authorize again. Personal tokens minted in Settings never
expire.

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

### Upgrading an instance at schema v14

An instance last deployed at substrate schema v14 runs fifteen migrations on
the first start of a current build:

| Version | Change |
| --- | --- |
| v15 | Drops the unused alias embeddings and their queue. |
| v16 | Adds source references to knowledge gaps. |
| v17 | Rewrites the seeded `rule` kind definition, only if nobody edited it. |
| v18 | Drops the unused `kind_link_matrix` table. |
| v19 | Replaces the seeded `sub-type` examples, only if nobody edited them. |
| v20 | Adds the table of entity pairs dismissed as not duplicates. |
| v21 | Adds statement audience labels and their queue. |
| v22 | Records when a curator label's statement text changed after the decision. |
| v23 | Adds the connect pass's memory of the statements it looked at. |
| v24 | Widens that memory to every curation item and adds the claims outside agents take on them. |
| v25 | Lets an external audience grant wait for a curator's confirmation (see below). |
| v26 | Marks labelling queue rows that belong to a backfill, so a backfill resumes after a restart. |
| v27 | Lets a curation agent close a knowledge gap as resolved or not applicable. |
| v28 | Adds the memory of items an automation stopped retrying, until their inputs change or an admin retries them. |
| v29 | Lets draft reviews, curation items, mention recomputes and embeddings stop at their retry limits too. |

The drafts and prompts databases upgrade themselves on the same start. The
research feature's data is deleted, as are its settings (see
[Startup changes that are not migrations](#startup-changes-that-are-not-migrations)).
Documentation runs gain summaries, review notes and plans. Saved ingest and
documentation output limits that are still at the old defaults are raised.
Open drafts with no operations and no creator, which earlier builds'
automations left behind, are withdrawn (see
[Startup changes that are not migrations](#startup-changes-that-are-not-migrations)).

**Before:** take a snapshot or `mycelium export`. The previous build refuses
to start on migrated data, so the way back is a restore, as described in
[Rolling back a deploy](#rolling-back-a-deploy).

**Start time:** if the vector indexes are not restored with the data, the
first start rebuilds them from the database before HTTP is available. On
CPU that took about a minute for 4,000 statements.

**After the start**, as an administrator:

1. **Settings → Audiences:** check the four seeded audiences and their
   descriptions, then click **Label unlabelled statements**. Until labelling has run, every
   statement is visible to internal audiences only, so external documents and
   plans have nothing to draw on. With a small model, labelling took about 11
   minutes and $0.10 per 1,000 statements. The external grants it makes then
   wait for confirmation; see
   [Confirming external grants](#upgrading-to-schema-v25-confirming-external-grants).
2. **Settings → Documentation:** choose an audience for each writing profile.
   Profiles without one write for the internal technical audience.
3. **Settings → Models:** choose models for the new actions (audience
   labelling, documentation planning). Check that each provider's model field
   holds a model of that provider.
4. **Documents:** revisions written before this upgrade record no citations,
   so they show as "unknown" rather than out of date until they are revised.

### Upgrading to schema v25: confirming external grants

v25 adds columns to the statement audience labels (the external grants
waiting for a curator, the curator's decisions on AI grants, why a relabel
after an edit narrowed a label, and the confirmed grants an edit kept for a
spot check) and the previous label to the labelling queue.
Grants already in force stay in force; nothing becomes hidden on upgrade.

On startup the seeded audiences get their includes (external technical and
internal non-technical include external non-technical; internal technical
includes the other three), unless an administrator saved them since. This
widens visibility at once: external technical now sees every statement granted
to external non-technical. Check **Settings → Audiences** before the start of
documentation runs if that is not wanted. If the audience labelling
instructions were customised in **Settings → Prompts**, compare them with the
new default, which names only the most restricted audiences a statement fits
and keeps an edited statement's audiences. From this
build on, an AI grant that would newly show a statement to an external
audience waits for a curator while **Settings → Limits → Audience labelling →
Confirm external grants** is on, which is the default.

**After the start**, as an administrator:

1. **Settings → Audiences:** click **Label unlabelled statements** (or
   **Relabel AI labels** when the AI labels are older than the current
   audience descriptions). On an instance that was never labelled, expect
   several hundred grants under **Waiting for confirmation**.
2. For each external audience, click **Review a sample**. Confirm or reject
   every sampled grant; the card shows the sample's precision.
3. If the precision is at or above the warning threshold (90% by default,
   **Settings → Limits**), click **Accept the rest**. Every remaining grant is
   confirmed and records that it was accepted after a sample of that size and
   precision; the sample's rejections stay rejected.
4. If it is below, do not accept the rest: sharpen the audience description or
   the audience labelling instructions (**Settings → Prompts**), click
   **Relabel AI labels**, and review a new sample.

Until a grant is confirmed, external documents and plans do not see the
statement.

---

## Data and backups

Everything an instance knows lives in `/var/lib/mycelium`:

| File | Holds |
|---|---|
| `mycelium.db` | Knowledge: statements, entities, names, links and conditions, vocabularies, knowledge gaps, audience labels; the queues of work against it |
| `mycelium-history.db` | Audit log of substrate changes |
| `mycelium-auth.db` | Users, MCP tokens, invites, OAuth clients |
| `mycelium-drafts.db` | Drafts, their reviews and applications; generated documents, their revisions, runs, publication receipts, plans and maintenance decisions; the AI usage ledger |
| `mycelium-prompts.db` | AI instructions and writing profiles with their history, audiences, model, review and product settings, GitHub connections |
| `mycelium-media.db` | Screenshots and recordings, their labels and attachments ([Media](MEDIA.md)) |
| `mycelium-ops.db` | Only on instances that predate its removal: tool-call telemetry that is no longer written or read, and not archived |
| `mycelium.vec`, `mycelium-names.vec` | Vector indexes; rebuilt by re-embedding if missing |
| `mycelium-vec.lock` | Lock that keeps `mycelium snapshot-indexes` from copying an index mid-write; not data |
| `entity-positions.json` | Entity layout cache; rebuilt if missing |
| `ask_trace.jsonl`, `ingest_trace.jsonl`, `connect_trace.jsonl`, `traces/` | Run traces and profiling output, not data; not archived |
| `.uv-cache/` | uv's package cache, not data |

The databases run in WAL mode, so copying a live `.db` file can produce a
torn copy. Use one of the two methods below.

### Backups: `mycelium export`

`mycelium export` writes one archive holding the databases above, the
audit log and the vector indexes, less the exclusions listed below. Run it
as the service user; it is safe while the service runs. It reads each
database as one consistent snapshot, one database after another, so a write
that lands meanwhile can be in one database's part and missing from a
later one's.

```bash
# once: the CLI wrapper and somewhere the service user may write
sudo install -m 0755 /opt/mycelium/deploy/myc /usr/local/bin/myc
sudo install -d -o mycelium -g mycelium -m 0700 /var/lib/mycelium-backups

sudo myc export /var/lib/mycelium-backups/mycelium-$(date -u +%F).tar.gz
```

It prints a row count per table. `--no-media` leaves screenshots and
recordings out, for a smaller archive; restoring such an archive keeps the
media already in the data directory, and a fresh restore starts without media. Copy archives off the VPS on a schedule,
for example from root's crontab:

```cron
0 3 * * * /usr/local/bin/myc export /var/lib/mycelium-backups/mycelium-$(date -u +\%F).tar.gz && find /var/lib/mycelium-backups -name '*.tar.gz' -mtime +14 -delete
```

followed by your off-site copy (rsync to S3, restic, borg — your call).

The archive is written owner-only and must be treated like the data dir:
it holds token hashes, invite links and all knowledge. It deliberately
leaves out OAuth authorization codes and consent screens (they expire
within minutes), single-use media upload links (they expire within fifteen
minutes), curation leases (an agent claims its work again after a restore),
the marks of one-time environment imports (restore sets them again), and
tool-call telemetry; `UNARCHIVED_TABLES` in `src/mycelium/backup.py` lists
them with reasons.
It also does not hold anything outside the data dir: back up
`/etc/mycelium.env` (session secret, OIDC and GitHub App secrets), the
GitHub App private key, and your nginx and systemd edits separately.

To check a backup, restore it into a scratch directory. `import` prints the
row counts recorded in the archive, not what it restored, so count a few
tables in the restored copy and compare them with the counts `export`
printed:

```bash
sudo -u mycelium /opt/mycelium/.local/bin/uv --project /opt/mycelium run \
  mycelium --data-dir /tmp/restore-check import /var/lib/mycelium-backups/<archive>
sudo -u mycelium sqlite3 /tmp/restore-check/mycelium.db \
  'SELECT (SELECT COUNT(*) FROM statements), (SELECT COUNT(*) FROM entities)'
sudo rm -rf /tmp/restore-check
```

### Opening a copy of production data

A restored copy holds the original's review settings, writing profiles and
GitHub destinations. Started normally, it reviews submitted drafts, labels
statements, revises out-of-date documents and opens pull requests against
the original's repositories, all with your AI credentials. Start a copy you
only want to inspect or test against in quarantine:

```bash
MYCELIUM_DATA_DIR=/tmp/restore-check mycelium-http --quarantine
# or, for a service or container:
MYCELIUM_QUARANTINE=1 mycelium-http
```

In quarantine:

- the audience labeller, the draft-review sweeper and document maintenance
  do not start;
- draft review counts as off: submitted drafts are not reviewed, and a
  review cannot be started by hand;
- publishing to GitHub is refused.

Nothing saved changes, so the same data dir starts normally once the flag
is gone. `/api/server-info` reports `"quarantine": true`, and the web app
shows a banner while it is on. Ask, ingest and document generation still
work when someone starts them and credentials are set; leave the AI keys out
of the environment as well if the copy should make no model calls at all.
`mycelium serve --quarantine` does the same for the stdio server.

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

### Index durability on ephemeral storage

A host that restores the databases on every start (for example from
Litestream) loses the vector indexes with the disk, and rebuilding them
re-embeds every statement and name before HTTP is available. To keep them,
copy them with:

```bash
mycelium snapshot-indexes <dir>
```

It writes `mycelium.vec`, `mycelium-names.vec` and their `.meta.json` files
into `<dir>`. It is safe while the server runs: it waits for any index write
in flight and copies between writes. Each copied `.meta.json` also records a
fingerprint of the database the copy matches (the vector ids the database
maps and the texts behind them). It exits non-zero and copies nothing when an
index is missing or marked dirty, so a failed run must not replace the
previous copy.

To restore, put the four files in the data dir beside the restored databases
before the server starts. The server loads a copy whose fingerprint matches
the restored database, which takes seconds; otherwise it rebuilds that index
and logs why, for example:

```
... WARNING mycelium.server.indexes: rebuilding statement vector index: snapshot reflects 6000 mapped vector(s) of another database state; the database maps 6012
```

A copy taken while statements were still being written is older than a
database that kept replicating, so it is rebuilt rather than loaded. Take a
last copy after the server has exited, before the host stops, so the next
start finds a copy that matches. Copy the files only through
`snapshot-indexes`: index files copied straight out of a live data dir carry
no fingerprint, and the server trusts such files as its own.

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
   every statement or name, which needs the configured embedding provider
   (see [Embedding provider](#embedding-provider)) and takes time proportional to the
   knowledge base.

   ```bash
   sudo systemctl start mycelium
   sudo journalctl -u mycelium -n 50 --no-pager
   ```

6. Count a few tables in the new data dir (`statements`, `entities`,
   `users`) and compare them with the counts `export` printed, then sign
   in and run a search you know the answer to.

   To look around before the new instance takes over, start it in
   quarantine first (see [Opening a copy of production
   data](#opening-a-copy-of-production-data)).

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
expects. Only the substrate carries a schema version: the other databases
upgrade themselves on start and an older build does not refuse them, so
read the release notes for changes to them, and restore the snapshot when
in doubt.

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
[AI prompts](AI_PROMPTS.md#when-a-release-changes-a-default)): Ingestion
and Document generation instructions still authored by `seed` get
the new build's default appended as a new version, and saved instructions
that predate a newer default are logged as a warning. The first start of a
build with this behaviour also creates `shipped_prompt_texts` in
`mycelium-prompts.db` and records the defaults it saw. An instance that ran
with the previous audience labelling default and never saved its own gets
that text saved as an `upgrade` version, so labelling keeps its rule about
what external audiences never get.

Starting a build without packaged writing profiles changes nothing stored: a
`kb-authoring` profile seeded by an earlier build stays as it is. A fresh
instance starts with no writing profile.

Restoring a snapshot undoes these with everything else. A code-only
rollback does not: the previous build serves the appended versions and
ignores the new table. To return to the earlier wording, restore it from
**Version history** in **Settings → Prompts**.

The first start of a build without research runs deletes what that feature
left: the `research_runs` table in `mycelium-drafts.db`, and the research
instructions, model selection, limits, sources and concurrency limit in
`mycelium-prompts.db`. Drafts that research runs created are ordinary drafts
and stay. Importing an older archive skips the same data.

The first start of a build where audiences no longer scope principals drops
`audience_id` from the users, MCP tokens and OAuth codes in
`mycelium-auth.db`. A user or token that was scoped to an audience now reads
what its role allows, and each one is logged as a warning naming its id and
former audience. Importing an older archive drops the column the same way. A
code-only rollback adds the column back empty, so every principal stays
unscoped.

The same start turns the retired `asker` role into `reader` on users, MCP
tokens (OAuth grants included) and invites, logging how many rows of each
changed. Importing an older archive does the same, with a deprecation warning.

Each start withdraws open drafts in `mycelium-drafts.db` that have no
operations, no creator and no repository source. Earlier builds' connect and
curation automations opened such drafts and added nothing to them. The
withdrawal is recorded as made by `upgrade`, and the start logs how many it
withdrew; nothing is deleted. Open drafts a person, agent or repository
created stay open, even when empty. A count logged after the first start of
this build means something still leaves empty drafts behind.

---

## Embedding provider

Statements and names are searched through embeddings. Each deployment picks
one provider:

| Variable | Default | Effect |
| --- | --- | --- |
| `MYCELIUM_EMBED_PROVIDER` | `ollama` | `ollama` embeds on a local Ollama server; `openai` calls the OpenAI embeddings API. |
| `MYCELIUM_EMBED_MODEL` | `nomic-embed-text` for Ollama, `text-embedding-3-small` for OpenAI | The model. Ollama also reads the older `EMBED_MODEL`. Both produce 768-dimensional vectors; a model that returns another size is refused. |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint. |
| `OPENAI_API_KEY` | unset | Required for `openai`; the same key the OpenAI AI actions use. |

**Ollama** needs the server running and the model pulled, and about 2 GB of
RAM on top of Mycelium:

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
sudo -u mycelium ollama pull nomic-embed-text
```

**OpenAI** needs only the key. Requests are batched, 100 texts at a time, and
their tokens appear under **Settings → AI usage** as *Embeddings*.
Re-embedding a knowledge base of a few thousand statements costs well under a
cent, and each search embeds its query once (repeated queries are cached).

Similarity thresholds (the near-duplicate warning, `find_duplicates`,
`discover_facts`, `find_entity_duplicates`, search floors) are tuned per model,
because the models score on different scales. A model without tuned values
uses its provider's default model's values and logs a warning at first use.

### Switching provider

Set the variables and restart. Embeddings are a derived index, so no knowledge
changes. Each index file records the embedder that built it in a
`.meta.json` file beside it (`mycelium.vec.meta.json`,
`mycelium-names.vec.meta.json`). On startup, an index built by a different
provider or model is discarded and rebuilt by re-embedding every statement and
name; vectors from two models are never mixed. The rebuild's progress is
logged and shown as the startup step in `/api/server-info`, and the server
answers `503` until it finishes. The file also records the index format. An
index without the file, or with an earlier format, is rebuilt the same way
once: indexes written before format 2 could lose statements from semantic
search.

Switching back rebuilds again. Exports carry the `.meta.json` files with the
indexes. A copy written by `mycelium snapshot-indexes` also records the
database it matches; see
[Index durability on ephemeral storage](#index-durability-on-ephemeral-storage).

### When the provider is unavailable

Embedding requests time out after `EMBED_TIMEOUT_S` and are retried twice
(honouring a rate limit's `Retry-After`, up to 20 seconds). If the provider
still fails:

- `search_statements` (also with `decompose`) falls back to keyword matching,
  and `search_entities` to name substring matching. Each hit is marked
  `retrieval: "keyword"`. Ask and documentation runs keep working, with weaker
  retrieval. `discover_facts` reports the error instead, since a keyword
  guess would mislead it. `find_duplicates` keeps working: it compares the
  vectors already in the index and calls no provider, so only statements
  still waiting for a vector are left out.
- A write still succeeds. The statement or name is saved without a vector and
  stays out of semantic search until a background worker re-embeds it, which it
  retries every 30 seconds. A row that keeps failing while others embed is
  passed over and listed under Stopped automations on Knowledge health. Statement responses carry `embedding_pending`; name
  responses are unchanged. An edited statement's old vector is removed, so
  search never matches its previous wording.
- A startup that has to rebuild an index fails and reports why; it needs the
  provider.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `503` from nginx | Service isn't running. `sudo systemctl status mycelium`, check journal. |
| `503` from Mycelium itself, "Mycelium is starting up" | Startup is still migrating or re-embedding. `curl -s localhost:8765/api/server-info` shows the step; the journal shows each migration's progress. |
| `502` from nginx | Service is up but uvicorn isn't bound to `127.0.0.1:8765`. Confirm `MYCELIUM_HTTP_HOST/PORT` in the systemd unit aren't being overridden by the env file. |
| Service stops right after a deploy with `database schema version N is newer than this build's latest known version M` | An older build is running on migrated data. See [Rolling back a deploy](#rolling-back-a-deploy). |
| Deploy aborts with `snapshot failed` | A database in `/var/lib/mycelium` failed its check, or the disk is full. The running build was restarted unchanged; read the message above it. |
| `403` on every login | `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` doesn't match, or the database already has an admin. Inspect with sqlite3. With `MYCELIUM_ALLOWED_EMAIL_DOMAINS` set, the email's domain must be listed too. |
| MCP `/mcp` 401 with a token | Token might be revoked or the user suspended. Check via the Settings UI. |
| Requests are slow | `GET /api/admin/performance` (admin) gives p50, p95 and max per route over the last 15 minutes, split into time to first byte, waiting for a worker thread, running, write-lock wait and hold, embedding, SQLite and model calls, and shows how busy the worker threads are. An MCP request is listed by its method and tool, such as `MCP tools/call ask`. Each slow request also logs a `MYCELIUM_SLOW_REQUEST` line with the same split. |
| A load balancer reports MCP responses capped at about 15 s | Time to first byte, not duration: for a 2026-07-28 client, the MCP SDK holds the response until the tool finishes or 15 s pass, then streams and pings until it does. The tool ran longer; its `MYCELIUM_SLOW_REQUEST` line has the full time. |
| MCP `/mcp` hangs | nginx is buffering. Confirm `proxy_buffering off` is in the `/mcp` location block. |
| Auth0 callback "redirect URI mismatch" | The URL in Auth0's allowed callbacks must be an exact match for `MYCELIUM_OIDC_REDIRECT_URI`, scheme included. |

Logs:

```bash
sudo journalctl -u mycelium -n 200 --no-pager
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```
