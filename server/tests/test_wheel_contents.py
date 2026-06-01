"""Smoke test for the server wheel. See the matching test in
``client/tests/test_wheel_contents.py`` for the rationale - same defensive
contract on what the published artifact must contain."""
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

    wheels = list(outdir.glob("outwarp_server-*.whl"))
    assert len(wheels) == 1, f"expected exactly one server wheel, got {wheels}"
    return wheels[0]


REQUIRED_PATHS = [
    "outwarp_server/__init__.py",
    "outwarp_server/api.py",
    "outwarp_server/cli.py",
    "outwarp_server/server_manager.py",
    "outwarp_server/wireguard.py",
    "outwarp_server/crypto.py",
    "outwarp_server/setup_wizard.py",
    # Platform abstraction modules.
    "outwarp_server/platforms/__init__.py",
    "outwarp_server/platforms/linux.py",
    "outwarp_server/platforms/windows.py",
    "outwarp_server/platforms/kubernetes.py",
    # UI assets - the admin GUI loads them at file:// boot time.
    "outwarp_server/ui/index.html",
    "outwarp_server/ui/bundle.js",
    "outwarp_server/ui/styles.css",
    "outwarp_server/ui/fonts/Geist-Variable.woff2",
    "outwarp_server/ui/fonts/GeistMono-Variable.woff2",
    "outwarp_server/ui/fonts/OFL.txt",
    # TUI stylesheet.
    "outwarp_server/tui/styles.tcss",
    # Tray/admin icons.
    "outwarp_server/resources/app_icon.png",
    "outwarp_server/resources/app_icon.ico",
]


@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_wheel_contains(built_wheel: Path, path: str) -> None:
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    assert path in names, f"{path} missing from {built_wheel.name}"


def test_wheel_has_entry_points(built_wheel: Path) -> None:
    """0.5.0 collapsed the server onto a single ``outwarp-server`` entry-point.
    The pywebview admin lives at ``outwarp-server gui`` as a subcommand, not
    as a separate ``outwarp-server-gui`` binary. Asserting the OLD name is
    absent catches accidental re-additions in pyproject.toml."""
    with zipfile.ZipFile(built_wheel) as zf:
        ep_paths = [n for n in zf.namelist() if n.endswith("/entry_points.txt")]
        assert ep_paths, "no entry_points.txt in wheel"
        content = zf.read(ep_paths[0]).decode()
    assert "outwarp-server" in content
    assert "outwarp-server-gui" not in content, \
        "stray 0.4.x `outwarp-server-gui` entry-point in wheel"


def test_wheel_excludes_caches_and_tests(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()
    leaked = [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    assert not leaked, f"cache files leaked into wheel: {leaked[:5]}"
    test_files = [n for n in names if "/tests/" in n or n.startswith("tests/")]
    assert not test_files, f"test files leaked into wheel: {test_files[:5]}"
