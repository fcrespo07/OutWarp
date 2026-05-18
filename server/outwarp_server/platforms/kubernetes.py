from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from outwarp_server.platforms.base import PlatformError
from outwarp_server.platforms.linux import LinuxServerPlatform, _run

log = logging.getLogger(__name__)


class KubernetesServerPlatform(LinuxServerPlatform):
    """Platform for running inside a Kubernetes pod (or plain Docker container).

    wstunnel runs as a subprocess managed by ServerManager — no systemd involved.
    WireGuard is managed directly via wg-quick (pod requires NET_ADMIN + NET_RAW
    capabilities and the wireguard kernel module loaded on the node).
    """

    # ── wstunnel: managed by ServerManager as a subprocess ───────────────────

    def install_wstunnel_service(self, port, cert_path, key_path, upgrade_path, wg_listen_port, wstunnel_bin) -> None:  # noqa: ANN001
        pass

    def uninstall_wstunnel_service(self) -> None:
        pass

    def is_wstunnel_running(self) -> bool:
        result = subprocess.run(["pgrep", "-x", "wstunnel"], capture_output=True, check=False)
        return result.returncode == 0

    def restart_wstunnel_service(self) -> None:
        # In K8s use: kubectl rollout restart deployment/outwarp-server
        pass

    # ── WireGuard: wg-quick directly, no systemd ─────────────────────────────

    def install_wg_config(self, conf_text: str, interface: str = "wg0") -> None:
        conf_path = self.wg_config_dir() / f"{interface}.conf"
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conf_path.write_text(conf_text, encoding="utf-8")
            os.chmod(conf_path, 0o600)
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

    def restart_wg(self, interface: str = "wg0") -> None:
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
