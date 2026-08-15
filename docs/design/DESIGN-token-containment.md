# Design — token containment

**The property this design is for:** a token exists in exactly one place, the macOS Keychain. AART
never shows it and never writes it to disk. Not in a log, not in a receipt, not in an error message,
not in a `--json` payload, not on screen.

Written for `RR-10`, after the `2.6.0` triage brief. Three findings started it (`LAF-63`, `LAF-66`,
`LAF-65`); measuring them found a fourth (`LAF-72`) that is larger than the three.

---

## 1. What is already correct, and must not be broken

The important part of this property is already true, and it is worth writing down before changing
anything, because the obvious "fix" would destroy it.

**AART never receives the secret.** The Keychain step runs:

```
/usr/bin/security add-generic-password -a <account> -s <service> -w
```

`-w` with **no value after it**. The `security` tool then prompts on the terminal itself and reads
the value without echo. The bytes go from the keyboard into Keychain. They never pass through an
AART variable, an argv list, or a pipe.

Two consequences that the rest of this design must preserve:

- The process call for that step uses `capture=False`. Nothing captures its output, on purpose.
- `shell.env-from-keychain@1` does not write the value into `.zshrc`. It writes a *lookup*:

  ```sh
  export DATABASE_URI="$(/usr/bin/security find-generic-password -a default -s aart/... -w)"
  ```

  So the shell file holds the question, not the answer.

**This is the design that already exists and it is right.** The problem is not the path the secret
takes. The problem is every *other* path, where text that happens to contain a token can travel.

## 2. What is actually broken

A token does not only arrive through the Keychain step. It arrives as ordinary text in places nobody
labelled "secret":

- a `docker build` transcript that contains `--build-arg GITHUB_TOKEN=ghp_...`
- an error message containing a clone URL: `https://user:ghp_...@github.example.com/org/repo.git`
- a step detail containing a query string: `...?access_token=ghp_...`

AART tries to strip these with a function called `redact_text`. There are **two** of them, they are
different, and the weaker one is the one that writes to disk.

Measured on `2026-08-15`:

| Text | `setup.py` version | `policy.py` version |
|---|---|---|
| `GITHUB_TOKEN=ghp_bbb` | **leaks** | **leaks** |
| `https://mifi:ghp_ccc@github.example.com/org/repo.git` | **leaks** | hidden |
| `?access_token=ghp_ddd` | **leaks** | hidden |
| `--build-arg NPM_TOKEN=npm_eee` | **leaks** | **leaks** |

Two separate defects:

**`LAF-63` — prefixed names are not matched.** Both patterns require a word boundary directly before
`token`, `secret`, `password`, `api_key`. In `GITHUB_TOKEN` the position before `TOKEN` sits between
two word characters, so there is no boundary and no match. `TOKEN=` is caught; `GITHUB_TOKEN=` is
not. The prefixed forms are the ones real projects use.

**`LAF-72` — the file on disk is redacted by the weaker function.** `dump_setup_state` writes the
setup record through `setup.py`'s `redact_text` only. That one knows nothing about URL credentials or
query strings. `setup_engine/application.py` applies both functions, but only to diagnostics. So the
thing that *persists* is protected by less than the thing that is merely *displayed*.

The URL row matters most for what comes next: a GitHub Enterprise clone URL with a token in it is
exactly that shape.

## 3. Why this keeps happening

Redaction is applied **at call sites**. Someone writing a new step, a new renderer, or a new error
path has to remember to call the right redactor, and there are two to choose from.

That is the same defect as `LAF-66` one level up, and as `LAF-69` one level up again: a check exists,
it is correct for the case its author had in mind, and the general claim made for it is wider than
what it does. The fix is never a better regex. The fix is putting the check where forgetting it is
impossible.

## 4. The design

### 4.1 One redactor

Delete one of the two. Keep a single `redact_text` with all four rules:

