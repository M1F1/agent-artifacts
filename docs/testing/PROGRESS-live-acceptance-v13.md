# Live acceptance v13 — progress

Fourteenth live acceptance run. Subject: `LAF-90`, the wizard defaults that author a registry the
same AART then refuses to read. Methodology unchanged:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs; the
[v1](PROGRESS-live-acceptance.md), [v2](PROGRESS-live-acceptance-v2.md),
[v3](PROGRESS-live-acceptance-v3.md) and [setup-build](PROGRESS-live-acceptance-setup-build.md)
records are the prior runs this one is read against, and none of them is ever rewritten. `v4`–`v12`
are now merged into `main` and are read alongside it.

**Status: agent scope complete for `LAF-90`.** Two scenarios re-executed, two passes, nothing
blocked. The curses screen stays human-gated (design §10); the defect never needed it.

## What this run establishes

The unit test proves the wizard's question loop returns a window that contains the running version.
It cannot show that the value an operator accepts by pressing return survives the trip through
`registry init` into `aart-registry.json` and comes back out of `registry validate` as a pass. That
is what this walks, on both sides.

1. **Both sides are walked.** `venv-before` holds a wheel built from `main`; `venv` holds a wheel
   built from this branch. Each probe prints `agent_artifacts.__file__` so the record shows which
   package answered.
2. **The observation is discriminating.** `main` offers `1.0.0..2.0.0` and its registry fails
   validation; the branch offers `2.6.0..3.0.0` and its registry passes. Nothing else differs — same
   source id, same display name, same commands, same sandbox.
3. **The wizard's own code supplies the values.** The two versions are not typed by the walker: they
   are what `_prompt_curation_request` returns when the reader presses return, taken from the
   installed wheel and handed to the shipped CLI.

## Run header

| Field | Value |
|---|---|
| AART commit under test | `dd90561` (`fix/wizard-defaults-name-the-running-aart-laf90`) |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, 550 604 bytes, **built locally from that commit** — no release carries this fix |
| Wheel sha256 | `7645192c28a9f13d0c7f3e7f2e94a9f6e3c91d428fc34d0d150197000c35ee9a` |
| Comparison executable | `b437061` (`main`, after tonight's merges), built the same way, 550 375 bytes, `bd96944ccaf82bc46e2a90e4d5bb51a7468952db84042c2d505d689c22bde807` |
| `aart --version` | `agent-artifacts 2.6.0` from both — the version is not what distinguishes them |
| Platform | macOS 26.2 (darwin 25.2.0), Python 3.11.0 |
| Sandbox `HOME` | `$LAB/home-main` and `$LAB/home-branch`; the real `~` is neither read nor written for this run |
| Registry | one fresh `git init` checkout per side, `$LAB/reg-main` and `$LAB/reg-branch`; **never pushed** |

## Scenarios

| ID | Result | What was done | What was seen |
|---|---|---|---|
| `LA-0-11` | **pass** | drive the installed wheel's `_prompt_curation_request` for `CurationAction.INIT`, pressing return at both version prompts | `main` returns `1.0.0..2.0.0`; the branch returns `2.6.0..3.0.0` and prints the value in the prompt itself — `Minimum AART version [2.6.0]: ` |
| `LA-0-12` | **pass** | pass exactly those two values to `aart registry init --yes`, then `aart registry validate` on what it wrote | `main`: `init` exits `0` writing `requires_aart {1.0.0, 2.0.0}`, `validate` exits `1`. Branch: `init` exits `0` writing `{2.6.0, 3.0.0}`, `validate` exits **`0`**, *registry validate: passed* |

## One methodology note, because it nearly spoiled the run

The first pass of both probes ran with the repository as the working directory. `python -c` puts the
current directory at the head of `sys.path`, so both venvs imported the **working tree** rather than
the wheel installed in them, and both sides reported the fixed values — a passing result that proved
nothing. Re-run with the working directory outside the repository and with
`agent_artifacts.__file__` printed, the two sides separate. `LAF-66` is the standing case of a probe
that looked nowhere real; this is the same trap in a different disguise, and the record should say
that it was walked into and caught rather than pretend the first numbers were the ones reported.

## Findings

None. No new residue from this walk.
