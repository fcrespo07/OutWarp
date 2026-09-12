from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp_server.config import ClientEntry, ServerConfig, validate_client_name
from outwarp_server.server_manager import ServerManager


def _config(clients: list[ClientEntry]) -> ServerConfig:
    return ServerConfig(
        schema_version=1,
        endpoint="203.0.113.42",
        port=443,
        http_upgrade_path_prefix="s3cr3t",
        cert_path="/etc/outwarp/cert.pem",
        key_path="/etc/outwarp/key.pem",
        cert_fingerprint_sha256="AA:" * 31 + "AA",
        wg_private_key="server_priv",
        wg_public_key="server_pub",
        subnet="10.0.0.0/24",
        server_address="10.0.0.1/24",
        wg_listen_port=51820,
        clients=clients,
    )


_PUB1 = "arnx6499M4j0+dWG9m6Z/VQIDfLERvDlhmiwnAihbdA="
_PUB2 = "AV9+a8Wur0g3JAieklLME7UJUaa2lBJSJ2XP9NeAMG4="
_PUB3 = "L1BSyf0VsZoYxYTQE2NWgZhhPww06EQJ73k4cJoVnsI="


class TestPruneExpired:
    def test_revokes_only_past_dated_clients(self, tmp_path: Path) -> None:
        clients = [
            ClientEntry("old", _PUB1, "10.0.0.2/32", expires_at="2000-01-01"),
            ClientEntry("live", _PUB2, "10.0.0.3/32", expires_at="2999-01-01"),
            ClientEntry("forever", _PUB3, "10.0.0.4/32"),
        ]
        cfg = _config(clients)
        mgr = ServerManager(cfg, config_path=tmp_path / "server_config.json")
        # revoke_client now delegates to operations.revoke_client, which
        # reloads fresh from config_path under its file lock (FIX-04).
        cfg.save(tmp_path / "server_config.json")
        with patch("outwarp_server.operations.remove_peer_live"), \
             patch("outwarp_server.platforms.get_server_platform"), \
             patch(
                 "outwarp_server.server_manager.default_config_path",
                 return_value=tmp_path / "server_config.json",
             ):
            revoked = mgr.prune_expired(today="2026-06-01")
        assert revoked == ["old"]
        assert {c.name for c in mgr.config.clients} == {"live", "forever"}

    def test_noop_when_nothing_expired(self, tmp_path: Path) -> None:
        clients = [ClientEntry("forever", _PUB1, "10.0.0.2/32")]
        mgr = ServerManager(_config(clients), config_path=tmp_path / "server_config.json")
        with patch("outwarp_server.server_manager.default_config_path",
                   return_value=tmp_path / "server_config.json"):
            assert mgr.prune_expired(today="2026-06-01") == []
        assert len(mgr.config.clients) == 1


class TestDoStartPrunesExpiredFirst:
    """CONCEPTO-D: a client whose expires_at passed while the server was off
    must not just be silently excluded from the next wg0.conf — it must
    actually be revoked (peer removal + token invalidation) on the next
    start, not wait for someone to run `prune-expired` by hand."""

    def test_do_start_calls_prune_expired_before_anything_else(
        self, tmp_path: Path,
    ) -> None:
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        with (
            patch.object(mgr, "prune_expired") as mock_prune,
            patch(
                "outwarp_server.server_manager.default_config_path",
                return_value=tmp_path / "server_config.json",
            ),
            # Let _do_start fail past that point (no real wstunnel/platform in
            # this sandbox) — this test only cares that prune ran first.
            patch(
                "outwarp_server.server_manager.get_server_platform",
                side_effect=RuntimeError("stop here"),
            ),
        ):
            mgr._do_start()
        mock_prune.assert_called_once()

    def test_do_start_survives_a_failing_prune(self, tmp_path: Path) -> None:
        """A prune failure (e.g. a transient WG hot-remove error) must not
        abort the whole startup — connectivity for everyone else matters more
        than one stale peer."""
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        with (
            patch.object(mgr, "prune_expired", side_effect=RuntimeError("boom")),
            patch(
                "outwarp_server.server_manager.default_config_path",
                return_value=tmp_path / "server_config.json",
            ),
            patch(
                "outwarp_server.server_manager.get_server_platform",
                side_effect=RuntimeError("stop here — reached past prune"),
            ) as mock_platform,
        ):
            mgr._do_start()
        mock_platform.assert_called_once()


