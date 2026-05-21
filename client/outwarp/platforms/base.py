from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PlatformError(RuntimeError):
    pass


class Platform(ABC):
    @abstractmethod
    def install_wg_tunnel(self, name: str, config_text: str) -> Path:
        ...

    @abstractmethod
    def uninstall_wg_tunnel(self, name: str) -> None:
        ...

    @abstractmethod
    def is_wg_tunnel_active(self, name: str) -> bool:
        ...

    @abstractmethod
    def get_default_gateway(self) -> str:
        ...

    @abstractmethod
    def add_host_route(self, ip: str, gateway: str) -> None:
        ...

    @abstractmethod
    def remove_host_route(self, ip: str) -> None:
        ...

    # ── autostart on user login ───────────────────────────────────────────
    # Each implementation decides where the registration lives
    # (HKCU\…\Run on Windows, ~/.config/autostart on Linux).
    # `command` is the argv list to run on login — the caller (api.py)
    # builds it from sys.executable so frozen and dev-mode launches both work.

    @abstractmethod
    def install_autostart(self, command: list[str]) -> None:
        ...

    @abstractmethod
    def uninstall_autostart(self) -> None:
        ...

    @abstractmethod
    def is_autostart_installed(self) -> bool:
        ...

    # ── kill switch ──────────────────────────────────────────────────────
    # When the user turns on the "kill switch" preference, api.py asks the
    # platform to block all outbound traffic any time the tunnel is down
    # (RECONNECTING / FAILED). `allowlist_ips` are the IPs that must keep
    # outbound access so the wstunnel reconnect itself can succeed — usually
    # ClientConfig.routing.bypass_ips of the active profile.
    #
    # release_kill_switch() must be safe to call when nothing is engaged
    # (called unconditionally on app startup to recover from a crash).

    @abstractmethod
    def engage_kill_switch(self, allowlist_ips: list[str]) -> None:
        ...

    @abstractmethod
    def release_kill_switch(self) -> None:
        ...

    @abstractmethod
    def is_kill_switch_engaged(self) -> bool:
        ...
