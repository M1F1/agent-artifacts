# AART 2.2.0 compatibility addendum — credentials and private hosts

[`compatibility-v10.md`](compatibility-v10.md) records what `2.2.0` added, and correctly records no
change to how AART reaches a remote. It does not state what that mechanism *is*, and until `2.3.0`
the package still contained a module implying something else. This addendum states the rule. Like
[`compatibility-v8-addendum.md`](compatibility-v8-addendum.md), it is written during a later release
and changes nothing about the one it names: it says what has been true since `2.0.0`.

## The rule

**AART holds no credentials of its own.** There is no token field, no `--token` flag, and no
environment variable AART reads to authenticate to a host. Every remote — a configured source, a
promoted native reference, a vendored subtree — is reached by running system Git, and Git is what
authenticates.

A private or GitHub Enterprise origin is therefore reached the way that machine already reaches it:

| Route | Where it is configured |
|---|---|
| SSH key | `~/.ssh/config` and the agent behind `SSH_AUTH_SOCK` |
| Git credential helper | `git config credential.helper`, the OS keychain behind it |
| URL rewriting for a mirror or Enterprise host | `git config url.<base>.insteadOf` |

The Git subprocess receives `HOME` and `SSH_AUTH_SOCK` and a deliberately narrow environment
otherwise; `GIT_TERMINAL_PROMPT=0` means a repository that needs an interactive credential fails
instead of hanging. Nothing about that changed in `2.1.0`, `2.2.0`, or `2.3.0`.

## What `2.3.0` removes

`agent_artifacts/io/net.py` — a GitHub REST client left from the pre-`2.0.0` batch importer,
imported by nothing but its own test. It read `GITHUB_TOKEN` and `GITHUB_API_URL` and, on a `401` or
`404`, told the reader to set them and point at an Enterprise `/api/v3` endpoint. No shipping
command called it, so that advice did nothing: it advertised a capability the product does not have.
The removal changes no behaviour, and a repository that fails to clone today fails identically after
it. What changes is that the package no longer contradicts this page.

The `validate` gate now fails if any module under `agent_artifacts/` names either variable, so the
promise cannot come back by accident. See
[`DESIGN-registry-vendoring.md`](../design/DESIGN-registry-vendoring.md) §9.

## What this does not say

It does not say AART cannot reach private hosts — it can, wherever Git can. It does not say
credentials are unnecessary; it says they are the machine's and Git's, held where the operating
system already protects them, and never passed through, stored by, or logged by AART.