@pytest.mark.parametrize(
    "name",
    ["laptop", "ferra-portatil", "Casa_01", "movil.personal", "a", "Client 1", "x" * 64],
)
def test_validate_client_name_accepts_safe_names(name):
    assert validate_client_name(name) == name


def test_validate_client_name_strips_whitespace():
    assert validate_client_name("  laptop  ") == "laptop"


@pytest.mark.parametrize(
    "name",
    [
        "../secret",       # path traversal
        "..\\secret",      # windows traversal
        "a/b",             # path separator
        "a\\b",            # windows separator
        ".",               # current dir
        "..",              # parent dir
        "",                # empty
        "   ",             # whitespace only
        "x" * 65,          # too long
        "name\x00",        # null byte
        "tab\tname",       # control char
        "/abs",            # absolute-ish
        ".hidden",         # leading dot (separator-like start)
    ],
)
def test_validate_client_name_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        validate_client_name(name)


def test_validate_client_name_rejects_non_string():
    with pytest.raises(ValueError):
        validate_client_name(None)  # type: ignore[arg-type]


class TestRotateClientKeys:
    """FIX-05 regression: rotate_client_keys used to write the client's fresh
    private key to Path.cwd() — whatever directory the daemon happened to
    start in — and nothing ever deleted it. It now delegates to
    operations.rotate_client with a private temp dir removed before return."""

    def test_no_owcfg_survives_outside_the_temp_dir(self, tmp_path: Path) -> None:
        old_pub = "yYzBcQWtwdHBN0USGevIH8L0z9WaUDItBX1ZLZMkYpk="
        clients = [ClientEntry("laptop", old_pub, "10.0.0.2/32")]
        cfg = _config(clients)
        mgr = ServerManager(cfg, config_path=tmp_path / "server_config.json")
        # FIX-04: operations.rotate_client reloads fresh from config_path under
        # its file lock, so the on-disk file must exist for this to find it.
        cfg.save(tmp_path / "server_config.json")

        captured: dict = {}
        real_mkdtemp = __import__("tempfile").mkdtemp

        def _spy_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, dir=tmp_path, **kwargs)
            captured["dir"] = Path(d)
            return d

        with (
            patch("outwarp_server.server_manager.tempfile.mkdtemp", side_effect=_spy_mkdtemp),
            patch(
                "outwarp_server.operations.generate_wg_keypair",
                return_value=("new_priv", "new_pub"),
            ),
            patch("outwarp_server.operations.generate_psk", return_value=""),
            patch("outwarp_server.operations.add_peer_live"),
            patch("outwarp_server.operations.remove_peer_live"),
            patch("outwarp_server.platforms.get_server_platform"),
            patch(
                "outwarp_server.server_manager.default_config_path",
                return_value=tmp_path / "server_config.json",
            ),
        ):
            owcfg_bytes, new_public = mgr.rotate_client_keys("laptop")

        assert new_public == "new_pub"
        assert b'"client_private_key": "new_priv"' in owcfg_bytes
        # The temp dir rotate_client used to write into is gone...
        assert not captured["dir"].exists()
        # ...and nothing else was left behind in tmp_path either.
        assert list(tmp_path.glob("*.owcfg")) == []


