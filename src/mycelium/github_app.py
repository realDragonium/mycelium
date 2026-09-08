"""GitHub App API boundary; access tokens never enter saved settings."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import TypeVar
from urllib.parse import quote, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class GitHubError(ValueError):
    pass


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    app_id: int = Field(gt=0)
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    slug: str = Field(pattern=r"^[a-zA-Z0-9-]+$")
    private_key_file: Path
    callback_url: str

    @classmethod
    def load(cls) -> AppConfig:
        try:
            config = cls(
                app_id=int(os.environ["MYCELIUM_GITHUB_APP_ID"]),
                client_id=os.environ["MYCELIUM_GITHUB_APP_CLIENT_ID"],
                client_secret=SecretStr(
                    os.environ["MYCELIUM_GITHUB_APP_CLIENT_SECRET"]
                ),
                slug=os.environ["MYCELIUM_GITHUB_APP_SLUG"],
                private_key_file=Path(
                    os.environ["MYCELIUM_GITHUB_APP_PRIVATE_KEY_FILE"]
                ),
                callback_url=os.environ["MYCELIUM_GITHUB_APP_CALLBACK_URL"],
            )
            url = urlsplit(config.callback_url)
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                (url.scheme != "https" and not (local and url.scheme == "http"))
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path != "/api/github/callback"
                or not config.client_secret.get_secret_value()
            ):
                raise ValueError
            return config
        except (KeyError, ValueError):
            raise GitHubError(
                "GitHub App setup is incomplete. Ask the server administrator to configure the GitHub App."
            ) from None


class APIModel(BaseModel):
    model_config = ConfigDict(strict=True)


class Account(APIModel):
    login: str


class Permissions(APIModel):
    contents: str = ""
    pull_requests: str = ""

    @property
    def can_publish(self) -> bool:
        return self.contents == "write" and self.pull_requests == "write"

    def require_publish(self) -> None:
        if not self.can_publish:
            raise GitHubError(
                "Grant the GitHub App Contents and Pull requests read/write permissions."
            )


class Installation(APIModel):
    id: int
    app_id: int
    account: Account
    permissions: Permissions
    suspended_at: str | None = None


class Installations(APIModel):
    installations: list[Installation]


class UserPermissions(APIModel):
    push: bool = False
    admin: bool = False


class Repository(APIModel):
    id: int
    name: str
    owner: Account
    default_branch: str
    archived: bool = False
    disabled: bool = False
    permissions: UserPermissions = Field(default_factory=UserPermissions)


class Repositories(APIModel):
    repositories: list[Repository]


class Branch(APIModel):
    name: str


class UserToken(APIModel):
    access_token: SecretStr


class InstallationToken(APIModel):
    token: SecretStr


class RepositoryChoice(APIModel):
    installation_id: int
    repository_id: int
    owner: str
    repo: str
    default_branch: str


T = TypeVar("T", bound=BaseModel)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def app_jwt(config: AppConfig, now: int) -> str:
    try:
        key = serialization.load_pem_private_key(
            config.private_key_file.read_bytes(), None
        )
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError
        header = _encode(b'{"alg":"RS256","typ":"JWT"}')
        payload = _encode(
            json.dumps(
                {"iat": now - 60, "exp": now + 540, "iss": config.client_id}
            ).encode()
        )
        message = f"{header}.{payload}".encode()
        signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        return message.decode() + "." + _encode(signature)
    except (OSError, ValueError, TypeError):
        raise GitHubError(
            "The server's GitHub App private key is unavailable or invalid."
        ) from None


class GitHubClient:
    def __init__(self, client: httpx.Client, config: AppConfig):
        self.client = client
        self.config = config

    def request(
        self,
        method: str,
        path: str,
        token: str,
        model: type[T],
        *,
        body: dict[str, object] | None = None,
    ) -> T:
        try:
            response = self.client.request(
                method,
                "https://api.github.com" + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=body,
            )
            if not response.is_success:
                raise GitHubError(_error(response.status_code))
            return model.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError):
            raise GitHubError(
                "GitHub could not be reached or returned an invalid response. Try again."
            ) from None

    def exchange(self, code: str, verifier: str) -> str:
        try:
            response = self.client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": self.config.callback_url,
                    "code_verifier": verifier,
                },
            )
            if not response.is_success:
                raise GitHubError("GitHub authorization failed. Connect GitHub again.")
            return UserToken.model_validate_json(
                response.content
            ).access_token.get_secret_value()
        except (httpx.HTTPError, ValidationError):
            raise GitHubError(
                "GitHub authorization failed. Connect GitHub again."
            ) from None

    def repositories(
        self, token: str, installation_id: int | None
    ) -> list[RepositoryChoice]:
        result: list[RepositoryChoice] = []
        installations: list[Installation] = []
        for page in range(1, 101):
            batch = self.request(
                "GET",
                f"/user/installations?per_page=100&page={page}",
                token,
                Installations,
            ).installations
            installations.extend(
                item
                for item in batch
                if item.app_id == self.config.app_id
                and (installation_id is None or item.id == installation_id)
            )
            if len(batch) < 100:
                break
        else:
            raise GitHubError(
                "Too many GitHub installations. Connect a specific installation instead."
            )
        for installation in installations:
            if (
                installation.suspended_at is not None
                or not installation.permissions.can_publish
            ):
                continue
            for page in range(1, 101):
                batch = self.request(
                    "GET",
                    f"/user/installations/{installation.id}/repositories?per_page=100&page={page}",
                    token,
                    Repositories,
                ).repositories
                result.extend(
                    RepositoryChoice(
                        installation_id=installation.id,
                        repository_id=repo.id,
                        owner=repo.owner.login,
                        repo=repo.name,
                        default_branch=repo.default_branch,
                    )
                    for repo in batch
                    if repo.permissions.push and not repo.archived and not repo.disabled
                )
                if len(batch) < 100:
                    break
            else:
                raise GitHubError(
                    "Too many repositories. Limit the App installation to the repositories you need."
                )
        return result

    def installation_token(self, installation_id: int, repository_id: int) -> str:
        jwt = app_jwt(self.config, int(time.time()))
        installation = self.request(
            "GET", f"/app/installations/{installation_id}", jwt, Installation
        )
        if (
            installation.app_id != self.config.app_id
            or installation.suspended_at is not None
        ):
            raise GitHubError(
                "This GitHub installation is unavailable. Reconnect GitHub."
            )
        installation.permissions.require_publish()
        return self.request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            jwt,
            InstallationToken,
            body={
                "repository_ids": [repository_id],
                "permissions": {"contents": "write", "pull_requests": "write"},
            },
        ).token.get_secret_value()

    def verify_repository(
        self, token: str, repository_id: int, owner: str, repo: str
    ) -> Repository:
        found = self.request(
            "GET",
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}",
            token,
            Repository,
        )
        if (
            found.id != repository_id
            or found.owner.login.lower() != owner.lower()
            or found.name.lower() != repo.lower()
        ):
            raise GitHubError(
                "The GitHub repository was renamed or replaced. Its saved publishing target cannot be changed automatically."
            )
        if found.archived or found.disabled:
            raise GitHubError("This GitHub repository is archived or disabled.")
        return found

    def verify_branch(self, token: str, owner: str, repo: str, branch: str) -> None:
        self.request(
            "GET",
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/branches/{quote(branch, safe='')}",
            token,
            Branch,
        )


def _error(status: int) -> str:
    if status in {401, 403, 404}:
        return "GitHub access is unavailable. Check repository access, organization approval, and App permissions, then reconnect."
    if status == 422:
        return "GitHub rejected the selected repository or permissions. Refresh the repository list."
    return f"GitHub request failed (HTTP {status}). Try again."


def client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=False)
