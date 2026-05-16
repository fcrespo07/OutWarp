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
    # (HKCU\…\Run on Windows, ~/.config/autostart on Linux, LaunchAgents on
    # macOS). `command` is the argv list to run on login — the caller (api.py)
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
