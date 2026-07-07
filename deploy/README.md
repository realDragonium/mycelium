# Deployment

Scripts and templates for hosting Mycelium on a Linux VPS.

| File | Where it runs | What it does |
|---|---|---|
| `install-server.sh` | the VPS, once, as root | Installs nginx/certbot/build tools, creates the `mycelium` user, sets up directories, drops in a systemd unit and an nginx site template. |
| `deploy.sh` | your laptop, every deploy | rsyncs source to `/opt/mycelium`, runs `uv sync --frozen`, restarts the service. |

Full step-by-step setup: [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
Auth0 setup: [../docs/AUTH0.md](../docs/AUTH0.md).
Inviting users / minting tokens: [../docs/USERS.md](../docs/USERS.md).
