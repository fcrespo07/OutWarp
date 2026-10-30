"""Where the privileged helper lives.

`install.sh` puts it under /usr/local/libexec; the distro package puts it
under /usr/lib/outwarp (packages must not write to /usr/local).
"""

from __future__ import annotations

from pathlib import Path

HELPER_CANDIDATES = (
    Path("/usr/local/libexec/outwarp-priv"),
    Path("/usr/lib/outwarp/outwarp-priv"),
)


def default_helper() -> Path:
    for candidate in HELPER_CANDIDATES:
        if candidate.exists():
            return candidate
    return HELPER_CANDIDATES[0]
