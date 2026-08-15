# Plan — token containment (`RR-10`)

Implements [`DESIGN-token-containment.md`](../design/DESIGN-token-containment.md).

Scope: the three findings that hold `2.6.0`, and nothing else. `LAF-63` grew into `LAF-72` when it
was measured; they are one defect on two paths and are fixed together.

The version is **not** bumped. `2.6.0` was never tagged, never pushed and never published, so these
fixes land in `2.6.0` itself rather than in a `2.6.1` that would exist only to correct a release
nobody received.

---

## Packages

### `RR-10A` — one redactor, four rules

**Files:** `agent_artifacts/configuration/policy.py`, `agent_artifacts/setup.py`

Today there are two `redact_text` functions with different rules, and `dump_setup_state` — the one
that writes to disk — uses the weaker.

One implementation, in `configuration/policy.py`, because that is the module the rest of the codebase
already imports from for policy-level text handling. `setup.py` re-exports it under the same name, so
no import outside these two files changes.

Four rules, in this order:

1. **URL credentials** — `scheme://user:pass@host` → `scheme://[redacted]@host`. Already exists.
2. **Query parameters** — `?token=`, `?access_token=`, `?api_key=`, `?key=`, `?secret=`,
   `?password=`. Already exists.
3. **Assignments** — `NAME=value` where `NAME` *contains* `token`, `password`, `passwd`, `secret`,
   `api_key`, `api-key`, `apikey`, `credential`, or `auth`. The change is dropping the leading `\b`,
   which is `LAF-63`.
4. **Bare credential shapes** — a value with no name beside it. `ghp_`, `gho_`, `ghu_`, `ghs_`,
   `ghr_`, `github_pat_`, `xox[bpsar]-`, `AKIA` + 16 upper-case alphanumerics, `sk-`, and
   `-----BEGIN … PRIVATE KEY-----` blocks.

Rule 4 is the one that changes the property rather than widening a pattern. Rules 1–3 all need the
credential to sit next to its name. A transcript that prints the value alone on a line defeats all
three.

**Deliberately not matched:** a high-entropy string with no recognisable prefix. Detecting those by
entropy would redact digests, image ids and plan hashes, which are the fields receipts exist to carry.
The design accepts this limit and states it.

**Test:** a table of inputs and expected outputs, including the four measured leaks, and one case per
rule proving the rule fires. Plus an idempotence test — `redact(redact(x)) == redact(x)` — because
§4.2 applies redaction more than once and that must be free.

### `RR-10B` — redact at the exits

**Files:** `agent_artifacts/setup.py` (`dump_setup_state`), `agent_artifacts/setup_engine/application.py`

`dump_setup_state` gets the full redactor. That single line is `LAF-72`.

`setup_engine/application.py`'s `_redact` currently composes both functions by hand
(`redact_setup(redact_config(value))`). With one implementation that composition collapses to one
call, and the double-import disappears.

**Test:** build a record whose step `detail` carries each of the four leak shapes, persist it, read
the file back as text, and assert none of the four values appears. Reading the **file**, not the
object, is the point: the object is what the code has, the file is what the operator has.

### `RR-10C` — the channel test

**File:** `tests/token_containment_test.py` (new)

The deliverable that matters more than the regex. Plant known token values, drive the real commands,
and assert the values appear in none of the exit channels:

| Channel | How it is read back |
|---|---|
| stdout, stderr | captured from the real command |
| the persisted setup record | read as raw text from disk |
| files under the run directory | walk the directory, read every file |
| `--json` payloads | serialise and search the string |
| managed files (`.zshrc`, `.mcp.json`) | read as raw text |

Driven headlessly, against a fake runtime, so it needs no Docker and no Keychain and runs in CI.

**It enumerates channels, not call sites.** A new channel that forgets redaction fails this test
without anyone remembering to extend a list — the same technique
`tests/tui_receipt_test.py`'s parity guard already uses.

### `RR-10D` — the orphan probe looks where runs are

**File:** `agent_artifacts/setup_verify_probes.py`, and its caller

`orphan_run_directories` scans `<project_root>/.agent-artifacts/setup-runs/`. Runs are created under
`<data_root>` because `setup_engine/application.py` passes `run_root=location.data_root`. The probe
takes the run root from the same source the run used, instead of deriving its own.

This is `LAF-66`, and closing it makes `LAF-61` genuinely visible for the first time.

**Test:** place a real leftover directory where runs are actually created; the claim must report
`false` and name the full path. Also place one where the probe *used* to look and assert it is **not**
reported, so the fix cannot pass by widening the search to both.

### `RR-10E` — the record names the command that exists

**File:** `agent_artifacts/setup.py` (`rollback_command`)

The field says *no command reverses a completed setup*. It now names
`aart marketplace receipt undo <coordinate> --profile … --scope …`.

**Test:** the string is parsed with the real CLI parser and the test fails if it does not parse. The
remediation guard already does this for user-visible `aart …` mentions in diagnostics; this extends
the same guard to a field the program *writes into a file*. Without that, the sentence goes stale
again the next time the command surface moves — which is exactly how it went stale the first time.

### `RR-10F` — `verify` reports a record that carries credential-shaped text

**File:** `agent_artifacts/setup_verify.py`

One new claim: *does this record contain anything that looks like a credential?* Applied to the
record as stored, using the same rule 4 shapes.

It **reports and never repairs**, like every other claim. Records written by `2.5.0` and `2.6.0` keep
whatever is in them; rewriting a persisted record would destroy the evidence receipts exist to be.
The operator decides whether to delete it.

This is what makes the fix reach records that already exist, without the fix editing them.

### `RR-10G` — documents and register

- `residue-register.md`: `LAF-63`, `LAF-72`, `LAF-66`, `LAF-65` → `closed`, each naming its
  reproduction. `LAF-61` → `visible`, because `RR-10D` is what finally makes it so.
- `compatibility-v14.md` and `release-checklist-v14.md`: the four closures, and the limit rule 4 does
  not cover.
- `triage-brief-2.6.0.md`: the verdict changes from *hold* to *ship*, or the brief is wrong.

---

## Order

`RR-10A` first, because everything else depends on one redactor existing. Then `RR-10B` and `RR-10C`
together — the boundary change and the test that proves it. `RR-10D`, `RR-10E`, `RR-10F` are
independent of each other and of the redaction work. `RR-10G` last, when the gates are green.

## What would make this plan wrong

**If rule 4 turns out to redact something receipts need.** Image digests are `sha256:…`, plan hashes
are bare hex, and none of the rule-4 prefixes collides with those — but that is an argument, not a
measurement. `RR-10A`'s test includes a real receipt's every field and asserts none of them changes.
If one does, rule 4 is wrong and the design's §4.4 limit needs widening, not the pattern.

**If the run root is not reachable where the probe runs.** `RR-10D` assumes the caller can hand the
probe the same root the run used. If it cannot, the probe should report `unknown` rather than
guessing — a probe that cannot ask is exactly what the three-status design is for, and `LAF-66`
happened because that mechanism was bypassed by a confident `true`.
