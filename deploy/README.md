# Deployment

Scripts and templates for hosting Mycelium on a Linux VPS.

| File | Where it runs | What it does |
|---|---|---|
| `install-server.sh` | the VPS, once, as root | Installs nginx/certbot/build tools, creates the `mycelium` user, sets up directories, drops in a systemd unit and an nginx site template. |
| `deploy.sh` | your laptop, every deploy | rsyncs source to a staging dir on the server and runs `release.sh` there. |
| `release.sh` | the VPS, called by `deploy.sh` | stops the service, snapshots `/var/lib/mycelium` to `/var/lib/mycelium-snapshots/<UTC time>/data/`, recording the build that wrote it in `BUILD` beside it (newest 5 kept; the deploy aborts if the snapshot fails), installs the build, runs `uv sync --frozen` (on failure the previous build is put back and started), starts the service. |
| `myc` | the VPS, `/usr/local/bin/myc` | runs `mycelium` CLI commands against the production data dir. |

Full step-by-step setup: [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
Auth0 setup: [../docs/AUTH0.md](../docs/AUTH0.md).
Inviting users / minting tokens: [../docs/USERS.md](../docs/USERS.md).
