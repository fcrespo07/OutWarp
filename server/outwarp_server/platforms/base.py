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

    # ── enrolment listener ───────────────────────────────────────────────────
    # The token-redemption endpoint (enroll_server.py) has to run as long as
    # the transport does, or every enrolment .owcfg is dead on arrival. Where
    # a ServerManager process is what keeps the transport up (Windows, Docker,
    # Kubernetes, the desktop GUI) it hosts the listener itself and these are
    # no-ops. A native systemd install has no such process — the wizard leaves
    # only units behind — so Linux overrides them with a unit of its own.

    @property
    def os_managed_transport(self) -> bool:
        """True when wstunnel and WireGuard run as OS services this platform
        can restart on its own (systemd), so a process that does not own the
        wstunnel subprocess — the web panel, the GUI next to a headless
        install — can still offer a restart. False where the transport is a
        subprocess of some ServerManager (Windows, Docker, Kubernetes): from
        another process there is nothing safe to drive."""
        return False

    @property
    def manages_enroll_service(self) -> bool:
        """True when this platform runs the listener as an OS service of its
        own (so status/doctor have a unit to report on)."""
        return False

    def install_enroll_service(self, exec_start: str) -> None:  # noqa: B027
        """Register the enrolment listener as an OS service running `exec_start`."""

    def uninstall_enroll_service(self) -> None:  # noqa: B027
        pass

    def is_enroll_running(self) -> bool:
        """Whether the OS-managed listener is up; False where none is installed."""
        return False

    def restart_enroll_service(self) -> None:  # noqa: B027
        pass

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
    def restart_wg(self, interface: str = "wg0", subnet: str | None = None) -> None:
        """Bring the WireGuard interface fully down and up again.

        Required when PostUp/PostDown rules in the config have changed —
        `wg syncconf` does a hot reload but doesn't re-run those scripts.

        `subnet` only matters on Windows: WireGuard for Windows has no
        PostUp/PostDown, so `prepare_system()`'s NAT is torn down and
        recreated by hand around the restart (FIX-07) rather than living
        inside the WG lifecycle the way Linux's PostUp/PostDown do. Callers
        that have a `ServerConfig` in scope should always pass `config.subnet`
        — omitting it is only safe on platforms where WG owns its own
        networking symmetrically.
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
        """OS-level setup: IP forwarding, NAT, firewall rules.

        Idempotent and called on every server start (ServerManager._do_start),
        not just once after the setup wizard — Windows' NAT in particular does
        not survive a `restart_wg()` on its own (see FIX-07) and has to be
        reconciled here every time. The default implementation is a no-op
        (Linux uses PostUp hooks instead, which are symmetric by construction).
        """

    def reconcile(
        self,
        conf_text: str,
        *,
        interface: str | None = None,
        subnet: str = "",
        wss_port: int = 0,
        force_restart: bool = False,
    ) -> None:
        """Idempotently bring WireGuard, and the OS-level network state it
        depends on (NAT, IP forwarding, the wstunnel firewall rule), in line
        with `conf_text`. Safe to call on every server start and after every
        config change.

        This replaces having callers sequence `prepare_system()` /
        `install_wg_config()` / `restart_wg()` by hand — getting that order
        wrong is exactly how FIX-07 happened (Windows silently dropped its
        NAT rule on every reload). One entry point that always calls
        `prepare_system()` first closes that class of bug generically instead
        of per call site (CONCEPTO-E in docs/history/OutWarp-fix-plan.md).

        `force_restart` asks for a full teardown+reinstall even if the
        interface is already active — needed when a change (e.g. the WG
        listen port) can't be applied by a hot reload alone.
        """
        iface = interface or self.wg_interface_name()
        self.prepare_system(subnet, wss_port)
        if force_restart and self.is_wg_active(iface):
            self.restart_wg(iface, subnet=subnet)
        else:
            self.install_wg_config(conf_text, iface)

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
