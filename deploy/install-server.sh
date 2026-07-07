#!/usr/bin/env bash
# Server-side bootstrap. Run ONCE, as root, on a fresh Ubuntu 22.04+
# / Debian 12+ VPS to install everything Mycelium needs.
#
# What it does (idempotent — safe to re-run):
#   - apt-installs build prerequisites, nginx, certbot, curl
#   - creates a `mycelium` system user (no shell, no password)
#   - creates /opt/mycelium (source) and /var/lib/mycelium (data + history)
#   - installs uv (Astral's Python package manager) for the mycelium user
#   - drops in the systemd unit and an nginx site, both DISABLED by default
#     so you can edit them before flipping them on
#
# What it does NOT do (deliberate — needs human decisions):
#   - obtain TLS certificates (you'll run certbot after picking a domain)
#   - write the .env file (you'll fill in Auth0 + session secret)
#   - start the service (you'll do that after both of the above)
#
# Usage:
#   curl -fsSL https://your-host/install-server.sh | sudo bash
#   OR
#   sudo bash install-server.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

SERVICE_USER="mycelium"
APP_DIR="/opt/mycelium"
DATA_DIR="/var/lib/mycelium"
ENV_FILE="/etc/mycelium.env"

echo "==> apt update & install"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl ca-certificates git \
    build-essential pkg-config \
    nginx certbot python3-certbot-nginx \
    rsync

echo "==> create system user '$SERVICE_USER'"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$APP_DIR" "$SERVICE_USER"
fi

echo "==> create directories"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$APP_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$DATA_DIR"

echo "==> install uv for $SERVICE_USER"
# uv lives in ~/.local/bin once installed; keep the install scoped to the
# mycelium user so a system-wide Python upgrade doesn't break the venv.
sudo -u "$SERVICE_USER" bash -lc '
    if ! command -v uv >/dev/null 2>&1 && ! test -x "$HOME/.local/bin/uv"; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
'

echo "==> place systemd unit"
cat >/etc/systemd/system/mycelium.service <<'UNIT'
[Unit]
Description=Mycelium HTTP / MCP server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mycelium
Group=mycelium
WorkingDirectory=/opt/mycelium
EnvironmentFile=/etc/mycelium.env
# The `mycelium` user's home IS /opt/mycelium (set by useradd above),
# so uv installs to /opt/mycelium/.local/bin — not /home/mycelium/...
Environment=PATH=/opt/mycelium/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/opt/mycelium
# uv stores its cache under $HOME/.cache by default, but the source
# dir is mounted read-only by ProtectSystem=strict below. Redirect
# the cache into the data dir so writes land in a permitted path.
Environment=UV_CACHE_DIR=/var/lib/mycelium/.uv-cache

# Bind to loopback only — nginx terminates TLS and proxies in.
Environment=MYCELIUM_HTTP_HOST=127.0.0.1
Environment=MYCELIUM_HTTP_PORT=8765
Environment=MYCELIUM_DATA_DIR=/var/lib/mycelium

ExecStart=/opt/mycelium/.local/bin/uv run mycelium-http

Restart=on-failure
RestartSec=3

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/mycelium
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=false
RestrictRealtime=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
# Don't enable yet — wait until the env file is in place.

echo "==> seed env file template (only if missing)"
if [[ ! -f "$ENV_FILE" ]]; then
    cat >"$ENV_FILE" <<'ENV'
# Mycelium runtime environment. Restart the service after changes:
#   systemctl restart mycelium

# --- public hostnames -----------------------------------------------
# Comma-separated host[:port] values that the MCP transport should
# accept on its Host header. Required because FastMCP defaults to
# localhost-only DNS-rebinding protection. Add every domain a real
# client might use (apex + ports as needed).
#   MYCELIUM_ALLOWED_HOSTS=mycelium.example.com,mycelium.example.com:443
MYCELIUM_ALLOWED_HOSTS=

# --- toggle ---------------------------------------------------------
# Set to "on" once you're ready to require login. Default "off" lets
# the service run with no auth (any caller becomes local-admin).
MYCELIUM_AUTH=off

# --- session cookie -------------------------------------------------
# Required when MYCELIUM_AUTH=on. Generate one with:
#   openssl rand -base64 48
MYCELIUM_SESSION_SECRET=

# --- OIDC / Auth0 ---------------------------------------------------
# See docs/AUTH0.md for how to obtain these.
MYCELIUM_OIDC_ISSUER=
MYCELIUM_OIDC_CLIENT_ID=
MYCELIUM_OIDC_CLIENT_SECRET=
# Must match the callback URL configured in Auth0:
#   https://your-domain.example.com/auth/callback
MYCELIUM_OIDC_REDIRECT_URI=

# --- bootstrap admin ------------------------------------------------
# First OIDC login with this email becomes admin (only when no admin
# exists yet). Leave blank if you'll seed an admin some other way.
MYCELIUM_BOOTSTRAP_ADMIN_EMAIL=
ENV
    chmod 0640 "$ENV_FILE"
    chown root:"$SERVICE_USER" "$ENV_FILE"
fi

echo "==> place nginx site template (disabled by default)"
cat >/etc/nginx/sites-available/mycelium <<'NGINX'
# Replace `mycelium.example.com` with your domain and run
# `certbot --nginx -d mycelium.example.com` to obtain a cert; certbot
# will rewrite this file to add the SSL block.

server {
    listen 80;
    listen [::]:80;
    server_name mycelium.example.com;

    # SSE / MCP streaming endpoint — disable buffering so events flush
    # to the client as the server emits them.
    location /mcp {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
        chunked_transfer_encoding on;
    }

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

# Don't enable the site yet — operator should edit the domain first.

echo
echo "==> bootstrap complete"
echo
echo "Next steps (see docs/DEPLOYMENT.md for the full guide):"
echo "  1. rsync your source to $APP_DIR (use deploy/deploy.sh from your laptop)"
echo "  2. edit $ENV_FILE  — at minimum, set MYCELIUM_SESSION_SECRET and"
echo "     decide whether to flip MYCELIUM_AUTH to 'on'"
echo "  3. edit /etc/nginx/sites-available/mycelium — set your domain"
echo "  4. ln -s /etc/nginx/sites-available/mycelium /etc/nginx/sites-enabled/"
echo "     nginx -t && systemctl reload nginx"
echo "  5. certbot --nginx -d your-domain.example.com"
echo "  6. systemctl enable --now mycelium"
echo
