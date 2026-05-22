from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

from outwarp import updater
from outwarp.updater import (
    LINUX_UPDATE_COMMAND,
    _is_newer,
    _parse_version,
    check_for_update,
    download_installer,
)


def _cm(resp):
    """Wrap a response mock so it works with `with urlopen(...) as resp`."""
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


def _json_resp(payload):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    return _cm(resp)


# ── version parsing / comparison ────────────────────────────────────────────

def test_parse_version_strips_v_and_suffix():
    assert _parse_version("v0.1.10") == (0, 1, 10)
    assert _parse_version("0.1.4") == (0, 1, 4)
    assert _parse_version("1.2.3-rc1") == (1, 2, 3)


def test_is_newer_basic():
    assert _is_newer("0.1.5", "0.1.4") is True
    assert _is_newer("0.2.0", "0.1.9") is True
    assert _is_newer("0.1.4", "0.1.4") is False
    assert _is_newer("0.1.3", "0.1.4") is False


def test_is_newer_double_digit_components():
    # String comparison would call 0.1.9 newer than 0.1.10 — int tuples must not.
    assert _is_newer("0.1.10", "0.1.9") is True
    assert _is_newer("0.1.9", "0.1.10") is False


def test_is_newer_handles_v_prefix_and_uneven_length():
    assert _is_newer("v0.1.5", "0.1.4") is True
    assert _is_newer("0.1", "0.1.0") is False
    assert _is_newer("0.2", "0.1.9") is True


def test_is_newer_empty_latest_is_false():
    assert _is_newer("", "0.1.4") is False


# ── check_for_update ────────────────────────────────────────────────────────

_RELEASE = {
    "tag_name": "v0.1.5",
    "body": "Fix reconnect; sign installer",
    "html_url": "https://github.com/fcrespo07/OutWarp/releases/tag/v0.1.5",
    "assets": [
        {"name": "checksums.txt", "browser_download_url": "https://x/c.txt", "size": 10},
        {
            "name": "OutWarpSetup-0.1.5.exe",
            "browser_download_url": "https://x/OutWarpSetup-0.1.5.exe",
            "size": 50_000_000,
        },
    ],
}


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_detects_newer_and_picks_installer_asset(mock_urlopen):
    mock_urlopen.return_value = _json_resp(_RELEASE)
    r = check_for_update("0.1.4")
    assert r["available"] is True
    assert r["latest"] == "0.1.5"
    assert r["notes"] == "Fix reconnect; sign installer"
    assert r["asset_name"] == "OutWarpSetup-0.1.5.exe"
    assert r["asset_url"] == "https://x/OutWarpSetup-0.1.5.exe"
    assert r["asset_size"] == 50_000_000
    assert r["html_url"].endswith("/v0.1.5")


def _asset(name, url):
    return {"name": name, "browser_download_url": url, "size": 1}


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_prefers_client_edition_asset(mock_urlopen):
    payload = dict(_RELEASE, assets=[
        _asset("OutWarpSetup-0.1.5.exe", "https://x/full"),
        _asset("OutWarpSetup-Server-0.1.5.exe", "https://x/srv"),
        _asset("OutWarpSetup-Client-0.1.5.exe", "https://x/cli"),
    ])
    mock_urlopen.return_value = _json_resp(payload)
    r = check_for_update("0.1.4")
    assert r["asset_name"] == "OutWarpSetup-Client-0.1.5.exe"
    assert r["asset_url"] == "https://x/cli"


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_falls_back_to_full_when_no_client_edition(mock_urlopen):
    # Releases published before the edition split only have the combined exe.
    payload = dict(_RELEASE, assets=[_asset("OutWarpSetup-0.1.5.exe", "https://x/full")])
    mock_urlopen.return_value = _json_resp(payload)
    r = check_for_update("0.1.4")
    assert r["asset_name"] == "OutWarpSetup-0.1.5.exe"


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_never_picks_server_edition(mock_urlopen):
    payload = dict(_RELEASE, assets=[_asset("OutWarpSetup-Server-0.1.5.exe", "https://x/srv")])
    mock_urlopen.return_value = _json_resp(payload)
    r = check_for_update("0.1.4")
    assert r["asset_url"] == ""
    assert r["asset_name"] == ""


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_prefer_full_overrides_client_edition(mock_urlopen):
    # When a server is co-installed the client must take the combined installer.
    payload = dict(_RELEASE, assets=[
        _asset("OutWarpSetup-Client-0.1.5.exe", "https://x/cli"),
        _asset("OutWarpSetup-0.1.5.exe", "https://x/full"),
    ])
    mock_urlopen.return_value = _json_resp(payload)
    r = check_for_update("0.1.4", prefer_full=True)
    assert r["asset_name"] == "OutWarpSetup-0.1.5.exe"


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_same_version_not_available(mock_urlopen):
    mock_urlopen.return_value = _json_resp(_RELEASE)
    r = check_for_update("0.1.5")
    assert r["available"] is False
    assert r["latest"] == "0.1.5"


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_no_matching_asset(mock_urlopen):
    payload = dict(
        _RELEASE,
        assets=[{"name": "notes.txt", "browser_download_url": "https://x/n", "size": 1}],
    )
    mock_urlopen.return_value = _json_resp(payload)
    r = check_for_update("0.1.4")
    assert r["available"] is True
    assert r["asset_url"] == ""
    assert r["asset_name"] == ""


@patch("outwarp.updater.urllib.request.urlopen", side_effect=urllib.error.URLError("offline"))
def test_check_network_error_degrades_gracefully(_mock):
    r = check_for_update("0.1.4")
    assert r["available"] is False
    assert r["current"] == "0.1.4"
    assert "error" in r


@patch("outwarp.updater.urllib.request.urlopen")
def test_check_invalid_json_is_an_error(mock_urlopen):
    resp = MagicMock()
    resp.read.return_value = b"<html>not json</html>"
    mock_urlopen.return_value = _cm(resp)
    r = check_for_update("0.1.4")
    assert r["available"] is False
    assert "error" in r


# ── download_installer ──────────────────────────────────────────────────────

@patch("outwarp.updater.urllib.request.urlopen")
def test_download_writes_file_and_reports_progress(mock_urlopen, tmp_path):
    resp = MagicMock()
    resp.read.side_effect = [b"a" * 50, b"b" * 50, b""]
    resp.headers = {"Content-Length": "100"}
    mock_urlopen.return_value = _cm(resp)

    seen: list[int] = []
    dest = tmp_path / "OutWarpSetup-0.1.5.exe"
    out = download_installer("https://x/o.exe", dest, seen.append)

    assert out == dest
    assert dest.read_bytes() == b"a" * 50 + b"b" * 50
    assert seen[-1] == 100
    assert seen == sorted(seen)  # monotonic


@patch("outwarp.updater.urllib.request.urlopen")
def test_download_without_content_length_still_finalizes(mock_urlopen, tmp_path):
    resp = MagicMock()
    resp.read.side_effect = [b"data", b""]
    resp.headers = {}  # server omitted Content-Length
    mock_urlopen.return_value = _cm(resp)

    seen: list[int] = []
    dest = tmp_path / "x.exe"
    download_installer("https://x/o.exe", dest, seen.append)

    assert dest.read_bytes() == b"data"
    assert seen == [100]  # only the final 100% tick fires when total is unknown


def test_linux_update_command_points_at_install_sh():
    assert "install.sh" in LINUX_UPDATE_COMMAND
    assert LINUX_UPDATE_COMMAND.startswith("curl ")
    assert "fcrespo07/OutWarp" in updater._RELEASES_PAGE
