"""Standalone setup / connection guide.

A single self-contained HTML page served at `/connect`. Independent of
the main UI bundle — no React component tree to load, no substrate
dump to fetch, no graph visualization. Just plain HTML + a tiny bit of
JavaScript that pulls the live MCP URL from `/api/server-info` so the
copy-paste snippets are correct for whatever host this is deployed at.

Kept in Python (not under `ui/` as a static file) because the page
needs no build step and putting it next to the route that serves it
makes the wiring obvious. The HTML lives as a module-level constant;
the route hands it back with `text/html`.
"""

from __future__ import annotations

CONNECT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Connect a client · Mycelium</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0b0b0c;
    --surface: #121214;
    --surface-2: #1a1a1d;
    --rule: #26262a;
    --ink: #f4f4f5;
    --ink-2: #c5c5cb;
    --ink-3: #8a8a93;
    --accent: #60a5fa;
    --amber: #fbbf24;
    --green: #4ade80;
    --red: #f87171;
    --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #fafafa; --surface: #fff; --surface-2: #f3f4f6;
      --rule: #e4e4e7; --ink: #18181b; --ink-2: #3f3f46; --ink-3: #71717a;
      --accent: #2563eb;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: 'Geist', system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--ink); line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  code, pre { font-family: var(--mono); }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }
  pre code { background: transparent; padding: 0; }
  .top {
    border-bottom: 1px solid var(--rule); padding: 14px 0;
    background: var(--surface);
  }
  .top-inner {
    max-width: 860px; margin: 0 auto; padding: 0 24px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .brand {
    font-weight: 600; font-size: 15px; letter-spacing: -0.01em;
  }
  .brand-sub {
    font-family: var(--mono); font-size: 10.5px; color: var(--ink-3);
    margin-left: 8px; letter-spacing: 0.04em; text-transform: uppercase;
  }
  .top a { font-size: 13px; color: var(--ink-2); }
  main {
    max-width: 860px; margin: 0 auto; padding: 40px 24px 80px;
  }
  h1 { font-size: 28px; margin: 0 0 8px; letter-spacing: -0.02em; }
  h2 {
    margin: 36px 0 14px; font-size: 12px; color: var(--ink-3);
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
  }
  h3 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
  p { margin: 0 0 12px; color: var(--ink-2); }
  p.lede { color: var(--ink-3); font-size: 14px; margin-bottom: 30px; }
  .card {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 8px; padding: 22px 26px; margin-bottom: 18px;
  }
  .banner {
    border-radius: 6px; padding: 12px 16px; font-size: 13px;
    margin-bottom: 22px;
  }
  .banner-amber { background: rgba(217,119,6,0.08); border: 1px solid rgba(217,119,6,0.35); color: var(--ink-2); }
  .banner-blue { background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.35); color: var(--ink-2); }
  .steps { display: grid; gap: 22px; }
  .step { display: flex; gap: 16px; }
  .step-num {
    flex-shrink: 0; width: 28px; height: 28px; border-radius: 50%;
    background: var(--surface-2); color: var(--ink-2);
    display: flex; align-items: center; justify-content: center;
    font-family: var(--mono); font-size: 12px; font-weight: 600;
  }
  .step-body { flex: 1; min-width: 0; }
  .step-body p { margin: 4px 0 0; font-size: 13.5px; }
  .tabs {
    display: flex; gap: 0; border-bottom: 1px solid var(--rule);
    margin: 0 0 18px;
  }
  .tab {
    padding: 10px 16px; font-size: 13px; border: none; background: transparent;
    cursor: pointer; color: var(--ink-3); margin-bottom: -1px;
    border-bottom: 2px solid transparent; font-family: inherit;
  }
  .tab:hover { color: var(--ink-2); }
  .tab.active { color: var(--ink); border-bottom-color: var(--accent); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .snippet { position: relative; margin: 10px 0 14px; }
  .snippet-label {
    font-family: var(--mono); font-size: 11px; color: var(--ink-3);
    margin-bottom: 4px; text-transform: lowercase;
  }
  .snippet pre {
    margin: 0; padding: 14px 16px; background: var(--surface-2);
    border-radius: 6px; font-size: 12.5px; line-height: 1.55;
    overflow-x: auto; color: var(--ink);
  }
  .copy-btn {
    position: absolute; top: 24px; right: 8px;
    font-size: 11px; padding: 4px 10px;
    background: var(--surface); border: 1px solid var(--rule);
    color: var(--ink-2); border-radius: 4px; cursor: pointer;
    font-family: inherit;
  }
  .copy-btn:hover { color: var(--ink); }
  details { font-size: 13px; margin-top: 10px; }
  summary { cursor: pointer; padding: 4px 0; color: var(--ink-2); font-weight: 500; }
  summary:hover { color: var(--ink); }
  details > div, details > ul, details > p {
    padding: 6px 0 8px 14px; color: var(--ink-3); font-size: 13px;
  }
  ul { padding-left: 20px; }
  .endpoint-grid {
    display: grid; grid-template-columns: 180px 1fr; gap: 8px 16px;
    font-size: 13px; margin-top: 12px;
  }
  .endpoint-grid > :nth-child(odd) { color: var(--ink-3); }
  .err {
    color: var(--red); font-size: 13px; padding: 16px;
    border: 1px solid var(--red); border-radius: 6px;
  }
</style>
</head>
<body>
<div class="top">
  <div class="top-inner">
    <div><span class="brand">Mycelium</span><span class="brand-sub">connect</span></div>
    <div id="top-nav">
      <!-- Populated by JS based on auth state. Two states:
           - logged out: a single "Sign in" link.
           - logged in:  "Manage tokens" and "View substrate" links. -->
    </div>
  </div>
</div>

<main>
  <h1>Connect a client</h1>
  <p class="lede">Wire Claude Desktop, Claude Code, or any MCP-aware client to this Mycelium instance over HTTP. Most people just paste the URL into their client and sign in with Google when prompted — no tokens to copy around.</p>

  <div id="boot-error" class="err" style="display:none"></div>
  <div id="auth-disabled" class="banner banner-amber" style="display:none">
    <strong>Auth is disabled.</strong> The <code>Authorization</code> header is not required against this instance — but tokens still work and are recommended if you'll ever flip auth on.
  </div>

  <h2>How it works</h2>
  <div class="card">
    <p>Mycelium supports two ways to connect, depending on who's behind the client:</p>
    <ul style="margin-top: 10px;">
      <li><strong>Sign in with browser (recommended for humans)</strong> — paste the URL into Claude Desktop or Claude Code and it'll open your browser to sign in via Google Workspace. No tokens to manage; the client gets one automatically.</li>
      <li><strong>Personal access token (for service accounts, CI, scripts)</strong> — mint a long-lived token in Settings and paste it into the client's config. Useful when there's no human at a browser to complete the sign-in flow.</li>
    </ul>
    <p style="font-size: 12.5px; color: var(--ink-3); margin-top: 12px;">
      Browser sign-in is invite-only — your email address has to be on the allow list first. Ask an admin to invite you if you can't get in.
    </p>
  </div>

  <h2>Client configuration</h2>
  <div class="card">
    <div class="tabs">
      <button class="tab active" data-tab="cc">Claude Code</button>
      <button class="tab" data-tab="cd">Claude Desktop</button>
      <button class="tab" data-tab="token">Service account (token)</button>
      <button class="tab" data-tab="raw">Other MCP clients</button>
    </div>

    <div class="tab-panel active" data-panel="cc">
      <p>From any terminal where the <code>claude</code> CLI is installed:</p>
      <div class="snippet">
        <div class="snippet-label">add the server</div>
        <pre><code id="cc-add">loading…</code></pre>
        <button class="copy-btn" data-copy="cc-add">Copy</button>
      </div>
      <p style="font-size: 13px; margin-top: 12px;">Then drive the sign-in:</p>
      <ol style="font-size: 13px; padding-left: 20px; line-height: 1.7;">
        <li>Open a Claude Code session: <code>claude</code></li>
        <li>Type <code>/mcp</code> to see the MCP picker.</li>
        <li>Select <strong>mycelium</strong> — it'll show <em>Needs authentication</em>.</li>
        <li>Claude opens your browser. Sign in with Google → click <strong>Allow</strong> on the consent page.</li>
        <li>Status flips to <em>Connected</em>. You're done.</li>
      </ol>
    </div>

    <div class="tab-panel" data-panel="cd">
      <p style="margin-top: 0;">No config file editing needed — Claude Desktop has a built-in UI for this.</p>

      <ol style="font-size: 13.5px; padding-left: 22px; line-height: 1.85;">
        <li>In Claude Desktop, open <strong>Settings → Connectors</strong> (called "Integrations" on some versions).</li>
        <li>Click <strong>Add Custom Connector</strong>.</li>
        <li>Paste the URL below as the connector address:
          <div class="snippet" style="margin-top: 6px;">
            <pre><code id="cd-url">loading…</code></pre>
            <button class="copy-btn" data-copy="cd-url">Copy</button>
          </div>
        </li>
        <li>Click <strong>Add</strong>. Claude Desktop detects that Mycelium needs auth and opens your browser.</li>
        <li>Sign in with Google → click <strong>Allow</strong> on the consent page.</li>
        <li>The connector flips to "Connected". Open a new chat and Mycelium's tools appear in the tools menu.</li>
      </ol>

      <p style="font-size: 12.5px; color: var(--ink-3); margin-top: 14px;">
        Requires a recent Claude Desktop build (Connectors UI). If you don't see the option, update the app first.
      </p>

      <details style="margin-top: 18px;">
        <summary>Old way: edit config file manually</summary>
        <p style="margin-top: 8px;">Only needed for older Claude Desktop versions, Linux, or unattended deployments. Edit the config file, save, then fully quit Claude (menu → Quit) and reopen — the app only reads config on startup.</p>
        <div class="snippet">
          <div class="snippet-label">claude_desktop_config.json</div>
          <pre><code id="cd-cfg">loading…</code></pre>
          <button class="copy-btn" data-copy="cd-cfg">Copy</button>
        </div>
        <p style="font-size: 12.5px;">Config file location:</p>
        <ul>
          <li>macOS: <code>~/Library/Application Support/Claude/claude_desktop_config.json</code></li>
          <li>Windows: <code>%APPDATA%\\Claude\\claude_desktop_config.json</code></li>
          <li>Linux: <code>~/.config/Claude/claude_desktop_config.json</code></li>
        </ul>
      </details>
    </div>

    <div class="tab-panel" data-panel="token">
      <p>For service accounts, CI agents, or anything that can't open a browser to sign in. Tokens never expire and are revocable individually.</p>
      <ol style="font-size: 13px; padding-left: 20px; line-height: 1.7;">
        <li>Go to <a href="/ui/#/settings">Settings → MCP tokens</a>.</li>
        <li>For a service account: ask an admin to create one in <strong>Settings → Users &amp; invites</strong>, then mint a token under that account.</li>
        <li>For a personal CI token: mint it under your own user. Pick a scope (<code>reader</code> / <code>writer</code> / <code>admin</code>; capped at your role).</li>
        <li>Copy the token immediately — it's shown <strong>once</strong>.</li>
      </ol>
      <p style="font-size: 13px; margin-top: 14px;">Use it as a bearer header:</p>
      <div class="snippet">
        <div class="snippet-label">Claude Code with explicit token</div>
        <pre><code id="cc-add-token">loading…</code></pre>
        <button class="copy-btn" data-copy="cc-add-token">Copy</button>
      </div>
      <div class="snippet">
        <div class="snippet-label">Claude Desktop config with token</div>
        <pre><code id="cd-cfg-token">loading…</code></pre>
        <button class="copy-btn" data-copy="cd-cfg-token">Copy</button>
      </div>
    </div>

    <div class="tab-panel" data-panel="raw">
      <p>Mycelium speaks MCP over <strong>streamable HTTP</strong> and implements the MCP authorization spec (RFC 9728 protected resource metadata, RFC 8414 authorization server metadata, RFC 7591 Dynamic Client Registration, OAuth 2.1 with PKCE). Any client that supports those will work without per-client configuration beyond the MCP URL.</p>
      <div class="snippet">
        <div class="snippet-label">MCP endpoint</div>
        <pre><code id="raw-url">loading…</code></pre>
        <button class="copy-btn" data-copy="raw-url">Copy</button>
      </div>
      <p style="font-size: 12.5px; color: var(--ink-3); margin-top: 10px;">
        Discovery starts from the <code>WWW-Authenticate</code> header on the first 401 from <code>/mcp</code>. Clients that don't implement OAuth-based MCP can still use the token path above with <code>Authorization: Bearer myc_…</code>.
      </p>
    </div>
  </div>

  <h2>Troubleshooting</h2>
  <div class="card">
    <details>
      <summary>Browser sign-in shows "this account is not authorized"</summary>
      <p>Your Google Workspace email is signed in but isn't on Mycelium's invite list. Sign-up is invite-only. Ask an admin to add you in <strong>Settings → Users &amp; invites</strong>, then re-attempt sign-in.</p>
    </details>
    <details>
      <summary>Claude shows "Needs authentication" but clicking it does nothing</summary>
      <p>Browser blocked the popup, or the loopback callback port is firewalled. Allow popups for <code>claude.ai</code> / the desktop app, and ensure no firewall is blocking <code>localhost:6274</code> (or whichever port Claude picked). Retry <code>/mcp</code>.</p>
    </details>
    <details>
      <summary>Claude shows "Failed to connect" instead of "Needs authentication"</summary>
      <p>The OAuth discovery handshake didn't complete. Verify the URL is exact (<code>/mcp</code> at the end, HTTPS). If the URL is right, check that <a href="/.well-known/oauth-authorization-server">/.well-known/oauth-authorization-server</a> returns JSON in your browser — if it's a 404 or HTML page, the server isn't reachable.</p>
    </details>
    <details>
      <summary>401 from /mcp after I thought I authorized</summary>
      <p>Token was revoked (someone clicked Revoke on Settings), your user was suspended, or your user's role dropped below <code>reader</code>. Reauthorize via <code>/mcp</code> again; if that fails, an admin should check your row in <strong>Settings → Users &amp; invites</strong>.</p>
    </details>
    <details>
      <summary>403 Forbidden on a specific tool</summary>
      <p>You're authenticated but lack the role for that tool. Reads need <code>reader</code>; writes need <code>writer</code>; deletes/merges need <code>admin</code>. Ask an admin to upgrade your role.</p>
    </details>
    <details>
      <summary>Service account token isn't working</summary>
      <p>Bearer header missing, token revoked, or service account suspended. <code>curl -i -X POST https://mycelium.devgo.dev/mcp -H "Authorization: Bearer myc_…" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"x","version":"0"}}}'</code> should return 200. 401 = token wrong or revoked.</p>
    </details>
    <details>
      <summary>Changes I make via MCP don't show in the UI</summary>
      <p>The UI caches the substrate dump per page load. Refresh to pick up new writes.</p>
    </details>
  </div>

  <h2>Endpoint reference</h2>
  <div class="card">
    <div class="endpoint-grid">
      <span>MCP endpoint</span><code id="ref-url">loading…</code>
      <span>Transport</span><span>streamable HTTP (MCP 2025-03-26)</span>
      <span>Auth</span><span id="ref-auth">loading…</span>
    </div>
  </div>
</main>

<script>
  // Tab switching
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.toggle('active', p.dataset.panel === id));
    });
  });

  // Copy buttons
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.copyText
        || document.getElementById(btn.dataset.copy)?.textContent
        || '';
      navigator.clipboard.writeText(text);
      const orig = btn.textContent;
      btn.textContent = 'Copied';
      setTimeout(() => { btn.textContent = orig; }, 1500);
    });
  });

  // Probe auth state — /api/me 401s when not signed in, returns the
  // principal when signed in. Used to choose top-bar links.
  function _navLink(href, text) {
    const a = document.createElement('a');
    a.href = href;
    a.textContent = text;
    return a;
  }
  fetch('/api/me', { headers: { accept: 'application/json' } })
    .then(r => r.ok ? r.json() : null)
    .then(me => {
      const nav = document.getElementById('top-nav');
      while (nav.firstChild) nav.removeChild(nav.firstChild);
      if (me && !me.synthetic) {
        nav.appendChild(_navLink('/ui/#/settings', 'Manage tokens'));
        nav.appendChild(document.createTextNode(' · '));
        nav.appendChild(_navLink('/ui/', 'View substrate'));
      } else {
        nav.appendChild(_navLink('/auth/login?next=%2Fconnect', 'Sign in'));
      }
    });

  // Pull live server info
  fetch('/api/server-info', { headers: { accept: 'application/json' } })
    .then(r => {
      if (!r.ok) throw new Error('server-info → ' + r.status);
      return r.json();
    })
    .then(info => {
      const url = info.mcp_url;
      // Default snippets: no token — the client picks up the OAuth
      // flow via /.well-known/oauth-protected-resource and prompts
      // the user in their browser. Tokenful variants live in the
      // service-account tab for callers that can't do interactive
      // sign-in.
      document.getElementById('cc-add').textContent =
        `claude mcp add --transport http mycelium ${url}`;
      document.getElementById('cd-url').textContent = url;
      document.getElementById('cd-cfg').textContent = JSON.stringify({
        mcpServers: {
          mycelium: {
            type: 'http',
            url: url,
          },
        },
      }, null, 2);
      document.getElementById('cc-add-token').textContent =
        `claude mcp add --transport http mycelium ${url} \\\\\n` +
        `  --header "Authorization: Bearer YOUR_TOKEN"`;
      document.getElementById('cd-cfg-token').textContent = JSON.stringify({
        mcpServers: {
          mycelium: {
            type: 'http',
            url: url,
            headers: { Authorization: 'Bearer YOUR_TOKEN' },
          },
        },
      }, null, 2);
      document.getElementById('raw-url').textContent = url;
      document.getElementById('ref-url').textContent = url;
      document.getElementById('ref-auth').textContent = info.auth_enabled
        ? 'required (bearer or session cookie)'
        : 'disabled — local mode';
      if (!info.auth_enabled) {
        document.getElementById('auth-disabled').style.display = 'block';
      }
    })
    .catch(err => {
      const e = document.getElementById('boot-error');
      e.style.display = 'block';
      e.textContent = 'Could not load server info: ' + err.message
        + '. The URL snippets below will be wrong — substitute the actual server URL manually.';
    });
</script>
</body>
</html>
"""
