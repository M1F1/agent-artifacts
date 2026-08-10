# AART 1.0.0 compatibility matrix

This document freezes the supported executable and protocol boundary for AART `1.0.0`.

| Boundary | Supported in 1.0.0 | Gate |
|---|---|---|
| Python | CPython 3.10–3.14 | Full `make quality` matrix on 3.10 and 3.14 |
| Runtime dependencies | Python standard library only | Import and wheel metadata audit |
| Platforms | macOS and Linux | Protocol/store/install fixtures; setup effects are macOS-only |
| Harness profiles | Claude, OpenCode, Tabnine, Vibe | Built-in profile loading and registry compatibility |
| Source transport | Local directories and Git repositories | Local/Git acquisition and immutable snapshot tests |
| Registry | Optional; zero, one, or many | Direct-only and public/company/team system scenarios |
| Installation scopes | Project and user | Canonical state, path, lifecycle, and migration tests |
| Installation modes | Copy and immutable managed Symlink | Distribution/environment recreation smoke |
| Native Source/Registry Protocol | v1 | Strict parsers, canonical writers, frozen schema evidence |
| Installation state | v2 | 0.1.x migration/apply/rollback fixtures |
| Setup | Reviewed recipe protocol v1; macOS effects | Fake Keychain/process, partial/retry/rollback tests |
| Security assessment | Baseline/provider/attestation schema v1 | Provider failure and bundle policy matrices |
| Usage reporting | Optional; disabled without destination | Absent/failure-isolation matrix |
| Executable delivery | Local editable checkout or local wheel | Index-free distribution smoke |

The public `M1F1/agent-artifacts-registry` declares AART `>=1.0.0,<2.0.0`; its native source remains
compatible with the prerelease range used to create its initial content. Registry capability and
SemVer handshakes—not an exact executable patch—decide compatibility.

Not supported in `1.0.0`: Nexus/PyPI delivery, non-Git remote transports, external importer
plugins, moving-channel managed links, cryptographic signing, automatic maintainer commits/PRs,
or non-macOS setup effects. None is required to migrate to a future indexed AART package.
