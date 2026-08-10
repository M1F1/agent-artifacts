# Confidential-content-free company registry bootstrap v1

A company registry is optional. Users may configure only direct public/private native sources, one
or more registries, or a reviewed company registry plus team sources. AART never infers a default
registry or reporting destination from an artifact upstream.

Start from a new private Git checkout using organization-neutral placeholders:

```bash
mkdir company-agent-artifacts-registry
cd company-agent-artifacts-registry
git init -b main

aart registry init \
  --source "$PWD" \
  --source-id company-agent-artifacts \
  --display-name "Company Agent Artifacts"

aart registry scaffold \
  --source "$PWD" \
  skill example-skill \
  --summary "Explain the reviewed capability in one useful sentence." \
  --profile codex \
  --platform darwin

aart registry format --source "$PWD"
aart registry lock --source "$PWD"
aart registry build --source "$PWD"
aart registry validate --source "$PWD" --strict --frozen
aart registry audit --source "$PWD"
aart registry test --source "$PWD"
```

`registry init` installs the minimum/latest GitHub Actions matrix before artifacts are published.
Keep the repository private until its organization-specific review is complete. Replace the sample
artifact, declare a license and provenance for every owned package, review setup effects, and use
organization policy to recommend or require the registry where appropriate.

Do not commit credentials, usage exports, user paths, local AART config, private clone URLs in
public-facing examples, generated dashboards, caches, or build output. Configure private source
URLs and an optional reporting service only inside the private deployment through explicit policy.
AART never commits or pushes maintainer changes automatically.
