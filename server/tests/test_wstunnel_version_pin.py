"""Every install path must pin the same wstunnel version.

OutWarp pins wstunnel because the WebSocket-upgrade handshake format changed
between releases: a client running a different version than the server fails the
upgrade with HTTP 400 and the tunnel carries no traffic (root-caused 2026-06).
``installer/wstunnel-version.txt`` is the single source of truth; this test
fails if ``server/Dockerfile``, ``installer/linux/install.sh`` or
``scripts/fetch_bundled_binaries.py`` drift from it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _norm(version: str) -> str:
    return version.strip().lstrip("v")


def _pinned() -> str:
    return _norm((REPO_ROOT / "installer" / "wstunnel-version.txt").read_text(encoding="utf-8"))


def test_pin_file_is_a_bare_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _pinned())


def test_dockerfile_arg_matches_pin() -> None:
    text = (REPO_ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^ARG WSTUNNEL_VERSION=(\S+)", text, re.MULTILINE)
    assert match, "ARG WSTUNNEL_VERSION not found in server/Dockerfile"
    assert _norm(match.group(1)) == _pinned()


def test_install_sh_default_matches_pin() -> None:
    text = (REPO_ROOT / "installer" / "linux" / "install.sh").read_text(encoding="utf-8")
    match = re.search(r'WSTUNNEL_VERSION_DEFAULT="([^"]+)"', text)
    assert match, "WSTUNNEL_VERSION_DEFAULT not found in install.sh"
    assert _norm(match.group(1)) == _pinned()


def test_fetch_bundled_binaries_reads_the_pin() -> None:
    path = REPO_ROOT / "scripts" / "fetch_bundled_binaries.py"
    spec = importlib.util.spec_from_file_location("_outwarp_fetch_bundled", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert _norm(module.WSTUNNEL_DEFAULT_VERSION) == _pinned()
