"""Which `Host` headers this server answers: its defence against DNS rebinding.

A page on an attacker's domain can re-point that domain at 127.0.0.1. The
browser then treats requests to the local server as same-origin and sends
them with the attacker's hostname in `Host`. With auth off each of those
requests is the local admin, so the hostname is the only thing left to check.

Only hostnames are compared. The attacker chooses the name, not the port.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from . import auth

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def _hostname(value: str) -> str | None:
    try:
        return urlsplit(f"//{value.strip()}").hostname
    except ValueError:
        return None


def configured() -> frozenset[str]:
    """`MYCELIUM_ALLOWED_HOSTS` plus the host of `MYCELIUM_PUBLIC_URL`."""
    entries = (os.environ.get("MYCELIUM_ALLOWED_HOSTS") or "").split(",")
    names = {_hostname(entry) for entry in entries if entry.strip()}
    public = (os.environ.get("MYCELIUM_PUBLIC_URL") or "").strip()
    if public:
        try:
            names.add(urlsplit(public).hostname)
        except ValueError:
            pass
    return frozenset(name for name in names if name)


def enforced() -> bool:
    """Always with auth off. With auth on a rebound page has no credential to
    use, and a deployment that never listed its hostnames must keep working,
    so the check starts once any hostname is configured."""
    return not auth.is_enabled() or bool(configured())


def is_allowed(host_header: str | None) -> bool:
    if host_header is None:
        return False
    name = _hostname(host_header)
    return name is not None and (name in LOOPBACK or name in configured())
