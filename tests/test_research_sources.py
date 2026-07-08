from __future__ import annotations

import json
import json as _json
import subprocess
from pathlib import Path

import pytest
import pytest as _pytest

from mycelium.research.sources import (
    Source,
    SourceError,
    fetch,
    get_source,
    load_sources,
)


def test_load_sources_parses_json():
    env = {
        "MYCELIUM_SOURCES": json.dumps(
            {
                "acme-api": {
                    "owner": "acme",
                    "repo": "api",
                    "ref": "main",
                    "token_env": "ACME_GH_TOKEN",
                },
                "docs": {"owner": "acme", "repo": "docs"},
            }
        )
    }

    sources = load_sources(env)

    assert sources == {
        "acme-api": Source(
            name="acme-api",
            owner="acme",
            repo="api",
            ref="main",
            token_env="ACME_GH_TOKEN",
            host="github.com",
        ),
        "docs": Source(
            name="docs",
            owner="acme",
            repo="docs",
            ref=None,
            token_env=None,
            host="github.com",
        ),
    }


def test_load_sources_empty_env_is_empty_dict():
    assert load_sources({}) == {}
    assert load_sources({"MYCELIUM_SOURCES": ""}) == {}


def test_load_sources_malformed_json_raises_source_error():
    with pytest.raises(SourceError, match="not valid JSON"):
        load_sources({"MYCELIUM_SOURCES": "{"})

    with pytest.raises(SourceError, match="JSON object"):
        load_sources({"MYCELIUM_SOURCES": "[]"})

    with pytest.raises(SourceError, match="owner"):
        load_sources({"MYCELIUM_SOURCES": json.dumps({"bad": {"repo": "api"}})})

    with pytest.raises(SourceError, match="repo"):
        load_sources({"MYCELIUM_SOURCES": json.dumps({"bad": {"owner": "acme"}})})


def test_get_source_unknown_name_lists_configured():
    env = {
        "MYCELIUM_SOURCES": json.dumps(
            {
                "acme-api": {"owner": "acme", "repo": "api"},
                "docs": {"owner": "acme", "repo": "docs"},
            }
        )
    }

    with pytest.raises(SourceError) as excinfo:
        get_source("missing", env)

    msg = str(excinfo.value)
    assert "missing" in msg
    assert "acme-api" in msg
    assert "docs" in msg


def test_fetch_builds_shallow_clone_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        dest = Path(cmd[-1])
        dest.mkdir(parents=True)
        (dest / ".git").mkdir()
        (dest / "README.md").write_text("ok")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setenv("ACME_GH_TOKEN", "secret-token")
    monkeypatch.setattr(subprocess, "run", fake_run)

    source = Source(
        name="acme-api",
        owner="acme",
        repo="api",
        ref="main",
        token_env="ACME_GH_TOKEN",
    )
    with fetch(source):
        pass

    cmd = calls[0][0]
    assert cmd[:5] == ["git", "clone", "--depth", "1", "--single-branch"]
    assert "--branch" in cmd
    assert cmd[cmd.index("--branch") + 1] == "main"
    assert "https://x-access-token:secret-token@github.com/acme/api.git" in cmd

    with fetch(Source(name="docs", owner="acme", repo="docs")):
        pass

    cmd = calls[1][0]
    assert "--depth" in cmd
    assert cmd[cmd.index("--depth") + 1] == "1"
    assert "--single-branch" in cmd
    assert "--branch" not in cmd


def test_fetch_success_removes_dot_git_and_cleans_up_after(monkeypatch):
    def fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        dest.mkdir(parents=True)
        (dest / ".git").mkdir()
        (dest / "app.py").write_text("print('ok')")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with fetch(Source(name="api", owner="acme", repo="api")) as dest:
        tmp = dest.parent
        assert dest.exists()
        assert (dest / "app.py").exists()
        assert not (dest / ".git").exists()

    assert not tmp.exists()


def test_fetch_failure_scrubs_token_and_removes_tempdir(monkeypatch):
    temp_roots = []

    def fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        temp_roots.append(dest.parent)
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="fatal: token secret-token rejected"
        )

    monkeypatch.setenv("ACME_GH_TOKEN", "secret-token")
    monkeypatch.setattr(subprocess, "run", fake_run)

    source = Source(name="api", owner="acme", repo="api", token_env="ACME_GH_TOKEN")
    with pytest.raises(SourceError) as excinfo:
        with fetch(source):
            pass

    msg = str(excinfo.value)
    assert "secret-token" not in msg
    assert "***" in msg
    assert temp_roots
    assert not temp_roots[0].exists()

    def timeout_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        temp_roots.append(dest.parent)
        raise subprocess.TimeoutExpired(cmd, 10, stderr="secret-token")

    monkeypatch.setattr(subprocess, "run", timeout_run)

    with pytest.raises(SourceError) as excinfo:
        with fetch(source):
            pass

    msg = str(excinfo.value)
    assert "secret-token" not in msg
    assert "***" in msg
    assert not temp_roots[1].exists()


