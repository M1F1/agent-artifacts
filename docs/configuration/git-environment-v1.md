# The environment AART gives Git

Every remote AART reaches — a configured source, a promoted native reference, a vendored subtree —
is reached by running system Git. AART holds no credentials of its own;
[`compatibility-v10-addendum.md`](../release/compatibility-v10-addendum.md) states that rule and
this page states the mechanism underneath it: **the Git subprocess is given an allowlisted
environment, not the operator's.**

Everything not named below is dropped. That is the design, and it is why a machine that can clone a
repository at a shell prompt can still fail to clone it through AART. This page exists so that
failure has a name.

## What Git receives

| Variable | Why it is passed |
|---|---|
| `HOME` | Git's own configuration lives there — `~/.gitconfig`, `~/.ssh/config`, the credential helper the machine already uses |
| `PATH` | Git resolves its own subprocesses, including `git-credential-*` helpers and `ssh` |
| `SSH_AUTH_SOCK` | the agent holding the key for an SSH remote |
| `XDG_CONFIG_HOME` | `~/.config/git/config` when the machine puts it there instead |
| `SYSTEMROOT` | Windows needs it for sockets; without it TLS fails before any repository is reached |

## What AART sets

Both are set by AART, not inherited. Whatever the operator's environment says, Git sees these:

| Variable | Value | Why |
|---|---|---|
| `GIT_TERMINAL_PROMPT` | `0` | a repository that needs an interactive credential fails instead of hanging — AART runs unattended more often than not |
| `LC_ALL` | `C` | Git's messages are parsed. A localised message is a message AART reads wrongly |

## What Git does not receive

Proxy configuration is the case that costs an operator an afternoon, so it is named here in full.

| Variable | What happens |
|---|---|
| `https_proxy` | dropped |
| `http_proxy` | dropped |
| `no_proxy` | dropped |
| `ALL_PROXY` | dropped |
| `GIT_SSH_COMMAND` | dropped — set `core.sshCommand` in Git's own configuration instead |
| `GIT_CONFIG_GLOBAL` | dropped — Git finds the global file through `HOME` |

**On a network whose only egress is a proxy, every AART command that touches a remote fails**, with
whatever transport error Git produces and no mention of a proxy. The proxy was exported in the
shell, so it looks like it was in effect. It was not.

This is deliberate. A proxy URL is one of the ordinary places a credential hides —
a proxy address carrying `user:token` in its userinfo is a
supported and common form — and AART's rule is that it
never carries a credential it was not handed on purpose.

**The route that works** is Git's own configuration, because `HOME` is passed:

```bash
git config --global http.proxy http://proxy.example:3128
```

`http.proxy` covers HTTPS remotes too, despite the name. For a proxy that needs credentials, keep
them out of the value and let the OS hold them — a credential helper, or a local unauthenticated
listener that forwards to the authenticated one. `http.<url>.proxy` scopes the setting to one host
if a global proxy is not wanted. An SSH remote goes through `~/.ssh/config` — `ProxyCommand` or
`ProxyJump` — for the same reason: it is Git's configuration, and Git can read it.

## Diagnosing it

A clone that works at the prompt and fails under AART, with a connection error and nothing about
proxies, is this. Confirm it in one step: unset the proxy variables in a shell and run the same
`git clone` by hand. If that reproduces the failure, the proxy was never reaching Git, and the
`git config` line above is the fix.

## Keeping this page true

`tests/git_environment_docs_test.py` reads the three tables here and compares them against
`agent_artifacts/io/git.py` — the allowlist against `_ALLOWED_ENVIRONMENT`, and every variable this
page calls dropped against what `_safe_environment` actually returns. A variable added to the code
and not to this page fails the suite, which is the only reason to trust a list published in prose.
