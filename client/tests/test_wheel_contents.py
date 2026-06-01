"""Smoke test for the client wheel: the published artifact must ship the
UI assets, fonts and icons that the runtime loads at startup. Without this
check, a refactor of pyproject.toml's hatch include/exclude block could
silently produce a wheel where the tray app boots into a blank window
(``file://.../ui/index.html`` 404) and we'd only catch it in a release.

The test is skipped automatically when ``python -m build`` is not available
(no dev install) so it never blocks ``pytest`` in a barebones venv.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("'build' package not installed - run pip install build")

    outdir = tmp_path_factory.mktemp("wheel")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(f"wheel build failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

    wheels = list(outdir.glob("outwarp_client-*.whl"))
    assert len(wheels) == 1, f"expected exactly one client wheel, got {wheels}"
    return wheels[0]


REQUIRED_PATHS = [
    "outwarp/__init__.py",
    "outwarp/api.py",
    "outwarp/cli.py",
    "outwarp/tunnel.py",
    "outwarp/wireguard.py",
    "outwarp/settings.py",
    # UI assets — the GUI hard-loads these by file:// path.
    "outwarp/ui/index.html",
    "outwarp/ui/bundle.js",
    "outwarp/ui/styles.css",
    "outwarp/ui/fonts/Geist-Variable.woff2",
    "outwarp/ui/fonts/GeistMono-Variable.woff2",
    "outwarp/ui/fonts/OFL.txt",
    # TUI stylesheet.
    "outwarp/tui/styles.tcss",
    # Tray icons.
    "outwarp/resources/app_icon.png",
    "outwarp/resources/app_icon.ico",
]


@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_wheel_contains(built_wheel: Path, path: str) -> None:
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    assert path in names, f"{path} missing from {built_wheel.name}"


def test_wheel_has_entry_points(built_wheel: Path) -> None:
    """0.5.0 collapsed the client onto a single ``outwarp-cli`` entry-point.
    The tray (``outwarp-cli gui``) and full-purge (``outwarp-cli uninstall``)
    are subcommands, not separate binaries. Asserting the OLD names are
    absent catches accidental re-additions in pyproject.toml."""
    with zipfile.ZipFile(built_wheel) as zf:
        ep_paths = [n for n in zf.namelist() if n.endswith("/entry_points.txt")]
        assert ep_paths, "no entry_points.txt in wheel"
        content = zf.read(ep_paths[0]).decode()
    assert "outwarp-cli" in content
    # Defensive: these 0.4.x entry-points must NOT exist in 0.5.0+ wheels.
    assert "outwarp =" not in content and "\noutwarp=" not in content, \
        "stray 0.4.x `outwarp` gui-script entry-point in wheel"
    assert "outwarp-uninstall" not in content, \
        "stray 0.4.x `outwarp-uninstall` script entry-point in wheel"


def test_wheel_excludes_caches_and_tests(built_wheel: Path) -> None:
    """Defensive: a __pycache__ or tests/ tree slipping into the wheel is a
    regression of the hatch [exclude] block."""
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()
    leaked = [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    assert not leaked, f"cache files leaked into wheel: {leaked[:5]}"
    test_files = [n for n in names if n.startswith("outwarp/tests/") or "/tests/" in n]
    assert not test_files, f"test files leaked into wheel: {test_files[:5]}"
