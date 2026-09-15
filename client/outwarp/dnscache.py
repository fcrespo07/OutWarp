"""Last-known addresses for the hostnames the client dials.

Why a cache and not "allow DNS through the kill switch": with the switch
engaged (RECONNECTING / FAILED) the only traffic allowed out is to the
escape set — the server and proxy addresses. A profile whose endpoint is a
hostname then needs a lookup that the switch itself blocks, so every
reconnect attempt failed at resolution and the user ended up in FAILED with
no network. Opening UDP/53 to the LAN resolver would fix the lookup but leak
every other application's queries while the tunnel is down, which is the
opposite of what a kill switch promises.

So each successful resolution is remembered here, and while the network says
no the last answer is used instead: the reconnect dials the address the
server had, with the hostname kept as SNI/Host, and the kill switch allowlist
is built from the same answers. The trade-off is explicit — if the server's
IP changes *while* the switch is engaged, the reconnect keeps failing until
the switch is released — and it is stated in the README.

Best-effort persistence next to the sticky-rung store so a daemon restarted
under an engaged switch (systemd Restart=on-failure) still has the answers.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.Lock()
_memory: dict[str, str] = {}
_loaded = False


def cache_path() -> Path:
    from platformdirs import user_config_dir

    return Path(user_config_dir("OutWarp")) / "resolved_hosts.json"


def _load_locked() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    hosts = raw.get("hosts") if isinstance(raw, dict) else None
    if isinstance(hosts, dict):
        _memory.update({str(k): str(v) for k, v in hosts.items() if v})


def _save_locked() -> None:
    path = cache_path()
    payload = {"hosts": dict(_memory), "updated": int(time.time())}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".resolved_hosts-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        log.debug("could not persist resolved-host cache: %s", exc)
        with contextlib.suppress(Exception):
            os.unlink(tmp)


def remember(host: str, ip: str) -> None:
    """Record ``host`` → ``ip`` (only when it actually changed, to keep the
    file quiet across the 1 Hz stats loop and repeated connects)."""
    if not host or not ip:
        return
    with _lock:
        _load_locked()
        if _memory.get(host) == ip:
            return
        _memory[host] = ip
        _save_locked()


def lookup(host: str) -> str | None:
    with _lock:
        _load_locked()
        return _memory.get(host)


def reset_for_tests() -> None:
    global _loaded
    with _lock:
        _memory.clear()
        _loaded = False
