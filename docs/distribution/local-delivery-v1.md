# AART 1.0 local delivery and future index boundary

## Status and scope

AART `1.0.0` is delivered from a local checkout or a local wheel. Nexus/PyPI publication,
automatic version discovery, and automatic self-update are deliberately out of scope. The wheel
has zero unconditional Python runtime dependencies.

## Install from a checkout

The editable path needs a compatible build backend already present in the environment. It never
downloads that backend:

```sh
python -m pip install \
  --no-index \
  --no-deps \
  --no-build-isolation \
  --editable /path/to/agent-artifacts
```

## Build and install a wheel

The repository's Python 3.11+ wheel builder uses only the standard library:

```sh
cd /path/to/agent-artifacts
make wheel
python -m pip install \
  --no-index \
  --no-deps \
  dist/agent_artifacts-1.0.0-py3-none-any.whl
```

The wheel allowlist contains executable Python modules and package resources only below
`schemas/`, `profiles/`, `importers/`, or `templates/`. It rejects operational artifact/registry
content and unexpected package data. The packaging gate independently rejects duplicate, unsafe,
or out-of-bound archive members and unconditional `Requires-Dist` metadata.

## Explicit replacement

`aart upgrade` is an explicit local replacement boundary, not a release resolver:

```sh
aart upgrade --wheel /path/to/agent_artifacts-1.0.0-py3-none-any.whl --dry-run
aart upgrade --wheel /path/to/agent_artifacts-1.0.0-py3-none-any.whl

aart upgrade --source-checkout /path/to/agent-artifacts --dry-run
aart upgrade --source-checkout /path/to/agent-artifacts
```

Exactly one source is required. Wheel and checkout paths must be real local files/directories, not
symlinks. The fixed pip plan includes `--no-index --no-deps --force-reinstall`; editable installs
also include `--no-build-isolation --editable`. There is no implicit repository, version, Nexus,
or PyPI fallback.

## Environment-independent managed data

The executable environment owns only AART code and the console entry points. These remain outside
it:

- user configuration;
- Git mirrors and validated source snapshots;
- content-addressed artifact objects;
- project/user installation state;
- installed Copy destinations and managed Symlink destinations.

Canonical Symlink mode targets an immutable object under the AART user data directory. It does not
target the editable checkout, wheel environment, or moving source checkout. Recreating the Python
environment therefore cannot break an installed managed link. A later reviewed source sync and
artifact update may select a new immutable object.

## Reproducible smoke proof

Run:

```sh
python scripts/distribution_smoke.py --json
```

The hermetic runner creates disposable editable and wheel environments, invokes AART from outside
the checkout, synchronizes a local native source, installs one Copy and one Symlink, removes the
editable environment, resumes from the wheel environment, checks status, uninstalls/reinstalls,
removes the wheel environment, and verifies the managed link after both removals. It uses only
temporary config/data/home/project paths and never contacts an index.

## Future Nexus readiness

A future Nexus release may supply a wheel to an external package installer or add an explicitly
configured, policy-controlled version resolver. That work must not change the source protocol,
registry protocol, source configuration, snapshot/CAS layout, installation state, or managed
Symlink semantics. Index credentials and Nexus/PyPI publication automation are not implemented
here; the GitHub release workflow only builds and attaches the reviewed local wheel.
