# AART 1.0 system matrix

The release system matrix is one auditable command over thirteen stable scenarios:

```shell
make system-matrix
python scripts/system_matrix.py --json
```

Each scenario runs exact `unittest` IDs in a fresh child process with its own temporary `HOME`,
`TMPDIR`, and XDG roots. Python user packages, Git prompts and global configuration, inherited
credential variables, and external Git prompts are unavailable; external HTTP traffic is forced to
a loopback refusal endpoint. The runner applies a per-scenario timeout, continues after failures,
removes the complete temporary tree, and emits a deterministic receipt without captured process
output or paths.

| Scenario | Acceptance boundary |
|---|---|
| `direct-only` | Local native source sync and canonical Copy installation without a registry |
| `public-company-team` | Optional public/company registries plus a direct team source coexist |
| `native-reference` | A native upstream is promoted by entry/lock/index reference only |
| `foreign-import` | Legacy foreign content is staged, reviewed, applied atomically, and becomes a no-op |
| `collision` | Ambiguous unqualified identity fails while a qualified company item resolves |
| `trust-downgrade` | Trust change after Review is terminal and non-mutating |
| `offline` | Cached install/lifecycle succeeds; missing cache returns a typed failure without Git |
| `concurrent-sync-install` | Concurrent source publication and installation converge without lost state |
| `corrupt-lock-object` | Stale/mismatched locks fail closed and corrupted CAS content is repaired safely |
| `setup-partial` | Setup queue stop, retry, and rollback retain per-item terminal outcomes |
| `security-provider-failure` | Optional analyzer timeout/crash/malformed output cannot become a core failure |
| `reporting-absent` | Disabled or unavailable reporting performs no provider mutation and fails closed |
| `migration-rollback` | Preview/apply and later-process rollback restore legacy state exactly |

Run one scenario while diagnosing a failure:

```shell
python scripts/system_matrix.py --scenario setup-partial --json
```

A failed receipt includes a stable diagnostic code and this exact recovery command. It deliberately
does not include child stdout/stderr because test processes may exercise credential-redaction paths.
The scenario-to-test-ID contract lives in `scripts/system_matrix.py`; changing it requires review of
this table and the runner contract tests.
