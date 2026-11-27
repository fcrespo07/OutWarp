# Contracts frozen at 1.0

What 1.0 freezes (see `CLAUDE.md` → "Criterio de 1.0.0"). CI fails if it changes by accident:

| Contract | Guard |
|---|---|
| `outwarp` CLI: subcommands, flags, choices | `client/tests/test_contract_cli.py` ↔ `cli-client.json` |
| `outwarp-server` CLI | `server/tests/test_contract_cli.py` ↔ `cli-server.json` |
| `.owcfg` / `config.json` shape and `schema_version` | `client/tests/test_contract_config.py` |

Help texts are not part of the contract (they are translated). To accept an
intentional **addition**, regenerate the snapshot:

```
python scripts/dump_cli_contract.py client > docs/contracts/cli-client.json
python scripts/dump_cli_contract.py server > docs/contracts/cli-server.json
```

Removing or renaming something after 1.0 is a breaking change (`feat!:` → 2.0, or ship a migration).