1. URL credentials — `scheme://user:pass@host` → `scheme://[redacted]@host`
2. Query parameters — `?token=`, `?access_token=`, `?api_key=`, `?key=`, `?secret=`, `?password=`
3. Assignments — `NAME=value` where `NAME` **contains** a sensitive word, with any prefix or suffix
4. Known credential shapes — `ghp_`, `github_pat_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `xox[bpsar]-`,
   `AKIA[0-9A-Z]{16}`, `sk-`, and PEM private key blocks

Rule 3 is `LAF-63`'s fix, and the change is to stop anchoring on a word boundary. Rule 4 is new and
is the important one: it catches a token that appears with **no name next to it at all** — the case
where a transcript prints the value alone on a line.

Both existing call-site names stay as aliases for one implementation, so nothing outside has to
change in this package.

### 4.2 Redact at the exits, not at the call sites

Every way text can leave AART gets redaction applied at the boundary:

| Exit | Where the boundary is |
|---|---|
| The persisted setup record | `dump_setup_state` |
| Diagnostics | `Diagnostic` construction |
| Terminal output | the one renderer entry point |
| `--json` payloads | the one payload serialiser |
| Files written under a run directory | the run-directory writer |

An inner function may still redact; the point is that it no longer *has* to, because the boundary
does it again. Redaction is idempotent, so applying it twice is free.

### 4.3 The test that makes it stay true

One test, and it is the deliverable that matters more than the regex.

Plant a set of known token strings. Run a full setup, a failing setup, an undo, a `receipt show`, a
`receipt verify`, and both front-ends. Then assert that **no planted token appears** in:

- anything printed to stdout or stderr
- the persisted setup state file
- any file under the run directory
- any `--json` payload
- the `.zshrc` block, or any managed file

The test enumerates channels, not call sites. A new channel that forgets redaction fails it without
anybody remembering to extend a list — the same technique the receipt renderer test already uses.

### 4.4 What this design does *not* do

**It does not clean records already on disk.** Files written by `2.5.0` and `2.6.0` keep whatever is
in them. Rewriting a persisted record would destroy evidence of what a run actually did, which is the
entire reason receipts exist.

Instead: `receipt verify` gains one claim — *does this record contain anything that looks like a
credential?* — and reports it. Reporting, never repairing, exactly like every other claim. The
operator then deletes the record themselves, which is a decision AART should not take for them.

**It does not stop a recipe author writing a token into a file on purpose.** A recipe that declares
`file.managed-block@1` with a literal secret in the block will store that secret. The review shows
the block before consent. That is a review problem, not a redaction problem, and it stays out of
scope.

## 5. The other two findings

Both are small and both are in the same release, so they belong in the same piece of work.

### `LAF-66` — the orphan check looks in the wrong folder

`orphan_run_directories` scans `<project_root>/.agent-artifacts/setup-runs/`. Runs are created under
`<data_root>`, because `setup_engine/application.py` passes `run_root=location.data_root`. The two
are never the same folder, so the claim answers `true` without looking.

Fix: the probe takes the run root it is actually verifying against, from the same source the run used.

Acceptance: place a real leftover folder where runs really are, and the claim must report `false` and
name the full path. That is the measurement that caught it, so it is the measurement that closes it.

### `LAF-65` — the record contradicts the program that wrote it

Every record carries `rollback_command`, and its text says *no command reverses a completed setup*.
`2.6.0` adds `aart marketplace receipt undo`.

Fix: the field names the real command.

Acceptance: a test that builds the command string with the real CLI parser and fails if it does not
parse. The remediation guard already does exactly this for user-visible `aart …` mentions; this
extends it to a field the program *writes* rather than prints. That is what stops the sentence going
stale a second time.

## 6. How we will know it worked

Seven criteria. Each is a measurement, not an opinion.

1. `GITHUB_TOKEN=`, `AWS_SECRET_ACCESS_KEY=` and `MY_API_KEY=` are hidden by the single redactor.
2. A clone URL with credentials is hidden **in the persisted record**, not only in a diagnostic.
3. A bare `ghp_…` value with no name beside it is hidden.
4. The channel test passes: no planted token in stdout, stderr, the state file, run-directory files,
   `--json`, or any managed file.
5. `receipt verify` reports `false` for a real leftover run folder placed where runs are actually
   created.
6. `receipt verify` reports a record that contains credential-shaped text, and does not change it.
7. The `rollback_command` string parses with the real CLI parser.

Criterion 2 is the one to check first. It is the shape a GitHub Enterprise setup produces, and it is
the one the current code gets wrong on the path that reaches disk.
