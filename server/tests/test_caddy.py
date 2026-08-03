from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server import caddy


class TestSiteConfig:
    def test_proxies_only_the_secret_path(self) -> None:
        text = caddy.build_site_config("vpn.example.com", "s3cr3t", internal_ws_port=8080)
        assert "vpn.example.com {" in text
        assert "path /s3cr3t /s3cr3t/*" in text
        assert "reverse_proxy @outwarp 127.0.0.1:8080" in text

    def test_requires_a_websocket_upgrade(self) -> None:
        """A prober that guesses the path with a plain GET must land on the
        decoy site, not on wstunnel's 400."""
        text = caddy.build_site_config("vpn.example.com", "s3cr3t")
        assert "header Connection *Upgrade*" in text
        assert "header Upgrade websocket" in text

    def test_serves_the_decoy_at_the_root(self) -> None:
        text = caddy.build_site_config(
            "vpn.example.com", "s3cr3t", decoy_dir=Path("/srv/decoy")
        )
        assert "root * /srv/decoy" in text
        assert "file_server" in text

    def test_acme_email_is_optional(self) -> None:
        assert "email" not in caddy.build_site_config("vpn.example.com", "p")
        with_email = caddy.build_site_config(
            "vpn.example.com", "p", acme_email="me@example.com"
        )
        assert "email me@example.com" in with_email

    def test_leading_slashes_in_the_prefix_do_not_double_up(self) -> None:
        text = caddy.build_site_config("vpn.example.com", "/s3cr3t/")
        assert "path /s3cr3t /s3cr3t/*" in text

    @pytest.mark.parametrize("domain,prefix", [("", "p"), ("vpn.example.com", "")])
    def test_rejects_missing_inputs(self, domain: str, prefix: str) -> None:
        with pytest.raises(caddy.CaddyError):
            caddy.build_site_config(domain, prefix)


class TestDecoySite:
    def test_writes_a_placeholder_page(self, tmp_path: Path) -> None:
        index = caddy.write_decoy_site(tmp_path / "decoy")
        assert index.exists()
        assert "<title>" in index.read_text(encoding="utf-8")

    def test_never_clobbers_existing_content(self, tmp_path: Path) -> None:
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        (decoy / "index.html").write_text("<h1>my real site</h1>", encoding="utf-8")
        caddy.write_decoy_site(decoy)
        assert (decoy / "index.html").read_text(encoding="utf-8") == "<h1>my real site</h1>"


class TestEnsureImport:
    def test_creates_the_main_caddyfile_when_absent(self, tmp_path: Path) -> None:
        main = tmp_path / "Caddyfile"
        assert caddy.ensure_import(main) is True
        assert caddy.IMPORT_LINE in main.read_text(encoding="utf-8")

    def test_appends_without_destroying_existing_sites(self, tmp_path: Path) -> None:
        main = tmp_path / "Caddyfile"
        main.write_text("blog.example.com {\n\trespond \"hi\"\n}\n", encoding="utf-8")
        caddy.ensure_import(main)
        text = main.read_text(encoding="utf-8")
        assert "blog.example.com {" in text
        assert caddy.IMPORT_LINE in text

    def test_is_idempotent(self, tmp_path: Path) -> None:
        main = tmp_path / "Caddyfile"
        caddy.ensure_import(main)
        first = main.read_text(encoding="utf-8")
        assert caddy.ensure_import(main) is False
        assert main.read_text(encoding="utf-8") == first


class TestApply:
    def _paths(self, tmp_path: Path) -> dict:
        return {
            "decoy_dir": tmp_path / "decoy",
            "main_caddyfile": tmp_path / "Caddyfile",
            "site_file": tmp_path / "conf.d" / "outwarp.caddyfile",
        }

    def test_writes_everything_and_reloads(self, tmp_path: Path) -> None:
        with (
            patch.object(caddy, "find_caddy", return_value=Path("/usr/bin/caddy")),
            patch.object(caddy, "validate", return_value=(True, "")),
            patch.object(caddy, "reload_service", return_value=(True, "")) as reload_,
        ):
            warnings = caddy.apply("vpn.example.com", "s3cr3t", **self._paths(tmp_path))
        assert warnings == []
        reload_.assert_called_once()
        assert (tmp_path / "conf.d" / "outwarp.caddyfile").exists()
        assert (tmp_path / "decoy" / "index.html").exists()
        assert caddy.IMPORT_LINE in (tmp_path / "Caddyfile").read_text(encoding="utf-8")

    def test_still_writes_the_config_when_caddy_is_missing(self, tmp_path: Path) -> None:
        """Leaving a valid config on disk that the admin can load by hand beats
        writing nothing at all."""
        paths = self._paths(tmp_path)
        with patch.object(caddy, "find_caddy", return_value=None):
            warnings = caddy.apply("vpn.example.com", "s3cr3t", **paths)
        assert paths["site_file"].exists()
        assert any("not installed" in w for w in warnings)

    def test_does_not_reload_an_invalid_config(self, tmp_path: Path) -> None:
        with (
            patch.object(caddy, "find_caddy", return_value=Path("/usr/bin/caddy")),
            patch.object(caddy, "validate", return_value=(False, "line 3: bad")),
            patch.object(caddy, "reload_service") as reload_,
        ):
            warnings = caddy.apply("vpn.example.com", "s3cr3t", **self._paths(tmp_path))
        reload_.assert_not_called()
        assert any("validate" in w for w in warnings)

    def test_reports_a_failed_reload(self, tmp_path: Path) -> None:
        with (
            patch.object(caddy, "find_caddy", return_value=Path("/usr/bin/caddy")),
            patch.object(caddy, "validate", return_value=(True, "")),
            patch.object(caddy, "reload_service", return_value=(False, "port in use")),
        ):
            warnings = caddy.apply("vpn.example.com", "s3cr3t", **self._paths(tmp_path))
        assert any("port in use" in w for w in warnings)


class TestReload:
    def test_falls_back_to_enable_when_caddy_is_not_running_yet(self) -> None:
        calls: list[list[str]] = []

        def _run(cmd, **_kw):
            calls.append(cmd)
            rc = 1 if cmd[1] == "reload" else 0
            return MagicMock(returncode=rc, stderr="", stdout="")

        with (
            patch.object(caddy.shutil, "which", return_value="/usr/bin/systemctl"),
            patch.object(caddy.subprocess, "run", side_effect=_run),
        ):
            ok, _ = caddy.reload_service()
        assert ok is True
        assert calls[0][:2] == ["systemctl", "reload"]
        assert calls[1][:3] == ["systemctl", "enable", "--now"]


class TestRemove:
    def test_removes_only_our_site_file(self, tmp_path: Path) -> None:
        main = tmp_path / "Caddyfile"
        main.write_text("blog.example.com {\n}\n" + caddy.IMPORT_LINE + "\n", encoding="utf-8")
        site = tmp_path / "outwarp.caddyfile"
        site.write_text("x", encoding="utf-8")
        with patch.object(caddy, "find_caddy", return_value=None):
            caddy.remove(main, site)
        assert not site.exists()
        assert "blog.example.com {" in main.read_text(encoding="utf-8")

    def test_is_safe_when_nothing_was_installed(self, tmp_path: Path) -> None:
        with patch.object(caddy, "find_caddy", return_value=None):
            caddy.remove(tmp_path / "Caddyfile", tmp_path / "missing.caddyfile")
