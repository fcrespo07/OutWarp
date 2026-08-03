from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PlatformError(RuntimeError):
    pass


class PrerequisiteStatus(Enum):
    OK = "ok"
    # The required OS components are now installed but the kernel/driver only
    # finishes loading after a reboot. The caller must abort and ask the user
    # to reboot before re-running setup.
    REBOOT_REQUIRED = "reboot_required"
    # Auto-bootstrap failed: the prerequisite cannot be installed from here.
    # Common on a damaged Windows image (missing system binaries) or where
    # Defender quarantined the provider DLL. The caller surfaces `remediation`
    # to the user.
    FAILED = "failed"


@dataclass
class PrerequisiteResult:
    status: PrerequisiteStatus
    detail: str = ""
    remediation: str = ""

    @property
    def ok(self) -> bool:
        return self.status is PrerequisiteStatus.OK


class ServerPlatform(ABC):
    """Abstract interface for server-side service management."""

    @abstractmethod
    def install_wstunnel_service(self, exec_start: str) -> None:
        """Register wstunnel as an OS service running `exec_start`.

        The caller renders the argv with
        ``server_manager.build_wstunnel_command`` so the service and the
        foreground process can never disagree about how wstunnel is invoked.
        """
        ...

    @abstractmethod
    def uninstall_wstunnel_service(self) -> None:
        ...

    @abstractmethod
    def is_wstunnel_running(self) -> bool:
        ...

    @abstractmethod
    def restart_wstunnel_service(self) -> None:
        ...

    @abstractmethod
    def install_wg_config(self, conf_text: str, interface: str = "wg0") -> None:
        ...

    @abstractmethod
    def reload_wg(self, interface: str = "wg0") -> None:
        ...

    @abstractmethod
    def is_wg_active(self, interface: str = "wg0") -> bool:
        ...

    @abstractmethod
    def restart_wg(self, interface: str = "wg0") -> None:
        """Bring the WireGuard interface fully down and up again.

        Required when PostUp/PostDown rules in the config have changed —
        `wg syncconf` does a hot reload but doesn't re-run those scripts.
        """
        ...

    @abstractmethod
    def uninstall_wg_config(self, interface: str = "wg0") -> None:
        ...

    @abstractmethod
    def wg_config_dir(self) -> Path:
        ...

    def wg_interface_name(self) -> str:
        """The name of the WireGuard interface this platform manages.

        Linux uses 'wg0' (wg-quick convention); Windows uses
        'OutWarp-Server' (wireguard.exe service name). Callers that need
        to query the running interface should use this instead of
        hardcoding 'wg0'.
        """
        return "wg0"

    def prepare_system(self, subnet: str, wss_port: int) -> None:  # noqa: B027
        """One-time OS-level setup: IP forwarding, NAT, firewall rules.

        Called once after first-run setup wizard completes.
        The default implementation is a no-op (Linux uses PostUp hooks).
        """

    def check_prerequisites(self) -> PrerequisiteResult:
        """Verify (and, where possible, install) OS-level prerequisites.

        Called at the start of the setup wizard AND on every server start, so
        the server never silently runs in a broken state. Default returns OK
        — Linux's iptables NAT works on any kernel ≥ 2.4 and needs no probe.

        Windows overrides this: it probes the MSFT_NetNat WMI provider and,
        if missing, attempts to enable the 'Containers' feature (then
        'HypervisorPlatform' as fallback). Returning REBOOT_REQUIRED or
        FAILED is the contract for callers to abort with a clear message.
        """
        return PrerequisiteResult(status=PrerequisiteStatus.OK)

    def install_prefix(self) -> Path | None:
        """Where the OS installer puts the venv/bundle. None if not applicable."""
        return None

    def bin_link(self) -> Path | None:
        """Where the OS installer puts the CLI symlink. None if not applicable."""
        return None
