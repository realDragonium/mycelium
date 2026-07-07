# Auth0 setup

Mycelium uses Auth0 (or any OIDC issuer) only for **human logins** to
the web UI. MCP tokens work entirely server-side and don't touch
Auth0 — you mint them after logging in, and Claude clients send them
as bearer headers without any OIDC round-trip.

This guide assumes you've already signed up for Auth0
(`https://auth0.com`, free tier). Total time: ~10 minutes.

---

## 1. Create a Regular Web Application

1. In the Auth0 dashboard sidebar: **Applications → Applications →
   Create Application**.
2. Name: `Mycelium` (or whatever you like).
3. Type: **Regular Web Applications**.
4. Click **Create**.

You land on the application's settings page. Keep this tab open — you'll
copy three values out of it shortly.

---

## 2. Note your tenant details

From the **Settings** tab of the application:

| Auth0 field | Mycelium env var |
|---|---|
| **Domain** (e.g. `your-tenant.us.auth0.com`) | `MYCELIUM_OIDC_ISSUER` (prefix with `https://`) |
| **Client ID** | `MYCELIUM_OIDC_CLIENT_ID` |
| **Client Secret** | `MYCELIUM_OIDC_CLIENT_SECRET` |

The issuer URL must include the scheme. E.g.:

```
MYCELIUM_OIDC_ISSUER=https://your-tenant.us.auth0.com
```

---

## 3. Configure URLs

Scroll down on the application **Settings** page.

**Allowed Callback URLs:**

```
https://mycelium.example.com/auth/callback
```

Substitute your actual domain. Auth0 requires an **exact** match — no
trailing slash, no typo, scheme included. If you have multiple
environments (staging + prod), add them on separate lines:

```
https://mycelium.example.com/auth/callback,
https://mycelium-staging.example.com/auth/callback
```

**Allowed Logout URLs:**

```
https://mycelium.example.com/ui/
```

(Where Auth0 sends the user after they log out.)

**Allowed Web Origins:**

```
https://mycelium.example.com
```

Click **Save Changes** at the bottom.

---

## 4. Enable the email scope

Mycelium uses the user's verified email to match against invites and
the bootstrap admin, so the ID token must carry it.

In the same application **Settings** page, scroll down to **Advanced
Settings → OAuth**. The default OIDC scopes already include `email`
when the client requests it (Mycelium does), so you usually don't need
to change anything here.

Verify by going to **Auth Pipeline → Rules** (or **Actions** in newer
tenants): no rules should be stripping the `email` claim from the
ID token. A fresh tenant has none.

---

## 5. Pick how users authenticate

Auth0 ships with a default **Database** connection (username +
password). For an internal tool, you probably want to layer one or
more of:

- **Google Workspace** — under **Authentication → Social**, enable
  Google. Useful if your team is on Google Workspace.
- **GitHub** — under **Authentication → Social**, enable GitHub. Useful
  for dev teams.
- **Username/Password** — already on by default.

Each connection you enable becomes a button on the Auth0 hosted login
page. You don't need to do anything in Mycelium to support them —
they all produce the same OIDC ID token shape.

If you want to **restrict signups** (e.g. only people on your domain),
either:

- Turn off **Disable Sign Ups** on the database connection (forces
  every account to come from a social provider you've vetted), or
- Add an Action that rejects logins where the email domain doesn't
  match (Auth0 → Actions → Library → Custom).

But for the simplest case: Mycelium itself rejects logins from
un-invited emails (see [USERS.md](USERS.md)), so even if Auth0 lets
anyone sign in, Mycelium will only let invited users through.

---

## 6. Wire it into Mycelium

Drop the three values into `/etc/mycelium.env` on the server:

```ini
MYCELIUM_AUTH=on
MYCELIUM_OIDC_ISSUER=https://your-tenant.us.auth0.com
MYCELIUM_OIDC_CLIENT_ID=abc123…
MYCELIUM_OIDC_CLIENT_SECRET=xyz789…
MYCELIUM_OIDC_REDIRECT_URI=https://mycelium.example.com/auth/callback
MYCELIUM_BOOTSTRAP_ADMIN_EMAIL=you@example.com

# Don't forget the session secret — required when AUTH=on
MYCELIUM_SESSION_SECRET=<openssl rand -base64 48>
```

Restart:

```bash
sudo systemctl restart mycelium
```

---

## 7. Test the login flow

1. Open `https://mycelium.example.com/` in a fresh browser (or
   incognito, to avoid cached cookies).
2. The middleware sees no session and 401s; visit
   `https://mycelium.example.com/auth/login` to start the OIDC dance.
3. Auth0's hosted login page appears. Log in.
4. Auth0 redirects back to `/auth/callback`, Mycelium provisions your
   user with the `admin` role (because your email matches
   `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL` and there are no other admins
   yet), and drops you on the UI logged in.
5. Visit **Settings**. The "Users & invites" section should be
   visible — admin only.

---

## Troubleshooting

**`Callback URL mismatch`** — Auth0 dashboard's *Allowed Callback URLs*
doesn't include the URL Mycelium is sending. The URL must be byte-exact
including scheme.

**`401` and a Mycelium 403 "this account is not authorized"** — Auth0
let you in but Mycelium refused. Means:

- The email doesn't match `MYCELIUM_BOOTSTRAP_ADMIN_EMAIL`, OR
- An admin already exists (the bootstrap is one-shot), OR
- There's no pending invite for this email.

Inspect the DB:

```bash
sudo sqlite3 /var/lib/mycelium/main.db \
  "SELECT email, role, status, created_at FROM users"
```

**`No 'sub' claim`** — Auth0 isn't returning an ID token. Make sure
your application type is **Regular Web Application** (not SPA or M2M)
and that your `MYCELIUM_OIDC_CLIENT_SECRET` is the actual secret, not
the client ID.

**Loop on `/auth/login`** — usually a session cookie problem. Confirm
`MYCELIUM_SESSION_SECRET` is set, the secret hasn't changed mid-session
(which would invalidate the cookie), and that your reverse proxy isn't
stripping cookies.

---

## Switching to a different OIDC provider

Mycelium uses Authlib's generic OIDC client — anything that serves
`/.well-known/openid-configuration` works:

- Google Identity: `MYCELIUM_OIDC_ISSUER=https://accounts.google.com`
- Microsoft Entra: `MYCELIUM_OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0`
- Authentik / Keycloak / Okta / WorkOS — all fine, set the issuer URL
  appropriately and configure the callback at the provider.

The rest of Mycelium's auth surface (invites, tokens, roles) is
provider-agnostic.
