from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

from .base import Platform, PlatformError

log = logging.getLogger(__name__)

_WIREGUARD_EXE = Path(r"C:\Program Files\WireGuard\wireguard.exe")
# C:\ProgramData\WireGuard is where wireguard.exe /installtunnelservice expects
# to find conf files — the service runs as LocalSystem and cannot access %LOCALAPPDATA%.
_WG_CONF_DIR = Path(r"C:\ProgramData\WireGuard")
_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# HKCU is the right hive for per-user autostart: HKLM\…\Run would require
# admin to write and would launch OutWarp for every user on the box.
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_VALUE = "OutWarp"

# Kill switch = the firewall profile's default *outbound* action flipped to
# Block, plus two allow rules: outbound to the endpoint(s) so wstunnel can
# reconnect, and outbound *from* the tunnel's own address so packets headed
# into the WireGuard adapter still flow (netsh cannot scope a rule to an
# adapter by name; the local address is the stable handle). An explicit
# "block all outbound" rule cannot be used for this: Windows evaluates block
# rules before allow rules regardless of specificity, so it would have
# blocked the very endpoint traffic the allow rule was meant to let through.
# Loopback is exempt from WFP filtering and stays reachable.
_KILL_RULE_ALLOW = "OutWarp-KillSwitch-Allow"
_KILL_RULE_TUNNEL = "OutWarp-KillSwitch-Tunnel"
# Pre-0.12 installs used a blanket block rule; still deleted on release so an
# upgrade never leaves one behind.
_KILL_RULE_BLOCK = "OutWarp-KillSwitch-Block"
_KILL_RULE_NAMES = (_KILL_RULE_BLOCK, _KILL_RULE_TUNNEL, _KILL_RULE_ALLOW)


def _set_default_outbound(action: str) -> subprocess.CompletedProcess:
    return _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"Set-NetFirewallProfile -All -DefaultOutboundAction {action}",
    ])


def _quote_arg(arg: str) -> str:
    """Wrap an argv item in double quotes if it contains a space, escaping any
    embedded quote. Windows' command line is a single string, so the Run-key
    value has to be one — properly quoted so a path like `C:\\Program Files\\…`
    doesn't get split."""
    if not arg or any(c in arg for c in ' \t"'):
        return '"' + arg.replace('"', r'\"') + '"'
    return arg


def _run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(*args, capture_output=True, text=True,
                          creationflags=_NO_WINDOW, **kwargs)


# Windows SCM service state codes (SERVICE_STATUS.dwCurrentState).
# Locale-independent; the state *name* in `sc query` output is translated
# (e.g. "EN EJECUCIÓN" on Spanish Windows) but the numeric code is not.
_SC_STATE_RUNNING = 4
# Captures lines of the form `<key> : <digit>  <name>` from `sc query` output.
# Matches a single digit (state codes are 1-7) followed by a non-digit,
# non-'(' character — that excludes TYPE lines (multi-digit, e.g. 30) and
# WIN32_EXIT_CODE lines (digit followed by "(0x...)").
_SC_STATE_LINE_RE = re.compile(r":\s+(\d)\s+[^\d(]")


def _sc_service_state(name: str) -> int | None:
    """Return the WinAPI service-state code for a service, or None if the
    service doesn't exist. Locale-independent."""
    result = _run(["sc", "query", name])
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        m = _SC_STATE_LINE_RE.search(line)
        if m:
            return int(m.group(1))
    return None


