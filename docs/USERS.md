# Managing users

Mycelium has two kinds of identity:

- **Humans** authenticate via OIDC (Auth0). They log into the web UI
  with a cookie session, mint their own MCP tokens, and can be
  promoted to admins.
- **Service accounts** are token-only identities for third-party agents
  (CI bots, doc-generator agents, custom Claude Code skills, etc.).
  They have no email, can't log in to the UI, and exist solely to own
  bearer tokens.

Both types live in the same `users` table and share the same
permission system. Both can hold multiple, independently-revocable
tokens.

---

## Roles

| Role | Can do |
|---|---|
| `reader` | Call any read tool (`list_*`, `get_*`, `search_*`, `grep_*`, `discover_*`, `find_*`). Cannot mutate the substrate. |
| `writer` | Everything `reader` can, plus all mutating tools (`upsert_*`, `add_*`, `patch_*`, `attach_*`, `rename_*`, `move_*`, etc.). |
| `admin` | Everything `writer` can, plus destructive ops (`delete_*`, `merge_*`) and the user-management surface. |

Roles are enforced **per request** in two places:

1. The REST mirror (`http.py`) checks before calling the underlying
   function.
2. The MCP `@tool` wrapper (`server.py`) checks via the
   `current_principal` ContextVar that the middleware populated.

Both paths use the same `auth.required_role_for(func_name)`
classification, so policy can't drift between transports.

---

## Inviting a human

1. Log in to the UI as an admin.
2. **Settings → Users & invites**.
3. Under **Invite human**, enter the email and pick a starting role.
   Click **Invite**.
4. A link appears at the top of the section. Click **Copy link** in
   the invites table — that's the URL to send to the invitee.
5. The invitee opens the link in their browser. It redirects them to
   Auth0, where they sign in (using whatever identity matches their
   email — Google, GitHub, password). When they come back, Mycelium
   sees a matching invite, accepts it, and creates their `users` row
   with the role you assigned.

**Important:** the invite is only consumed by a login whose verified
email matches the invited address. If Alice invites `bob@example.com`
and Bob logs in as `bob@gmail.com`, the invite stays pending.

Pending invites are listed in the same section and can be revoked
with the **Revoke** button. Revoking deletes the invite row; the link
becomes useless.

---

## Creating a service account

For automated agents that should write to Mycelium without a human
behind them.

1. **Settings → Users & invites → Create service account**.
2. Enter a name that identifies what the agent is (e.g. `ci-doc-bot`,
   `feedback-ingestor`, `claude-skill-changelog`). Pick a role.
3. Click **Create**. The row appears in the members table with
   `type=service`.
4. Click **Mint token** next to the new service account. Give the
   token a name (often the same as the account, or with a host suffix
   if the same agent runs in multiple places).
5. The raw token appears in a green banner. **Copy it now** — it is
   never shown again. Paste it into whatever agent config needs it.

A service account can hold many tokens. Revoke them individually as
agents are decommissioned.

> **Why separate types?** Both kinds *could* technically be a single
> "user", but separating them gives you:
>
> - Honest attribution — substrate writes record whether they came from
>   a human or a bot.
> - No confused login UI — service accounts can't accidentally try to
>   log in via OIDC and fail.
> - Easier rotation — wiping a service account doesn't risk locking out
>   a human collaborator.

---

## Changing someone's role

In the members table on **Settings → Users & invites**, the **Role**
column is a dropdown. Change it; the update is immediate.

Safety: Mycelium refuses to demote the **last active admin** — there
must always be at least one. If you're locked out, you can promote a
new admin directly in SQLite:

```bash
sudo sqlite3 /var/lib/mycelium/main.db \
  "UPDATE users SET role='admin' WHERE email='backup-admin@example.com'"
```

(Restart isn't needed; roles are read live from the DB on every
request.)

---

## Suspending an account

Same table, **Suspend** button. A suspended account:

- Can't log in via OIDC (the callback returns 401 because the user is
  inactive).
- Loses every token immediately — `resolve_token` checks the user's
  status and rejects when not `active`.
- Stays in the table so you can re-activate later without losing the
  attribution history.

Useful when an employee leaves, when a service-account credential
might be compromised, or as a "soft delete" before you decide to
remove someone for good.

---

## Managing your own tokens

Every authenticated user has **Settings → MCP tokens** — list, create,
revoke. You can mint tokens with **any scope ≤ your own role**:

- An admin can mint `admin`, `writer`, or `reader` tokens.
- A writer can mint `writer` or `reader` tokens.
- A reader can mint `reader` tokens only.

Why downgrade your own token? Two common reasons:

1. **Sandboxing a risky agent.** You're an admin but you want to give
   a new automation read-only access until you trust it.
2. **Defense in depth.** A laptop token gets stolen → if it was minted
   `reader`, the blast radius is limited even though you have full
   privileges in person.

The scope is **re-clamped** on every request against your current
role. If you're demoted from admin to writer, an `admin`-scoped token
you previously minted immediately downgrades to `writer` — you can't
escape demotion by hanging onto an old token.

---

## What clients see

Each request carries one principal. The principal's identity is what
shows up in the substrate's `created_by` and `updated_by` columns —
so the audit trail tells you which human or service account authored
which statement. This works automatically; no client config required.

---

## Inspecting state from the command line

When the UI isn't enough, the SQLite store is human-queryable:

```bash
# All users
sudo sqlite3 -header -column /var/lib/mycelium/main.db \
  "SELECT name, type, email, role, status, created_at FROM users"

# All tokens (hashed; raw secrets are NEVER stored)
sudo sqlite3 -header -column /var/lib/mycelium/main.db \
  "SELECT u.name AS user, t.name AS token, t.prefix, t.scope,
          t.created_at, t.last_used_at, t.revoked_at
     FROM mcp_tokens t JOIN users u ON u.id = t.user_id
   ORDER BY t.created_at DESC"

# Pending invites
sudo sqlite3 -header -column /var/lib/mycelium/main.db \
  "SELECT email, role, created_at FROM invites WHERE accepted_at IS NULL"
```

Direct DB writes are supported — Mycelium re-reads roles and statuses
live, so a SQL update takes effect on the next request without a
restart. Useful for emergency unblocking.

---

## Common scenarios

**"I want to give a teammate the same access as me, no questions
asked."** → Invite them as a `writer`. They'll get the same authoring
surface, just not the admin tools.

**"I want a CI job to run a nightly extraction."** → Create a service
account with role `writer`. Mint one token. Put it in your CI secrets.
Done.

**"I want a Claude Code skill to do dry-run analysis without ever
writing."** → Mint a `reader`-scoped token under your own user (or a
new service account, whichever you prefer). Hand that to the skill.
The substrate is now write-protected against this client even though
the underlying identity has write access.

**"A laptop with a token was lost."** → Settings → MCP tokens →
**Revoke** that one token. Everything else the user has stays valid.

**"A team member is leaving."** → Suspend them on
**Settings → Users & invites**. All their tokens die immediately. Keep
the user row so the attribution stays meaningful in the substrate.
