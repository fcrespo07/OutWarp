"""Local WireGuard key generation.

The point of enrolment is that the private key is born on the machine that will
use it and never travels, so the client has to be able to make one itself.

It shells out to ``wg genkey``/``wg pubkey`` rather than doing the Curve25519
maths in Python: ``wg`` is already a hard requirement for bringing a tunnel up on
both supported platforms (and the Windows installer bundles it), whereas a pure
Python implementation would mean adding ``cryptography`` — a compiled wheel — to
every client bundle for 32 bytes of key material.
"""

from __future__ import annotations

import logging
import subprocess
import sys

from outwarp.wireguard import _find_wg_bin

log = logging.getLogger(__name__)


class KeygenError(RuntimeError):
    pass


def wg_available() -> bool:
    return _find_wg_bin() is not None


def generate_keypair() -> tuple[str, str]:
    """Return (private_key, public_key) as base64 strings.

    Raises KeygenError when ``wg`` is missing or misbehaves. Callers surface that
    as an import failure: an enrolment profile cannot be completed without it.
    """
    wg = _find_wg_bin()
    if wg is None:
        raise KeygenError(
            "WireGuard tools are required to import this profile: it asks the "
            "client to generate its own key. Install wireguard-tools "
            "(Linux) or WireGuard for Windows, then import again."
        )

    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        genkey = subprocess.run(
            [str(wg), "genkey"],
            capture_output=True, text=True, check=True, timeout=10, **extra,
        )
        private_key = genkey.stdout.strip()
        pubkey = subprocess.run(
            [str(wg), "pubkey"],
            input=private_key,
            capture_output=True, text=True, check=True, timeout=10, **extra,
        )
        public_key = pubkey.stdout.strip()
    except FileNotFoundError as exc:
        raise KeygenError(f"wg binary not found at {wg}") from exc
    except subprocess.TimeoutExpired as exc:
        raise KeygenError("wg did not respond while generating a key") from exc
    except subprocess.CalledProcessError as exc:
        raise KeygenError(
            f"WireGuard key generation failed: {(exc.stderr or '').strip()}"
        ) from exc

    if not private_key or not public_key:
        raise KeygenError("wg produced an empty key")
    return private_key, public_key
