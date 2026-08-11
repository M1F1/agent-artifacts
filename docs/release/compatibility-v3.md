# AART 1.1.1 compatibility matrix

This document freezes the supported executable and protocol boundary for AART `1.1.1`. The
`1.0.0` and `1.1.0` boundaries remain recorded, unedited, in
[`compatibility-v1.md`](compatibility-v1.md) and
[`compatibility-v2.md`](compatibility-v2.md).

| Boundary | Supported in 1.1.1 | Gate |
|---|---|---|
| Python | CPython 3.10–3.14 | Full `make quality` matrix on 3.10 and 3.14 |
| Runtime dependencies | Python standard library only | Import and wheel metadata audit |
| Platforms | macOS and Linux | Protocol/store/install fixtures; setup effects are macOS-only |
| Harness profiles | Claude, OpenCode, Tabnine, Vibe | Built-in profile loading and registry compatibility |
| Source transport | Local directories and Git repositories | Local/Git acquisition and immutable snapshot tests |
| Registry | Optional; zero, one, or many | Direct-only and public/company/team system scenarios |
| Installation scopes | Project and user | Canonical state, path, lifecycle, and migration tests |
| Installation modes | Copy and immutable managed Symlink | Distribution/environment recreation smoke |
| Native Source/Registry Protocol | v1 with optional artifact `requires_aart` | Strict parsers, canonical writers, frozen schema evidence |
| Installation state | v2 (unchanged) | 0.1 migration/apply/rollback fixtures |
| Configuration schema | v1, unchanged from 1.1.0 | Round-trip and multi-ref parser tests |
| Source store layout | v2, unchanged from 1.1.0 | Migration planning/apply and crash-resume tests |
| Executable delivery | Local editable checkout or local wheel | Index-free distribution smoke |

## Patch boundary

`1.1.1` implements the artifact-level `requires_aart` boundary that the `1.1.0` compatibility
document required registry skills to declare but the `1.1.0` parser did not accept. The optional
object uses `min_inclusive` and/or `max_exclusive` SemVer values. It is preserved in canonical
artifact manifests and compiled indexes and appears in marketplace JSON only when constrained.
Agent-facing `marketplace list --json` also reports the running `aart_version`, an
`aart_compatible` boolean for each item, and a warning when installation is disabled. Human
marketplace output keeps the artifact visible and names the required range; the TUI marks the row
unavailable and exposes the same reason.

The bound is manual and capability-driven:

- omitting it means no artifact-specific executable restriction;
- a maintainer adds or raises it only because the artifact uses behavior absent below that version;
- releasing or patching AART does not rewrite or infer the field;
- a failed bound rejects only the selected artifact with `aart-version-unsupported` when evaluated
  by an executable that supports this field.

The source/registry marker retains its independent source-wide range. These two ranges must not be
conflated.

## Bootstrap compatibility

`1.1.0` rejects the new artifact field as unknown before it can evaluate an artifact-local bound.
Consequently, the first source revision that authors the field must declare a source-level parser
minimum of `1.1.1`. This is a one-time schema-reader floor, not a rule that follows future patch
versions. Artifacts in sources that omit the field remain readable and installable under their
existing source bounds.

For the REG02 skills, the artifact's functional minimum is still the first executable that exposes
the documented commands (`1.1.0`), while the registry revision containing the new field requires a
`1.1.1` parser. Future AART releases do not raise either value unless the registry begins using a
new capability.
