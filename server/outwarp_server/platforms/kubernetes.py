from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path

from outwarp_server.config import _atomic_write_secret
from outwarp_server.platforms.base import PlatformError
from outwarp_server.platforms.linux import LinuxServerPlatform, _run

log = logging.getLogger(__name__)

# `outwarp-server [--config-dir DIR] serve` as seen in /proc/*/cmdline, which
# pgrep -f matches against with the interpreter path in front.
_SERVE_PATTERN = r"outwarp-server( .*)? serve( |$)"


class KubernetesServerPlatform(LinuxServerPlatform):
    """Platform for running inside a Kubernetes pod (or plain Docker container).

    wstunnel runs as a subprocess managed by ServerManager — no systemd involved.
    WireGuard is managed directly via wg-quick (pod requires NET_ADMIN + NET_RAW
    capabilities and the wireguard kernel module loaded on the node).
    """

    # ── wstunnel: managed by ServerManager as a subprocess ───────────────────

    def install_wstunnel_service(self, exec_start: str) -> None:
        pass

    def uninstall_wstunnel_service(self) -> None:
        pass

    def is_wstunnel_running(self) -> bool:
        result = subprocess.run(["pgrep", "-x", "wstunnel"], capture_output=True, check=False)
        return result.returncode == 0

    def restart_wstunnel_service(self) -> None:
        # The `serve` process owns wstunnel and the enrolment listener; ask it
        # to reload. This used to be a no-op that `restart` reported as done
        # (B-030). Works under `docker exec` / `kubectl exec` (same PID
        # namespace) and from a sidecar with shareProcessNamespace.
        found = subprocess.run(
            ["pgrep", "-f", _SERVE_PATTERN], capture_output=True, text=True, check=False,
        )
        pids = [int(p) for p in found.stdout.split() if p.isdigit() and int(p) != os.getpid()]
        if not pids:
            raise PlatformError(
                "no `outwarp-server serve` process found in this container; "
                "restart the container (kubectl rollout restart / docker restart)"
            )
        for pid in pids:
            try:
                os.kill(pid, signal.SIGHUP)
            except OSError as exc:
                raise PlatformError(f"could not signal serve (pid {pid}): {exc}") from exc

    # ── enrolment listener: hosted by ServerManager, same as wstunnel ────────

    @property
    def os_managed_transport(self) -> bool:
        return False

    @property
    def manages_enroll_service(self) -> bool:
        return False

    def install_enroll_service(self, exec_start: str) -> None:
        pass

    def uninstall_enroll_service(self) -> None:
        pass

    def is_enroll_running(self) -> bool:
        return False

    def restart_enroll_service(self) -> None:
        # Hosted by `serve`: the SIGHUP from restart_wstunnel_service restarts it.
        pass

    # ── WireGuard: wg-quick directly, no systemd ─────────────────────────────

    @staticmethod
    def _container_conf(conf_text: str) -> str:
        # The shared PostUp template writes `sysctl -w net.ipv4.ip_forward=1`
        # before adding the iptables MASQUERADE rules. /proc/sys is read-only
        # in containers without SYS_ADMIN, so that write fails and wg-quick
        # rolls the whole interface back. The cluster operator is expected to
        # have ip_forward set on the node (or via pod sysctls) — strip the
        # line so the rest of the PostUp runs cleanly with just NET_ADMIN.
        return conf_text.replace("sysctl -w net.ipv4.ip_forward=1; ", "")

    def write_wg_config(self, conf_text: str, interface: str = "wg0") -> None:
        super().write_wg_config(self._container_conf(conf_text), interface)

    def install_wg_config(self, conf_text: str, interface: str = "wg0") -> None:
        conf_text = self._container_conf(conf_text)

        conf_path = self.wg_config_dir() / f"{interface}.conf"
        try:
            # Atomic 0o600 write — the WG config holds the server private key.
            _atomic_write_secret(conf_path, conf_text)
        except OSError as exc:
            raise PlatformError(f"Failed to write WG config: {exc}") from exc

        if self.is_wg_active(interface):
            self.reload_wg(interface)
        else:
            try:
                _run(["wg-quick", "up", interface])
            except subprocess.CalledProcessError as exc:
                raise PlatformError(
                    f"Failed to bring up WireGuard {interface}: {exc.stderr.strip()}"
                ) from exc

        log.info("WireGuard interface %s is up", interface)

    def restart_wg(self, interface: str = "wg0", subnet: str | None = None) -> None:
        # `subnet` is unused: same reasoning as LinuxServerPlatform — wg-quick's
        # PostUp/PostDown are symmetric (FIX-07 only affects Windows).
        _run(["wg-quick", "down", interface], check=False)
        try:
            _run(["wg-quick", "up", interface])
        except subprocess.CalledProcessError as exc:
            raise PlatformError(
                f"Failed to restart WireGuard {interface}: {exc.stderr.strip()}"
            ) from exc

    def uninstall_wg_config(self, interface: str = "wg0") -> None:
        _run(["wg-quick", "down", interface], check=False)
        conf_path = self.wg_config_dir() / f"{interface}.conf"
        if conf_path.exists():
            conf_path.unlink()

    # ── Paths: no install prefix in a container ───────────────────────────────

    def install_prefix(self) -> Path | None:
        return None

    def bin_link(self) -> Path | None:
        return None
