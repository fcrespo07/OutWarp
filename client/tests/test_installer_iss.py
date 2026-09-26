"""Static checks on the Inno Setup script: CI cannot run the Windows uninstaller."""
from __future__ import annotations

import re
from pathlib import Path

from outwarp.platforms import windows

_ISS = Path(__file__).resolve().parents[2] / "installer" / "windows" / "outwarp.iss"


def _section(name: str) -> str:
    text = _ISS.read_text(encoding="utf-8")
    match = re.search(rf"^\[{name}\]\n(.*?)(?=^\[)", text, re.S | re.M)
    assert match, f"[{name}] missing from outwarp.iss"
    return match.group(1)


def test_uninstaller_releases_the_kill_switch() -> None:
    # B-026: a client that died with the kill switch engaged left the firewall's
    # default outbound action on Block; uninstalling then stranded the machine.
    run = _section("UninstallRun")
    assert "Set-NetFirewallProfile -All -DefaultOutboundAction Allow" in run
    for rule in windows._KILL_RULE_NAMES:
        assert f"delete rule name={rule}" in run


def test_uninstaller_only_resets_the_policy_when_our_rules_exist() -> None:
    run = _section("UninstallRun")
    assert "Get-NetFirewallRule -DisplayName 'OutWarp-KillSwitch-*'" in run
    assert all(name.startswith("OutWarp-KillSwitch-") for name in windows._KILL_RULE_NAMES)


def test_uninstaller_removes_the_client_tunnel_and_its_key() -> None:
    assert "/uninstalltunnelservice OutWarp" in _section("UninstallRun")
    assert r'{commonappdata}\WireGuard\*.conf' in _section("UninstallDelete")
