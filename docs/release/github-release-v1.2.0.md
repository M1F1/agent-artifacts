# AART 1.2.0

AART `1.2.0` adds two marketplace conveniences while keeping artifact installation independent from
the runtime in which an artifact will eventually execute.

Collections are now selectable directly in canonical CLI/JSON lifecycle commands and in the human
TUI. A qualified collection expands to its exact compiled, versioned members before Review, so
Finalize still applies one deterministic plan.

Registries can also publish advisory runtime metadata such as Python `>=3.11.0`. A consuming
repository supplies an explicit environment inventory and asks:

```shell
aart marketplace health reference/collection/residuality \
  --environment .agent-artifacts/runtime-environment.json --json
```

The report distinguishes `satisfied`, `unsatisfied`, and `unknown`, but never controls installation.
AART does not probe or provision runtimes, and valid health reports exit successfully regardless of
observation status. Repositories remain responsible for their own environment and execution policy.

The native Source/Registry Protocol remains v1 and the installed AART runtime still uses only the
Python standard library. Existing AART `1.1.1` clients ignore the namespaced advisory metadata,
continue to install artifacts, and can install collection members individually. Registry and
artifact `requires_aart` floors are not raised automatically by this release.

See the [`1.2.0` compatibility matrix](compatibility-v4.md) for the exact boundary.
