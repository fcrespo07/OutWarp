"""Print the documented CLI surface (subcommands, flags, choices) as JSON.

Used by the contract tests: ``python scripts/dump_cli_contract.py client|server``
regenerates ``docs/contracts/cli-*.json``. Help texts are deliberately left out
(they are translated and not part of the frozen contract).
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def surface(parser: argparse.ArgumentParser) -> dict:
    """Describe a parser: options, positionals and (recursively) subcommands."""
    options: list[dict] = []
    positionals: list[dict] = []
    commands: dict[str, dict] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helped = {c.dest for c in action._choices_actions}
            for name, sub in action.choices.items():
                entry = surface(sub)
                # Subcommands registered without help= are internal.
                entry["documented"] = name in helped
                commands[name] = entry
            continue
        if isinstance(action, argparse._HelpAction):
            continue
        item = {
            "dest": action.dest,
            "choices": sorted(map(str, action.choices)) if action.choices else None,
            "nargs": action.nargs,
            "required": bool(getattr(action, "required", False)),
        }
        if action.option_strings:
            item["flags"] = sorted(action.option_strings)
            options.append(item)
        else:
            positionals.append(item)
    out = {
        "options": sorted(options, key=lambda o: o["flags"]),
        "positionals": positionals,
    }
    if commands:
        out["commands"] = dict(sorted(commands.items()))
    return out


def load(which: str) -> dict:
    os.environ["OUTWARP_LANG"] = "en"
    if which == "client":
        from outwarp.cli import build_parser
    else:
        from outwarp_server.cli import build_parser
    return surface(build_parser())


if __name__ == "__main__":
    print(json.dumps(load(sys.argv[1]), indent=2, sort_keys=True))
