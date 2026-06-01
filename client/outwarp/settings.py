"""Persisted user preferences for the OutWarp client.

Single source of truth for the ``settings.json`` schema. Both the pywebview
GUI (``outwarp.api``) and the Textual TUI (``outwarp.tui``) read and write the
same file via this module, so toggling something in one UI takes effect in the
other on next start.

If you add a key, wire its consumer first - an unused toggle lies to the user.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from outwarp.config import default_config_path


def settings_path() -> Path:
    """Return the on-disk location of ``settings.json``.

    Resolved at call time from :func:`outwarp.config.default_config_path` so a
    monkeypatch on that symbol takes effect.
    """
    return default_config_path().parent / "settings.json"


def default_settings() -> dict[str, Any]:
    """The complete, opinionated default set. Used as the merge target on load
    so a missing key in the on-disk file falls back to the default."""
    return {
        "language": "es",
        "theme": "auto",
        "advanced": False,
        # Tolerate a pinned-fingerprint mismatch instead of aborting. For
        # networks that do active TLS interception (corporate/school proxies)
        # where the outer cert is the proxy's, not the server's. WireGuard's
        # own crypto still protects the traffic. Off by default.
        "allow_tls_intercept": False,
        # When False, an unexpectedly-closed tunnel goes straight to FAILED
        # instead of looping through the reconnect schedule. Consumed by
        # TunnelManager._run. Initial-connect failures still honour max_attempts.
        "auto_reconnect": True,
        # When True, app.py creates the main window hidden on startup so only
        # the tray icon is visible. The user opens the window from the tray's
        # "Open" entry. A fresh install (no profile yet) ignores this setting
        # - the user needs the import screen visible to do anything at all.
        "minimize_to_tray": True,
        # Register OutWarp to start on user login. Wired to platform.
        # install_autostart / uninstall_autostart in the GUI's set_settings, so
        # toggling the value writes the registry key (Windows) or .desktop file
        # (Linux) immediately.
        "start_at_boot": False,
        # Block all outbound traffic any time the tunnel is unexpectedly down
        # (RECONNECTING / FAILED). Released on CONNECTED or on a clean stop.
        # Real implementation lives in WindowsPlatform; Linux raises a
        # PlatformError when toggled on so the UI surfaces an honest error
        # rather than pretending the switch works.
        "kill_switch": False,
        # When True, the About screen runs check_for_updates() once on mount so
        # the user sees a pending release without having to click. Consumed by
        # the About component in the GUI.
        "check_updates_on_start": False,
        # When True (default), the GUI (app.main) and the TUI
        # (OutWarpClientTUI.start_manager) bring the tunnel up automatically at
        # launch if a profile is imported and not expired. Off → land on the
        # dashboard disconnected, user reconnects manually.
        "auto_connect": True,
    }


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Load ``settings.json`` and merge into the defaults. Always returns a
    dict with every default key present, even if the file is missing/corrupt.

    ``path`` lets the caller override the lookup so callers that already hold
    a tested/monkey-patchable path computation (eg ``outwarp.api._settings_path``)
    keep working without re-importing this module's internals.
    """
    target = path if path is not None else settings_path()
    if not target.exists():
        return default_settings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings()
    merged = default_settings()
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if k in merged})
    return merged


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    """Persist ``settings`` to disk atomically.

    Writes to a sibling tempfile inside the target directory and ``os.replace``s
    it onto ``target``. A crash, OOM-kill or power loss between truncate and
    full write would otherwise leave a zero-byte settings.json that
    :func:`load_settings` silently replaces with the defaults — wiping every
    user preference. The replace is atomic on the same filesystem (POSIX
    rename / Windows ReplaceFile), so a torn write is impossible.
    """
    target = path if path is not None else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, indent=2)
    # delete=False because we hand the path to os.replace; the file is
    # consumed by the rename and never needs the NamedTemporaryFile cleanup.
    fd, tmp_name = tempfile.mkstemp(
        prefix=".settings-", suffix=".json.tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
