"""Trust-on-first-use verification of a server's .owcfg signature.

CONCEPTO-C prop.2 (OutWarp-fix-plan.md): a .owcfg travels to its recipient by
email, USB, or messaging — channels this project has no control over. Every
self-hosted OutWarp server signs the profiles it issues with its own Ed25519
keypair (generated server-side in outwarp_server/minisign.py's signing half;
verified here with this package's existing hand-rolled outwarp.minisign
verifier — nothing about verification changes, only what happens with the
result). This module decides what to do with that signature once checked.

Threat model, and its limits:
  - Someone with read/write access to the .owcfg in transit (a shared drive,
    an email still sitting in an inbox, a lost USB stick) but *not* the
    server's private signing key can no longer tamper with it undetected.
  - A full man-in-the-middle who substitutes the *entire* profile — content,
    embedded public key, and a freshly forged signature of their own — on its
    very first delivery is not caught here. That is the same trust-on-first-
    use gap an SSH host key fingerprint has the first time you connect: this
    module closes it from the *second* profile onward for the same server, by
    remembering the key it saw first and flagging a mismatch later.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from outwarp import minisign

log = logging.getLogger(__name__)

_APP_NAME = "OutWarp"


class ProfileTrustError(ValueError):
    """A .owcfg carries a "signing" block that does not verify."""


@dataclass(frozen=True)
class TrustVerdict:
    """What verify_and_pin() actually decided, for surfacing to the user.

    Every import path (CLI, GUI, TUI) used to have no way to show this at
    all — the outcome only ever reached a log line, so an unsigned profile or
    a rotated signing key looked identical to a normal import from the
    user's side. ``status`` is a stable machine-readable tag the GUI bridge
    can key a banner style on; ``message`` is the human-readable sentence
    every surface can print/log/toast verbatim.
    """

    status: str  # "verified" | "unverified" | "key_rotated"
    message: str


def known_servers_path() -> Path:
    return Path(user_config_dir(_APP_NAME)) / "known_servers.json"


def canonical_json(payload: dict[str, Any]) -> bytes:
    """Deterministic serialization matching outwarp_server.owcfg._canonical_json —
    the two must agree byte-for-byte or every signature would fail to verify."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_known_servers(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _pin(path: Path, endpoint: str, public_key_text: str) -> None:
    known = _load_known_servers(path)
    known[endpoint] = public_key_text
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(known, indent=2), encoding="utf-8")


def verify_and_pin(raw: Any, *, path: Path | None = None) -> TrustVerdict:
    """Verify `raw`'s embedded "signing" block, if any, and TOFU-pin the key.

    Raises ProfileTrustError when a signature is *present but invalid*, or
    when the profile is unsigned for an endpoint whose key is already pinned
    (a stripped signature must not downgrade the pin). A profile from a
    never-seen server with no signing key configured yet (or an older OutWarp
    version) is accepted with a warning, the same fail-open shape the release
    updater already uses for "no manifest published". A key that
    differs from one already pinned for this server's endpoint is also only a
    warning: refusing outright would brick a legitimate admin-initiated key
    rotation with no recovery path in this first cut, and the profile's own
    signature already verified against the key *it* claims — see the module
    docstring for exactly what that does and doesn't prove.

    Returns a TrustVerdict describing the outcome instead of only logging it,
    so every import surface (CLI, GUI, TUI) can show the user what happened —
    an unsigned profile or a rotated key used to be indistinguishable from an
    ordinary import unless someone went looking at the log file.
    """
    if not isinstance(raw, dict):
        return TrustVerdict("unverified", "Profile is not a JSON object — nothing to verify.")
    endpoint = str((raw.get("server") or {}).get("endpoint", ""))
    store = path or known_servers_path()
    signing = raw.get("signing")
    if not signing:
        if endpoint and endpoint in _load_known_servers(store):
            # Fail-open is only for servers we have never seen sign anything.
            # Once a key is pinned for this endpoint, an unsigned profile is
            # exactly what stripping the signature off a tampered one looks
            # like — accepting it would make the pin worthless.
            raise ProfileTrustError(
                f"Profile for {endpoint} is unsigned, but this server's signing "
                "key is already trusted on this machine. Ask the server admin "
                "for a signed profile; if the server was reinstalled, remove "
                f"its entry from {store} first."
            )
        log.warning("Profile has no signing block — cannot verify who issued it.")
        return TrustVerdict(
            "unverified", "Profile has no signing block — cannot verify who issued it."
        )
    if not isinstance(signing, dict):
        raise ProfileTrustError("'signing' must be an object")
    public_key = str(signing.get("public_key", ""))
    signature = str(signing.get("signature", ""))
    if not public_key or not signature:
        raise ProfileTrustError("'signing' is missing public_key or signature")

    payload = canonical_json({k: v for k, v in raw.items() if k != "signing"})
    try:
        minisign.verify(payload, signature, public_key)
    except minisign.MinisignError as exc:
        raise ProfileTrustError(f"Profile signature is invalid: {exc}") from exc

    if not endpoint:
        return TrustVerdict("verified", "Signature verified.")
    known = _load_known_servers(store)
    previous = known.get(endpoint)
    if previous is None:
        _pin(store, endpoint, public_key)
        return TrustVerdict(
            "verified", "Signature verified — server key pinned for future imports."
        )
    if previous != public_key:
        log.warning(
            "Profile for %s is signed with a different key than the one "
            "last seen for this server — confirm with the server admin that "
            "the signing key was intentionally rotated before trusting it.",
            endpoint,
        )
        return TrustVerdict(
            "key_rotated",
            "Signature verified, but with a different key than last time — confirm "
            "with the server admin that the key was intentionally rotated.",
        )
    return TrustVerdict("verified", "Signature verified — matches the pinned server key.")
