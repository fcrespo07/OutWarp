"""Contract test: the documented `outwarp` CLI surface is frozen at 1.0.

If this fails you changed a subcommand, flag, choice or positional. After 1.0
that is a breaking change (`feat!:` -> 2.0) unless it only *adds* something; for
an intentional addition regenerate the snapshot:

    python scripts/dump_cli_contract.py client > docs/contracts/cli-client.json
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dumper():
    spec = importlib.util.spec_from_file_location(
        "dump_cli_contract", ROOT / "scripts" / "dump_cli_contract.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_surface_matches_snapshot() -> None:
    expected = json.loads((ROOT / "docs" / "contracts" / "cli-client.json").read_text())
    actual = json.loads(json.dumps(_load_dumper().load("client")))
    assert actual == expected
