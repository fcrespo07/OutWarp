from __future__ import annotations

import os
import sys

from outwarp_server.platforms.base import PlatformError, ServerPlatform


def get_server_platform() -> ServerPlatform:
    # Explicit override or auto-detected Kubernetes environment.
    if os.environ.get("OUTWARP_PLATFORM") == "kubernetes" or "KUBERNETES_SERVICE_HOST" in os.environ:
        from outwarp_server.platforms.kubernetes import KubernetesServerPlatform
        return KubernetesServerPlatform()
    if sys.platform == "win32":
        from outwarp_server.platforms.windows import WindowsServerPlatform
        return WindowsServerPlatform()
    if sys.platform == "darwin":
        from outwarp_server.platforms.macos import MacOSServerPlatform
        return MacOSServerPlatform()
    from outwarp_server.platforms.linux import LinuxServerPlatform
    return LinuxServerPlatform()


__all__ = ["ServerPlatform", "PlatformError", "get_server_platform"]
