from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from outwarp.integrity import (
    IntegrityIssue,
    check_critical_files,
    format_report,
    likely_av_quarantine,
)
from outwarp.tunnel import TunnelError


def _make_ui(tmp_path: Path) -> Path:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>")
    (ui / "bundle.js").write_text("// bundle")
    (ui / "styles.css").write_text("body{}")
    return ui


@pytest.fixture
def fake_world(tmp_path, monkeypatch):
    """Wire find_wstunnel, the UI dir and the Windows WG path to tmp_path so
    each test can independently flip files in/out of existence."""
    wst = tmp_path / "wstunnel.exe"
    wst.write_text("x" * 8)
    ui_dir = _make_ui(tmp_path)
    wg = tmp_path / "wireguard.exe"
    wg.write_text("x" * 8)

    monkeypatch.setattr("outwarp.integrity.find_wstunnel", lambda: wst)
    monkeypatch.setattr("outwarp.integrity._resolve_ui_dir", lambda: ui_dir)
    # outwarp.platforms.windows imports subprocess.CREATE_NO_WINDOW at module
    # load which only exists on Windows; only patch the WG path when that
    # module is actually loadable.
    if sys.platform == "win32":
        monkeypatch.setattr("outwarp.platforms.windows._WIREGUARD_EXE", wg)
    return tmp_path, wst, ui_dir, wg


def test_check_returns_empty_when_all_present(fake_world):
    assert check_critical_files() == []


def test_check_flags_missing_wstunnel(fake_world, monkeypatch):
    def _raise():
        raise TunnelError("wstunnel binary not found")
    monkeypatch.setattr("outwarp.integrity.find_wstunnel", _raise)

    issues = check_critical_files()
    names = [i.name for i in issues]
    assert "wstunnel" in names
    miss = next(i for i in issues if i.name == "wstunnel")
    assert miss.kind == "missing"
    assert "not found" in miss.detail


def test_check_flags_empty_wstunnel(fake_world):
    _, wst, _, _ = fake_world
    wst.write_text("")
    issues = check_critical_files()
    miss = next(i for i in issues if i.name == "wstunnel")
    assert miss.kind == "empty"


def test_check_flags_missing_ui_file(fake_world):
    _, _, ui_dir, _ = fake_world
    (ui_dir / "bundle.js").unlink()
    issues = check_critical_files()
    names = [i.name for i in issues]
    assert "ui/bundle.js" in names


def test_check_wireguard_only_on_windows(fake_world, monkeypatch):
    _, _, _, wg = fake_world
    wg.unlink()
    monkeypatch.setattr(sys, "platform", "linux")
    issues = check_critical_files()
    # Linux: WireGuard isn't checked because the binary path is Windows-only.
    assert all(i.name != "wireguard.exe" for i in issues)


@pytest.mark.skipif(sys.platform != "win32", reason="windows-only path probe")
def test_check_flags_missing_wireguard_on_windows(fake_world):
    _, _, _, wg = fake_world
    wg.unlink()
    issues = check_critical_files()
    names = [i.name for i in issues]
    assert "wireguard.exe" in names


def test_likely_av_quarantine_detects_wstunnel():
    issues = [IntegrityIssue("wstunnel", "/x", "missing", "gone")]
    assert likely_av_quarantine(issues) is True


def test_likely_av_quarantine_ignores_ui_only():
    issues = [IntegrityIssue("ui/bundle.js", "/x", "missing", "gone")]
    assert likely_av_quarantine(issues) is False


def test_format_report_ok():
    assert format_report([]) == "integrity ok"


def test_format_report_lists_issues():
    issues = [
        IntegrityIssue("wstunnel", "/x/wst.exe", "missing", "not found"),
        IntegrityIssue("ui/bundle.js", "/x/b.js", "empty", "0 bytes"),
    ]
    txt = format_report(issues)
    assert "2 issue(s)" in txt
    assert "[missing] wstunnel" in txt
    assert "[empty] ui/bundle.js" in txt


def test_check_never_raises_even_if_internal_helper_does(fake_world, monkeypatch):
    """A bug in any sub-check must not gate startup."""
    def _boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr("outwarp.integrity._check_ui_bundle", _boom)
    issues = check_critical_files()
    assert any(i.name == "integrity-check" and i.kind == "unknown" for i in issues)


def test_issue_to_dict_round_trip():
    i = IntegrityIssue("wstunnel", "/x", "missing", "d")
    assert i.to_dict() == {"name": "wstunnel", "path": "/x", "kind": "missing", "detail": "d"}


def test_api_get_integrity_reports_issues():
    """End-to-end: Api hands back the issues it was constructed with."""
    from outwarp.api import Api
    from outwarp.logs import MemoryLogHandler

    mh = MemoryLogHandler()
    issues = [IntegrityIssue("wstunnel", "/x/wst.exe", "missing", "gone")]
    with patch("outwarp.api._load_settings", return_value={}):
        api = Api(mh, manager=None, integrity_issues=issues)
    report = api.get_integrity()
    assert report["ok"] is False
    assert report["likely_av"] is True
    assert report["issues"][0]["name"] == "wstunnel"


def test_api_get_integrity_empty_by_default():
    from outwarp.api import Api
    from outwarp.logs import MemoryLogHandler

    mh = MemoryLogHandler()
    with patch("outwarp.api._load_settings", return_value={}):
        api = Api(mh, manager=None)
    report = api.get_integrity()
    assert report == {"ok": True, "likely_av": False, "issues": []}
