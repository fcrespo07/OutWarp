"""Tests for ``outwarp.uninstall`` — the cleanup logic behind
``outwarp uninstall``. We mainly care about the path-detection helpers
because that's where the 0.4.x → 0.5.x pipx migration introduced regressions
(both layouts can coexist on a machine that upgraded in place)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """0.4.x shipped three shims (outwarp, outwarp, outwarp-uninstall);
    0.5.0 only ships outwarp but in-place upgrades leave the old shims
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
    helper used by the unprivileged outwarp) plus /etc/sudoers.d/outwarp.
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


# --- FIX-06a: the kill pattern must never match the uninstall process itself ---

@pytest.mark.skipif(sys.platform == "win32", reason="Linux pkill pattern")
def test_kill_pattern_does_not_match_the_uninstall_command_itself() -> None:
    """`pkill -f outwarp` used to match this very `outwarp uninstall`
    process (pkill only excludes its own PID, never its caller's) and kill it
    with no SIGTERM handler on this path — before a single file was removed."""
    with patch("subprocess.run") as run:
        uninstall._kill_running()
    pattern = run.call_args.args[0][2]  # ["pkill", "-f", <pattern>]
    assert not re.search(pattern, "/usr/bin/python3 /usr/local/bin/outwarp uninstall")
    assert not re.search(pattern, "/usr/bin/python3 /usr/local/bin/outwarp uninstall -y")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux pkill pattern")
@pytest.mark.parametrize("subcommand", ["gui", "connect", "tui", "daemon"])
def test_kill_pattern_still_matches_a_live_client_process(subcommand: str) -> None:
    """The fix must not overcorrect into matching nothing — a running tray/
    TUI/daemon instance still has to go before its files are deleted."""
    with patch("subprocess.run") as run:
        uninstall._kill_running()
    pattern = run.call_args.args[0][2]
    assert re.search(pattern, f"/usr/bin/python3 /usr/local/bin/outwarp {subcommand}")


# --- FIX-06b: releasing the kill switch / tunnel must not depend on a live process ---

def test_tunnel_name_from_config_none_when_nothing_imported() -> None:
    with patch("outwarp.config.default_config_path", return_value=Path("/nonexistent")):
        assert uninstall._tunnel_name_from_config() is None


def _run_main_with(monkeypatch, plat: MagicMock, tunnel_name: str | None) -> list[str]:
    """Run uninstall.main(['-y']) with everything except the network-state
    release and _kill_running mocked out, and return the call order of the
    interesting mocks (so tests can assert both "was it called" and "in what
    order relative to _kill_running")."""
    calls: list[str] = []
    monkeypatch.setattr(uninstall, "_require_admin", lambda: None)
    monkeypatch.setattr(uninstall, "_config_dir", lambda: None)
    monkeypatch.setattr(uninstall, "_startup_shortcut", lambda: None)
    monkeypatch.setattr(uninstall, "_desktop_shortcut", lambda: None)
    monkeypatch.setattr(uninstall, "_client_prefixes", lambda: [])
    monkeypatch.setattr(uninstall, "_client_shims", lambda: [])
    monkeypatch.setattr(uninstall, "_extra_artifacts", lambda: [])
    monkeypatch.setattr(uninstall, "_tunnel_name_from_config", lambda: tunnel_name)
    monkeypatch.setattr(uninstall, "_kill_running", lambda: calls.append("kill_running"))
    monkeypatch.setattr("outwarp.platforms.get_platform", lambda: plat)

    plat.release_kill_switch.side_effect = lambda: calls.append("release_kill_switch")
    plat.uninstall_wg_tunnel.side_effect = lambda name: calls.append(f"uninstall_wg_tunnel:{name}")

    ret = uninstall.main(["--yes"])
    assert ret == 0
    return calls


def test_uninstall_releases_kill_switch_before_killing_processes(monkeypatch) -> None:
    plat = MagicMock()
    calls = _run_main_with(monkeypatch, plat, tunnel_name=None)
    assert calls == ["release_kill_switch", "kill_running"]
    plat.uninstall_wg_tunnel.assert_not_called()


def test_uninstall_tears_down_the_tunnel_when_a_profile_is_imported(monkeypatch) -> None:
    plat = MagicMock()
    calls = _run_main_with(monkeypatch, plat, tunnel_name="OutWarp")
    assert calls == ["release_kill_switch", "uninstall_wg_tunnel:OutWarp", "kill_running"]


def test_uninstall_still_completes_if_kill_switch_release_fails(monkeypatch) -> None:
    """A firewall-layer failure here is surfaced as a warning (exit 1), not a
    crash that aborts before config/shims/venv cleanup even starts."""
    plat = MagicMock()
    plat.release_kill_switch.side_effect = RuntimeError("nftables not installed")
    monkeypatch.setattr(uninstall, "_require_admin", lambda: None)
    monkeypatch.setattr(uninstall, "_config_dir", lambda: None)
    monkeypatch.setattr(uninstall, "_startup_shortcut", lambda: None)
    monkeypatch.setattr(uninstall, "_desktop_shortcut", lambda: None)
    monkeypatch.setattr(uninstall, "_client_prefixes", lambda: [])
    monkeypatch.setattr(uninstall, "_client_shims", lambda: [])
    monkeypatch.setattr(uninstall, "_extra_artifacts", lambda: [])
    monkeypatch.setattr(uninstall, "_tunnel_name_from_config", lambda: None)
    monkeypatch.setattr(uninstall, "_kill_running", lambda: None)
    monkeypatch.setattr("outwarp.platforms.get_platform", lambda: plat)

    ret = uninstall.main(["--yes"])
    assert ret == 1
