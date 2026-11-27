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


def _client_run_section() -> str:
    run = _section("Run")
    return run[run.index("#if HasClient"):]


def test_installer_registers_the_stale_tunnel_cleanup_at_boot_and_logon() -> None:
    # B-034: without it a tunnel left by an unclean shutdown keeps the machine
    # offline until someone opens OutWarp or kills WireGuard by hand.
    run = _client_run_section()
    for trigger, task in (("ONSTART", "RecoverTunnelBoot"), ("ONLOGON", "RecoverTunnelLogon")):
        line = next(ln for ln in run.splitlines() if task in ln)
        assert f"/SC {trigger}" in line
        assert "/RU SYSTEM" in line
        assert r'{app}\client\outwarp.exe\"" recover-tunnel' in line


def test_uninstaller_removes_the_cleanup_tasks_and_markers() -> None:
    run = _section("UninstallRun")
    assert r'/Delete /F /TN ""OutWarp\RecoverTunnelBoot""' in run
    assert r'/Delete /F /TN ""OutWarp\RecoverTunnelLogon""' in run
    assert r'{commonappdata}\WireGuard\*.outwarp-client' in _section("UninstallDelete")


def test_single_component_editions_skip_the_components_page() -> None:
    """The client-only installer showed a "Select Components" page whose
    drop-down held one entry ("Instalación completa") and nothing to choose."""
    text = _ISS.read_text(encoding="utf-8")
    code = text[text.index("[Code]"):]
    assert "function ShouldSkipPage(PageID: Integer): Boolean;" in code
    guarded = re.search(
        r'#if Edition != "full"\s+if PageID = wpSelectComponents then\s+Result := True;\s+#endif',
        code,
    )
    assert guarded, "only the slim editions may skip the components page"


def test_the_client_is_relaunched_with_its_window_shown() -> None:
    """After an update or a first install the user is waiting for the app;
    minimize_to_tray (on by default) used to bring it back hidden in the tray."""
    entries = re.sub(r"\\\n\s*", " ", _section("Run")).splitlines()  # join `\` continuations
    launches = [ln for ln in entries if "postinstall" in ln and "ClientExeName" in ln]
    assert len(launches) == 2, "interactive launch and auto-update relaunch"
    assert all('Parameters: "--show-window"' in ln for ln in launches)


def _joined(name: str) -> str:
    return re.sub(r"\\\n\s*", " ", _section(name))


def test_no_startup_folder_shortcuts_for_the_elevated_guis() -> None:
    """B-052: both GUIs require elevation and Windows skips elevated programs
    in the Startup folder at logon, so "start at login" never worked."""
    assert "{autostartup}" not in _section("Icons")
    deleted = _section("InstallDelete")
    assert r"{autostartup}\OutWarp Client.lnk" in deleted
    assert r"{autostartup}\OutWarp Server.lnk" in deleted


def test_start_at_login_is_an_elevated_logon_task_matching_the_client() -> None:
    from outwarp.platforms import windows as win

    run = _joined("Run")
    for task, prefix in (("startupclient", "StartClient-"), ("startupserver", "StartServer-")):
        line = next(ln for ln in run.splitlines() if f"Tasks: {task}" in ln and "powershell" in ln)
        assert "-AtLogOn" in line and "-RunLevel Highest" in line
        assert "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries" in line
        assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in line
        assert f"-TaskPath '\\OutWarp\\' -TaskName ('{prefix}' + $env:USERNAME)" in line
    assert win._AUTOSTART_TASK_PREFIX == "\\OutWarp\\StartClient-"


def test_a_silent_update_does_not_re_enable_start_at_login() -> None:
    run = _joined("Run")
    line = next(ln for ln in run.splitlines() if "Tasks: startupclient" in ln)
    assert "Check: ShouldRegisterClientStartup" in line
    code = _ISS.read_text(encoding="utf-8")
    assert "Result := (not IsAutoUpdate) or LegacyClientStartup;" in code


def test_recover_tunnel_tasks_also_run_on_battery() -> None:
    run = _joined("Run")
    line = next(ln for ln in run.splitlines() if "Set-ScheduledTask" in ln)
    assert "-AllowStartIfOnBatteries" in line
    assert "'RecoverTunnelBoot','RecoverTunnelLogon'" in line


def test_uninstaller_removes_start_at_login() -> None:
    run = _joined("UninstallRun")
    assert "$_.TaskName -like 'Start*'" in run and "Unregister-ScheduledTask" in run
    assert r"CurrentVersion\Run /v OutWarp /f" in run
