"""Guards for the Linux install paths: helper script copies and the Arch package."""

from __future__ import annotations

import re
from pathlib import Path

from outwarp import helper_path

REPO = Path(__file__).resolve().parents[2]


def test_standalone_helper_matches_install_sh_heredoc() -> None:
    script = (REPO / "installer/linux/install.sh").read_text()
    match = re.search(r"<<'HELPER_EOF'\n(.*?)\nHELPER_EOF\n", script, re.S)
    assert match, "helper heredoc not found in install.sh"
    assert (REPO / "installer/linux/outwarp-priv").read_text() == match.group(1) + "\n"


def test_pkgbuild_pins_the_same_wstunnel_as_the_installer() -> None:
    pinned = (REPO / "installer/wstunnel-version.txt").read_text().strip().lstrip("v")
    pkgbuild = (REPO / "packaging/arch/PKGBUILD").read_text()
    assert f"_wstunnel={pinned}\n" in pkgbuild


def test_pkgbuild_version_matches_client() -> None:
    pyproject = (REPO / "client/pyproject.toml").read_text()
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert f"pkgver={version}\n" in (REPO / "packaging/arch/PKGBUILD").read_text()


def test_default_helper_prefers_existing_candidate(monkeypatch, tmp_path: Path) -> None:
    present = tmp_path / "outwarp-priv"
    present.write_text("")
    monkeypatch.setattr(helper_path, "HELPER_CANDIDATES", (tmp_path / "missing", present))
    assert helper_path.default_helper() == present


def test_default_helper_falls_back_to_first_candidate(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "a"
    monkeypatch.setattr(helper_path, "HELPER_CANDIDATES", (first, tmp_path / "b"))
    assert helper_path.default_helper() == first
