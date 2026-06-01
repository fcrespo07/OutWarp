"""Tests for ``outwarp.uninstall`` — the cleanup logic behind
``outwarp-cli uninstall``. We mainly care about the path-detection helpers
because that's where the 0.4.x → 0.5.x pipx migration introduced regressions
(both layouts can coexist on a machine that upgraded in place)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp import uninstall


@pytest.mark.skipif(sys.platform != "linux", reason="Linux path layout")
def test_client_prefixes_detects_both_legacy_and_pipx() -> None:
    """A machine that upgraded 0.4.x → 0.5.0 in place will have both
    /opt/outwarp-client (left behind by the legacy installer because
    migrate_legacy_install couldn't free the kernel-held inodes) AND
    /opt/pipx/venvs/outwarp-client (created by pipx). We must clean both."""
    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if str(self) in {"/opt/outwarp-client", "/opt/pipx/venvs/outwarp-client"}:
            return True
        return real_exists(self)

    with patch.object(Path, "exists", fake_exists):
        prefixes = uninstall._client_prefixes()

    assert Path("/opt/pipx/venvs/outwarp-client") in prefixes
    assert Path("/opt/outwarp-client") in prefixes


@pytest.mark.skipif(sys.platform != "linux", reason="Linux path layout")
def test_client_prefixes_empty_when_nothing_installed() -> None:
    """Fresh machine — neither path should be reported."""
    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if str(self) in {"/opt/outwarp-client", "/opt/pipx/venvs/outwarp-client"}:
            return False
        return real_exists(self)

    with patch.object(Path, "exists", fake_exists):
        assert uninstall._client_prefixes() == []


@pytest.mark.skipif(sys.platform != "linux", reason="Linux path layout")
def test_client_shims_detects_all_known_entry_points() -> None:
    """0.4.x shipped three shims (outwarp, outwarp-cli, outwarp-uninstall);
    0.5.0 only ships outwarp-cli but in-place upgrades leave the old shims
    behind. The uninstall pass must reach all three."""
    real_exists = Path.exists
    targets = {
        "/usr/local/bin/outwarp",
        "/usr/local/bin/outwarp-cli",
        "/usr/local/bin/outwarp-uninstall",
    }

    def fake_exists(self: Path) -> bool:
        if str(self) in targets:
            return True
        return real_exists(self)

    with patch.object(Path, "exists", fake_exists):
        shims = {str(s) for s in uninstall._client_shims()}
    assert shims == targets


@pytest.mark.skipif(sys.platform != "linux", reason="Linux path layout")
def test_extra_artifacts_includes_helper_and_sudoers() -> None:
    """0.5.0 install.sh writes /usr/local/libexec/outwarp-priv (privileged
    helper used by the unprivileged outwarp-cli) plus /etc/sudoers.d/outwarp.
    Both must be cleaned — leaving the sudoers file behind is a security
    smell (NOPASSWD rule pointing at a now-missing binary)."""
    real_exists = Path.exists
    targets = {
        "/usr/local/libexec/outwarp-priv",
        "/etc/sudoers.d/outwarp",
    }

    def fake_exists(self: Path) -> bool:
        if str(self) in targets:
            return True
        return real_exists(self)

    with patch.object(Path, "exists", fake_exists):
        extras = {str(p) for p in uninstall._extra_artifacts()}
    assert targets.issubset(extras)