class TestConcurrentAddClient:
    """FIX-04 regression: add_client used to read-modify-write self._config
    with no lock at all. Two near-simultaneous calls (e.g. two browser tabs
    both hitting the panel's /api/add_client) could both read the same client
    list, both allocate the same pool IP via next_available_ip, and have the
    second save silently clobber the first's new peer — the first client
    would work live (its peer was hot-added) but vanish from the persisted
    config, resurfacing as a mystery on the next restart.

    ServerManager._lock (a threading.Lock, held for the whole operation) now
    serializes same-process callers; operations.py's locked_config() closes
    the same gap across processes (not exercised here — that needs real
    multiprocessing, see config.py's docstring for the reasoning)."""

    def test_n_concurrent_add_client_calls_yield_n_distinct_ips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import threading

        # ServerManager.add_client doesn't pass output_dir, so
        # operations.add_client falls back to Path.cwd() for the .owcfg it
        # writes — without this, the 8 files land in the real repo checkout
        # instead of tmp_path.
        monkeypatch.chdir(tmp_path)

        n = 8
        cfg = _config([])
        mgr = ServerManager(cfg, config_path=tmp_path / "server_config.json")
        config_path = tmp_path / "server_config.json"
        cfg.save(config_path)

        errors: list[BaseException] = []

        def _add(i: int) -> None:
            try:
                mgr.add_client(f"client-{i}")
            except BaseException as exc:  # noqa: BLE001 — surfaced by the assert below
                errors.append(exc)

        with (
            patch("outwarp_server.operations.generate_psk", return_value=""),
            patch("outwarp_server.platforms.get_server_platform"),
            patch(
                "outwarp_server.server_manager.default_config_path",
                return_value=config_path,
            ),
        ):
            threads = [threading.Thread(target=_add, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert errors == []
        # In-memory view (mgr._config, updated under the lock on every call)...
        names = {c.name for c in mgr.config.clients}
        ips = [c.address for c in mgr.config.clients]
        assert names == {f"client-{i}" for i in range(n)}
        assert len(ips) == len(set(ips)) == n

        # ...matches what actually landed on disk — no lost update.
        persisted = ServerConfig.load(config_path)
        assert {c.name for c in persisted.clients} == names
        assert len(persisted.clients) == n


# --- transport branch: what wstunnel is actually told to do ---

class TestWstunnelCommandBranches:
    def _cmd(self, **overrides):
        from dataclasses import replace

        from outwarp_server.server_manager import build_wstunnel_command

        return build_wstunnel_command(
            replace(_config([]), **overrides), Path("/usr/bin/wstunnel")
        )

    def test_self_signed_holds_the_public_port_with_its_own_cert(self) -> None:
        cmd = self._cmd()
        assert "wss://0.0.0.0:443" in cmd
        assert "--tls-certificate" in cmd
        assert "--tls-private-key" in cmd

    def test_acme_drops_tls_and_binds_loopback(self) -> None:
        """Caddy owns the certificate and the public port in this branch; the
        listener must not be reachable from the network, or anyone knowing the
        path could skip the front entirely."""
        cmd = self._cmd(tls_mode="acme", internal_ws_port=8080)
        assert "ws://127.0.0.1:8080" in cmd
        assert "0.0.0.0" not in " ".join(cmd)
        assert "--tls-certificate" not in cmd
        assert "--tls-private-key" not in cmd

    def test_both_branches_keep_the_path_gate_and_the_wg_restriction(self) -> None:
        for cmd in (self._cmd(), self._cmd(tls_mode="acme")):
            assert "--restrict-http-upgrade-path-prefix" in cmd
            assert "--restrict-to" in cmd
            assert cmd[cmd.index("--restrict-to") + 1] == "127.0.0.1:51820"

    def test_both_branches_allow_a_forward_to_the_enrolment_listener_only(self) -> None:
        """B-018: enrolment rides the transport as a TCP forward to the
        loopback listener, so wstunnel must allow exactly that destination on
        top of WireGuard's — and nothing else, or the path prefix would become
        a generic TCP proxy into the server."""
        for cmd in (self._cmd(), self._cmd(tls_mode="acme")):
            restricts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--restrict-to"]
            assert restricts == ["127.0.0.1:51820", "127.0.0.1:8444"]


class TestConfigDirIsHonoured:
    def test_add_client_uses_the_launch_config_dir_not_etc_outwarp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression (k3s, `--config-dir /data serve`): ServerManager reloaded
        the config from default_config_path() — /etc/outwarp — on every
        add/revoke and failed with "Config file not found" because nothing was
        ever written there. The manager must keep using the path it was
        launched with."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        cfg_path = data_dir / "server_config.json"
        _config([]).save(cfg_path)
        mgr = ServerManager(ServerConfig.load(cfg_path), config_path=cfg_path)
        # add_client writes <name>.owcfg to the cwd — keep it out of the repo.
        monkeypatch.chdir(tmp_path)

        etc = tmp_path / "etc-outwarp"  # stands in for /etc/outwarp: must stay untouched
        with (
            patch("outwarp_server.config.default_config_dir", return_value=etc),
            patch("outwarp_server.operations.generate_wg_keypair", return_value=("priv", "pub")),
            patch("outwarp_server.operations.generate_psk", return_value=""),
            patch("outwarp_server.operations.add_peer_live"),
            patch("outwarp_server.platforms.get_server_platform"),
            patch("outwarp_server.server_manager.default_config_path",
                  side_effect=AssertionError("manager must not consult the default path")),
        ):
            mgr.add_client("phone")

        assert not etc.exists()
        assert [c.name for c in ServerConfig.load(cfg_path).clients] == ["phone"]

    def test_cli_config_dir_flag_is_exported_to_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Components that resolve the config dir on their own (GUI bridge,
        panel, enrolment listener) must see the same --config-dir."""
        from outwarp_server import cli
        from outwarp_server.config import CONFIG_DIR_ENV, default_config_dir

        monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
        monkeypatch.setenv("OUTWARP_TEST_MODE", "1")
        with patch.dict(cli._COMMANDS, {"status": lambda args: 0}):
            cli.main(["--config-dir", str(tmp_path), "status"])
        assert default_config_dir() == tmp_path


class TestEffectiveState:
    """`state` alone only reflects actions *this* process took — a companion
    admin surface (the web/GUI panel next to a separately-managed `serve`
    process, e.g. a Docker/Kubernetes sidecar, or a systemd-installed
    wstunnel unit with no `serve` daemon at all) never calls start(), so its
    dashboard reported "stopped" forever even with a perfectly healthy
    tunnel. `effective_state` reconciles that ambiguous default against the
    OS; a state this process actually set (STARTING/RUNNING/ERROR) is left
    alone."""

    def test_stopped_is_reconciled_to_running_when_the_os_says_so(self, tmp_path: Path) -> None:
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        assert mgr.state.value == "stopped"
        fake_platform = type(
            "P", (), {
                "is_wstunnel_running": lambda self: True,
                "is_wg_active": lambda self, iface: True,
                "wg_interface_name": lambda self: "wg0",
            },
        )()
        with patch(
            "outwarp_server.server_manager.get_server_platform", return_value=fake_platform,
        ):
            assert mgr.effective_state.value == "running"

    def test_stopped_stays_stopped_when_the_os_agrees(self, tmp_path: Path) -> None:
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        fake_platform = type(
            "P", (), {
                "is_wstunnel_running": lambda self: False,
                "is_wg_active": lambda self, iface: False,
                "wg_interface_name": lambda self: "wg0",
            },
        )()
        with patch(
            "outwarp_server.server_manager.get_server_platform", return_value=fake_platform,
        ):
            assert mgr.effective_state.value == "stopped"

    def test_a_platform_probe_failure_falls_back_to_state(self, tmp_path: Path) -> None:
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        with patch(
            "outwarp_server.server_manager.get_server_platform",
            side_effect=RuntimeError("no platform for this OS"),
        ):
            assert mgr.effective_state == mgr.state

    def test_running_is_never_downgraded_by_a_disagreeing_probe(self, tmp_path: Path) -> None:
        """This process's own RUNNING is ground truth — it started the
        process itself and knows better than an OS probe that may not even
        apply to how it manages the service (e.g. a Popen child never
        registered with systemd)."""
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        mgr._set_state(mgr.state.__class__.RUNNING)  # noqa: SLF001
        fake_platform = type(
            "P", (), {
                "is_wstunnel_running": lambda self: False,
                "is_wg_active": lambda self, iface: False,
                "wg_interface_name": lambda self: "wg0",
            },
        )()
        with patch(
            "outwarp_server.server_manager.get_server_platform", return_value=fake_platform,
        ):
            assert mgr.effective_state.value == "running"

    def test_start_adopts_an_externally_running_service_instead_of_racing_it(
        self, tmp_path: Path,
    ) -> None:
        """Calling start() on a companion panel's manager while the service
        is already running elsewhere must not spawn a second wstunnel."""
        mgr = ServerManager(_config([]), config_path=tmp_path / "server_config.json")
        fake_platform = type(
            "P", (), {
                "is_wstunnel_running": lambda self: True,
                "is_wg_active": lambda self, iface: True,
                "wg_interface_name": lambda self: "wg0",
            },
        )()
        with patch(
            "outwarp_server.server_manager.get_server_platform", return_value=fake_platform,
        ), patch.object(
            mgr, "_do_start", side_effect=AssertionError("must not attempt a real start"),
        ):
            mgr.start()
        assert mgr.state.value == "running"
        assert mgr._wstunnel is None  # noqa: SLF001 — no process spawned


class TestExternalConfigChanges:
    """The panel/GUI keeps one ServerManager for its whole life while other
    processes write the state it displays (the `serve` container's enrolment
    listener, `add-client` over kubectl exec, outwarp-enroll.service). It
    used to show its start-up snapshot forever."""

    def _mgr(self, tmp_path: Path) -> tuple[ServerManager, Path]:
        cfg_path = tmp_path / "server_config.json"
        _config([]).save(cfg_path)
        return ServerManager(ServerConfig.load(cfg_path), config_path=cfg_path), cfg_path

    def test_refresh_is_a_noop_when_nothing_changed(self, tmp_path: Path) -> None:
        mgr, _ = self._mgr(tmp_path)
        with patch("outwarp_server.server_manager.ServerConfig.load") as load:
            assert mgr.refresh_config() is False
        load.assert_not_called()

    def test_refresh_picks_up_a_client_enrolled_by_another_process(
        self, tmp_path: Path,
    ) -> None:
        import os
        from dataclasses import replace

        from outwarp_server.client_store import ClientStore

        mgr, cfg_path = self._mgr(tmp_path)
        assert mgr.config.clients == []

        # What enroll_server.py does in the other process: SQLite row + save.
        store = ClientStore(tmp_path / "clients.sqlite")
        with store.transaction() as conn:
            store.insert(
                ClientEntry(name="laptop", public_key=_PUB1, address="10.0.0.2/32"),
                conn=conn, created_at="2026-01-01",
            )
        replace(mgr.config, clients=store.list_active()).save(cfg_path)
        # Coarse filesystems could give the rewrite the same mtime.
        os.utime(cfg_path, (2_000_000_000, 2_000_000_000))

        assert mgr.refresh_config() is True
        assert [c.name for c in mgr.config.clients] == ["laptop"]
        assert mgr.refresh_config() is False

    def test_own_writes_do_not_trigger_a_reload(self, tmp_path: Path) -> None:
        mgr, _ = self._mgr(tmp_path)
        with (
            patch("outwarp_server.operations.generate_psk", return_value=""),
            patch("outwarp_server.platforms.get_server_platform"),
        ):
            mgr.add_client("phone")
        with patch("outwarp_server.server_manager.ServerConfig.load") as load:
            assert mgr.refresh_config() is False
        load.assert_not_called()


class TestAddClientLeavesNoFile:
    def test_returns_bytes_and_writes_nothing_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A token-bearing .owcfg used to land in the panel's cwd — `/` under
        systemd, /data in the pod — and stay there unread."""
        import json

        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        cfg_path = tmp_path / "server_config.json"
        _config([]).save(cfg_path)
        mgr = ServerManager(ServerConfig.load(cfg_path), config_path=cfg_path)
        with (
            patch("outwarp_server.operations.generate_psk", return_value=""),
            patch("outwarp_server.platforms.get_server_platform"),
        ):
            owcfg = json.loads(mgr.add_client("phone"))
        assert owcfg["name"] == "phone"
        assert owcfg["enrollment"]["token"].startswith("ow_enroll_")
        assert list(cwd.iterdir()) == []


def test_owns_transport_only_with_a_live_subprocess(tmp_path: Path) -> None:
    cfg_path = tmp_path / "server_config.json"
    _config([]).save(cfg_path)
    mgr = ServerManager(ServerConfig.load(cfg_path), config_path=cfg_path)
    assert mgr.owns_transport is False
    mgr._wstunnel = object()  # noqa: SLF001 — what _do_start sets
    assert mgr.owns_transport is True