class WindowsPlatform(Platform):
    def __init__(self) -> None:
        self._conf_dir = _WG_CONF_DIR

    def install_wg_tunnel(self, name: str, config_text: str) -> Path:
        self._require_wireguard()
        # Clean up any stale service left over from a previous session.
        stale = _run(["sc", "query", f"WireGuardTunnel${name}"])
        if stale.returncode == 0:
            log.warning(
                "Stale WireGuard service found for '%s'; uninstalling before reinstall", name,
            )
            self.uninstall_wg_tunnel(name)

        self._conf_dir.mkdir(parents=True, exist_ok=True)
        conf_path = self._conf_dir / f"{name}.conf"
        conf_path.write_text(config_text, encoding="utf-8")
        result = _run([str(_WIREGUARD_EXE), "/installtunnelservice", str(conf_path)])
        if result.returncode != 0:
            raise PlatformError(
                f"Failed to install WireGuard tunnel '{name}': "
                f"{(result.stderr or result.stdout).strip()}"
            )
        if result.stdout.strip():
            log.info("wireguard /installtunnelservice: %s", result.stdout.strip())
        # /installtunnelservice returns before the service reaches RUNNING; poll until it does
        # so that is_wg_tunnel_active() returns True by the time wstunnel starts.
        deadline = time.monotonic() + 15.0
        last_state: int | None = None
        while time.monotonic() < deadline:
            last_state = _sc_service_state(f"WireGuardTunnel${name}")
            if last_state == _SC_STATE_RUNNING:
                break
            time.sleep(0.25)
        else:
            log.warning("WireGuard service state at timeout: code=%s", last_state)
            _run([str(_WIREGUARD_EXE), "/uninstalltunnelservice", name])
            raise PlatformError(
                f"WireGuard tunnel '{name}' did not reach RUNNING within 15 s — "
                "ensure the client runs as Administrator and WireGuard is fully installed."
            )
        return conf_path

    def uninstall_wg_tunnel(self, name: str) -> None:
        if not _WIREGUARD_EXE.exists():
            return
        _run([str(_WIREGUARD_EXE), "/uninstalltunnelservice", name])
        # /uninstalltunnelservice is async — poll until SCM confirms the service is gone.
        # After 5 s send an explicit sc stop in case the service is stuck in STOP_PENDING.
        deadline = time.monotonic() + 20.0
        nudge_at = time.monotonic() + 5.0
        nudged = False
        while time.monotonic() < deadline:
            if _run(["sc", "query", f"WireGuardTunnel${name}"]).returncode != 0:
                break
            if not nudged and time.monotonic() >= nudge_at:
                log.warning("WireGuard service '%s' still stopping; sending sc stop nudge", name)
                _run(["sc", "stop", f"WireGuardTunnel${name}"])
                nudged = True
            time.sleep(0.25)
        else:
            log.warning("WireGuard tunnel '%s' did not stop within timeout; routes may flap", name)
        conf_path = self._conf_dir / f"{name}.conf"
        conf_path.unlink(missing_ok=True)

    def is_wg_tunnel_active(self, name: str) -> bool:
        return _sc_service_state(f"WireGuardTunnel${name}") == _SC_STATE_RUNNING

    def get_default_gateway(self) -> str:
        result = _run([
            "powershell", "-NoProfile", "-Command",
            "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            "Sort-Object -Property RouteMetric | Select-Object -First 1).NextHop",
        ])
        if result.returncode != 0:
            raise PlatformError(
                f"Failed to query default gateway: {(result.stderr or result.stdout).strip()}"
            )
        gateway = result.stdout.strip()
        if not _IPV4_RE.match(gateway):
            raise PlatformError(f"Could not parse default gateway from output: {result.stdout!r}")
        return gateway

    def add_host_route(self, ip: str, gateway: str) -> None:
        result = _run(["route", "add", ip, "MASK", "255.255.255.255", gateway])
        if result.returncode != 0:
            raise PlatformError(
                f"Failed to add host route {ip} via {gateway}: "
                f"{(result.stderr or result.stdout).strip()}"
            )

    def remove_host_route(self, ip: str) -> None:
        _run(["route", "delete", ip])

    def _require_wireguard(self) -> None:
        if not _WIREGUARD_EXE.exists():
            raise PlatformError(
                f"WireGuard for Windows not found at {_WIREGUARD_EXE}. "
                "Install it from https://www.wireguard.com/install/ and retry."
            )

    # ── autostart ─────────────────────────────────────────────────────────

    def install_autostart(self, command: list[str]) -> None:
        if not command:
            raise PlatformError("install_autostart: empty command")
        import winreg

        value = " ".join(_quote_arg(a) for a in command)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, _AUTOSTART_VALUE, 0, winreg.REG_SZ, value)
        except OSError as exc:
            raise PlatformError(
                f"Failed to register autostart in HKCU\\{_AUTOSTART_KEY}: {exc}"
            ) from exc

    def uninstall_autostart(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, _AUTOSTART_VALUE)
        except FileNotFoundError:
            return  # already absent — nothing to do
        except OSError as exc:
            raise PlatformError(
                f"Failed to unregister autostart from HKCU\\{_AUTOSTART_KEY}: {exc}"
            ) from exc

    def is_autostart_installed(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, _AUTOSTART_VALUE)
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return True

    # ── kill switch ───────────────────────────────────────────────────────

    def engage_kill_switch(
        self, allowlist_ips: list[str], *, tunnel_iface: str, tunnel_address: str,
    ) -> None:
        if not allowlist_ips:
            raise PlatformError(
                "engage_kill_switch refusing to run with an empty allowlist — "
                "the wstunnel reconnect would never get out and the user would "
                "have no way back online."
            )
        if not tunnel_address:
            raise PlatformError(
                "engage_kill_switch needs the tunnel's local address — without it "
                "the switch would block the tunnel's own traffic."
            )
        # Idempotent: wipe any prior rules before adding fresh ones. Safer than
        # editing in place — if a previous run died mid-way and only one rule
        # exists, this brings the set back to a known state.
        self._delete_killswitch_rules()

        for name, scope in (
            (_KILL_RULE_ALLOW, f"remoteip={','.join(allowlist_ips)}"),
            (_KILL_RULE_TUNNEL, f"localip={tunnel_address}"),
        ):
            r = _run([
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={name}", "dir=out", "action=allow", "profile=any",
                "enable=yes", scope,
            ])
            if r.returncode != 0:
                self._delete_killswitch_rules()
                raise PlatformError(
                    f"Failed to add kill-switch rule {name}: "
                    f"{(r.stderr or r.stdout).strip()}"
                )
        policy = _set_default_outbound("Block")
        if policy.returncode != 0:
            # Never leave allow rules around with the policy unchanged — they
            # are harmless, but the switch must not report as engaged.
            self._delete_killswitch_rules()
            raise PlatformError(
                "Failed to set the firewall's default outbound action to Block: "
                f"{(policy.stderr or policy.stdout).strip()}"
            )

    def release_kill_switch(self) -> None:
        # Best-effort and safe when nothing is engaged (called unconditionally
        # on startup to recover from a crash). Restore the outbound default
        # first so the user is back online even if rule deletion fails.
        policy = _set_default_outbound("Allow")
        if policy.returncode != 0:
            log.warning("restoring default outbound action failed: %s",
                        (policy.stderr or policy.stdout).strip())
        self._delete_killswitch_rules()

    def is_kill_switch_engaged(self) -> bool:
        # `show rule` exits 0 when the rule exists, 1 when it does not.
        result = _run([
            "netsh", "advfirewall", "firewall", "show", "rule",
            f"name={_KILL_RULE_TUNNEL}",
        ])
        return result.returncode == 0

    def _delete_killswitch_rules(self) -> None:
        for name in _KILL_RULE_NAMES:
            r = _run([
                "netsh", "advfirewall", "firewall", "delete", "rule",
                f"name={name}",
            ])
            if r.returncode != 0:
                # netsh prints "No rules match the specified criteria." when
                # absent. Ignore that, log anything else.
                msg = (r.stderr or r.stdout).strip()
                if "No rules match" not in msg:
                    log.warning("netsh delete rule %s returned %d: %s",
                                name, r.returncode, msg)
