# AART 1.0.0

AART `1.0.0` is the first stable release of the standalone agent-artifact compiler and package
manager. It installs canonical skills, guidelines, MCP configurations, hooks, and memory from any
compatible local/Git source plus optional public, company, team, or private registries.

Highlights:

- deterministic federated marketplace with source-qualified identity and local trust policy;
- durable Copy and immutable managed Symlink installs across project/user scopes;
- source health, offline last-known-good, CAS repair, lifecycle, and migration/rollback;
- reviewed User/Maintainer TUI, setup queues, security evidence, and optional usage reporting;
- strict Registry Protocol v1 quality gates and independent public reference registry;
- zero runtime Python dependencies and local editable/wheel delivery without Nexus/PyPI.

Breaking migration: the executable no longer treats its package-local catalog as the default
marketplace. Configure explicit sources and follow the
`0.1.x migration guide`. Existing state can be previewed, backed up, migrated, and
rolled back exactly.

See the [changelog](../../CHANGELOG.md), [compatibility matrix](compatibility-v1.md), and
[release evidence](release-checklist-v1.md).
