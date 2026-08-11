# AART 1.3.1

AART `1.3.1` fixes the non-mutating CLI/JSON Review for `aart marketplace setup`.

Agents can now inspect the exact setup plans attached to already-installed artifacts before deciding
whether to run them. Review still performs no mutation, supplies no credential, and grants no source,
custom-code, or effect authorization. Canonical installed-record, immutable-object, trust, policy,
and recipe checks remain authoritative; a missing proof is reported as a planning failure.

There are no protocol or schema changes, no runtime dependencies, and no registry or artifact
compatibility-floor increases. See the [1.3.1 compatibility matrix](compatibility-v6.md) and
[release evidence](release-checklist-v6.md).