def test_fetch_missing_token_env_raises_without_value(monkeypatch):
    monkeypatch.delenv("ACME_GH_TOKEN", raising=False)

    source = Source(name="api", owner="acme", repo="api", token_env="ACME_GH_TOKEN")
    with pytest.raises(SourceError) as excinfo:
        with fetch(source):
            pass

    msg = str(excinfo.value)
    assert "ACME_GH_TOKEN" in msg
    assert "x-access-token" not in msg


def test_fetch_no_token_env_uses_plain_https_url(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        dest = Path(cmd[-1])
        dest.mkdir(parents=True)
        (dest / ".git").mkdir()
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with fetch(Source(name="api", owner="acme", repo="api")):
        pass

    assert "https://github.com/acme/api.git" in calls[0]
    assert all("x-access-token" not in part for part in calls[0])


def test_fetch_timeout_does_not_chain_token_bearing_exception(monkeypatch):
    """The SourceError raised on clone timeout must not chain the original
    TimeoutExpired (whose .cmd carries the token-bearing URL)."""
    import subprocess as sp

    from mycelium.research.sources import Source, SourceError, fetch

    monkeypatch.setenv("SECRET_TOKEN_ENV", "s3cr3t-token")

    def fake_run(cmd, **kwargs):
        raise sp.TimeoutExpired(cmd=cmd, timeout=1.0)

    monkeypatch.setattr(sp, "run", fake_run)
    src = Source(name="s", owner="o", repo="r", token_env="SECRET_TOKEN_ENV")
    with pytest.raises(SourceError) as exc_info:
        with fetch(src):
            pass  # pragma: no cover
    assert "s3cr3t-token" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


# --------------------------------------------------------------------------- #
# Input validation (arg-injection / PAT-exfiltration hardening)
# --------------------------------------------------------------------------- #


@_pytest.mark.parametrize(
    "entry",
    [
        {"owner": "-oops", "repo": "r"},  # leading '-' → git option
        {"owner": "o", "repo": "../evil"},  # path escape in repo
        {"owner": "o", "repo": "r", "ref": "--upload-pack=x"},  # option-shaped ref
        {"owner": "o", "repo": "r", "host": "evil.com/@github.com"},  # PAT redirect
        {"owner": "o", "repo": "r", "host": "attacker@evil"},  # userinfo
        {"owner": "o/../x", "repo": "r"},  # slash in owner
    ],
)
def test_load_sources_rejects_injection_shaped_fields(monkeypatch, entry):
    from mycelium.research.sources import SourceError, load_sources

    monkeypatch.setenv("MYCELIUM_SOURCES", _json.dumps({"s": entry}))
    with _pytest.raises(SourceError):
        load_sources()


def test_load_sources_accepts_normal_and_enterprise_hosts(monkeypatch):
    from mycelium.research.sources import load_sources

    monkeypatch.setenv(
        "MYCELIUM_SOURCES",
        _json.dumps(
            {
                "a": {
                    "owner": "acme",
                    "repo": "api",
                    "ref": "release/1.2",
                    "host": "github.com",
                },
                "b": {
                    "owner": "acme",
                    "repo": "web.app",
                    "host": "ghe.corp.example:8443",
                },
            }
        ),
    )
    srcs = load_sources()
    assert srcs["a"].ref == "release/1.2"
    assert srcs["b"].host == "ghe.corp.example:8443"


def test_fetch_fails_closed_when_git_dir_survives(monkeypatch, tmp_path):
    """If .git can't be removed after clone, fetch refuses to yield the
    workspace (the PAT could still be in .git/config)."""
    import subprocess as sp

    from mycelium.research.sources import Source, SourceError, fetch

    def fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        (dest / ".git").mkdir(parents=True)
        (dest / ".git" / "config").write_text(
            "url = https://x-access-token:tok@github.com/o/r"
        )
        (dest / "README.md").write_text("hi")
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sp, "run", fake_run)
    # make .git removal a no-op so the dir "survives"
    import mycelium.research.sources as srcmod

    real_rmtree = srcmod.shutil.rmtree

    def fake_rmtree(path, *a, **k):
        if str(path).endswith(".git"):
            return  # simulate failed removal
        return real_rmtree(path, *a, **k)

    monkeypatch.setattr(srcmod.shutil, "rmtree", fake_rmtree)
    src = Source(name="s", owner="o", repo="r")
    with _pytest.raises(SourceError) as exc:
        with fetch(src):
            pass
    assert ".git" in str(exc.value)
    assert "tok" not in str(exc.value)
