# Connect GitHub repositories

Administrators can connect GitHub under **Documentation → Models & GitHub →
Documentation delivery**. Connecting a repository grants this Mycelium instance's
writers permission to publish documentation pull requests. It does not change
Mycelium sign-in or grant other users administrator access.

Choose **Connect GitHub**, install the App on the repositories you want, and
complete GitHub authorization. Back in Mycelium, select a repository and base
branch, then choose **Use repository**. Check the name and file path template
(default `docs/{slug}.md`) and **Save documentation delivery**. Connecting alone
does not publish anything. Open a document and explicitly create/update its PR.

For an existing installation, or after an organization approves an installation
request, choose **Use existing GitHub installation**. The picker only includes
repositories that both the App and your GitHub account can write to. Archived
and disabled repositories are omitted. GitHub access is checked again when
connecting and when reading or publishing a document.

## One-time operator setup

Register a GitHub App for the deployment. Users then connect repositories in the
UI without creating personal tokens or editing environment variables.

Configure the GitHub App with:

- **Callback URL:** `https://MYCELIUM_HOST/api/github/callback`
- **Setup URL:** `https://MYCELIUM_HOST/api/github/setup`
- **Redirect on update:** enabled
- **Request user authorization during installation:** disabled. Mycelium starts
  authorization after verifying the setup state.
- **Webhook:** inactive; this release checks access when it is used.
- **Repository permissions:** Contents **Read and write**, Pull requests **Read
  and write**, and the automatically required Metadata **Read-only**.
- Make the App installable on the accounts/organizations you intend to connect.

Generate a private key, store its PEM file where only the service account can
read it, and set these variables in the server's runtime environment:

```dotenv
MYCELIUM_GITHUB_APP_ID=123456
MYCELIUM_GITHUB_APP_CLIENT_ID=Iv1.example
MYCELIUM_GITHUB_APP_CLIENT_SECRET=<app-client-secret>
MYCELIUM_GITHUB_APP_SLUG=mycelium-docs
MYCELIUM_GITHUB_APP_PRIVATE_KEY_FILE=/etc/mycelium/github-app.pem
MYCELIUM_GITHUB_APP_CALLBACK_URL=https://MYCELIUM_HOST/api/github/callback
```

For the repository's systemd deployment, environment variables belong in
`/etc/mycelium.env`. Restart the service after changing them. Preserve the private
key and client secret separately from instance backups. The callback origin must
match the origin used to open Mycelium; configure the reverse proxy's forwarded
scheme/host correctly. Local testing supports HTTP on localhost or loopback.

The current server runs in one process. Setup state and temporary user tokens
are held in memory for ten minutes, tied to the administrator and browser session.
A restart or an expired setup requires reconnecting. Do not run this flow across
multiple server workers without adding a shared transient credential store.
Installation tokens are generated on demand, restricted to the selected
repository, and never stored in product settings, cookies, or instance archives.

[Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)

## Disconnect, restore, and existing integrations

**Disconnect** disables the repository connection in this Mycelium instance.
It preserves documents, publication history, and existing PRs, and does not
uninstall the App from GitHub. An operation already communicating with GitHub may
finish. To remove GitHub access globally, manage or uninstall the App in GitHub.
Reconnect by authorizing the same installation and choosing the same repository.

Backups include connection references and repository IDs, but restore them as
disconnected. An administrator must reauthorize each connection after restoration.
Existing documents keep their recorded repository, branch, file path, and
connection. Reconnection cannot silently point them at another repository or
another installation. A repository rename or transfer requires operator attention;
Mycelium fails rather than writing to a different repository under the old name.

Environment-backed credentials and GitHub Enterprise destinations continue to
work. GitHub App connections currently support github.com documentation publishing
only; research integrations retain their existing credential configuration.
