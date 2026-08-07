# aart setup protocol version 1

Top-level fields are closed-world: `schema_version`, `protocol_version`, `artifact`, `purpose`,
`platforms`, `help_urls`, `required_tools`, `capabilities`, `inputs`, `steps`, and optional
`custom_entrypoint`.

Shared modules:

- `macos-keychain.store@1` — `keychain`
- `shell.env-from-keychain@1`, `file.managed-block@1`, `json.managed-merge@1`,
  `directory.create@1` — `filesystem`
- `docker.pull@1` — `docker`, `network`, `process`
- `command.verify@1` — `process`
- `restart.notice@1` — no capability

The runtime plans exact non-secret effects, hashes the canonical plan, asks for granular consent,
applies one installer transaction, verifies, records a redacted receipt, and rolls back completed
reversible effects in reverse order on failure. An item always ends in a terminal status. Queue
failures continue by default; explicit Stop marks unstarted items `skipped`.

Custom entrypoints receive only allowlisted non-secret `AART_SETUP_*` metadata and fixed argv:

```text
install.sh plan --json --result RESULT
install.sh apply --plan-hash HASH --result RESULT
install.sh verify --json --result RESULT
install.sh rollback --receipt RECEIPT --result RESULT
```
