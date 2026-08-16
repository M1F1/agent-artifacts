# Design: subscription identity binding

Response to the second live acceptance run,
[PROGRESS-live-acceptance-v2.md](../testing/PROGRESS-live-acceptance-v2.md), executed against
released `2.1.0`. Composed from the whole residue set, not from any one finding: four changes answer
eleven residues, and each change is placed where the residues converge rather than where they were
observed.

## 1. What the run actually found

`2.1.0` gave the subscription a full lifecycle. The run confirms that half of it: a subscription can
be ended and re-identified, the ordering invariant survives interruption, both front-ends reach both
actions, and three of v1's four consumer defects are genuinely gone.

It also shows that the lifecycle stops at the subscription. Everything installed *from* a
subscription is bound to a copy of its identity that nothing maintains, and the moment the two
disagree the product reports a state that is both wrong and terminal.

Four attractors organise the residues; §2–§5 answer one each.

| Attractor | Residues | Answered by |
|---|---|---|
| A1 — a missing subscription is reported as a missing artifact | `LAF-31`, v1 `LAF-19`, `LA2-X-02` | §3 |
| A2 — identity is pinned in four places, two of them unmaintained | `LAF-33`, `LAF-37` | §2 |
| A3 — remediation exists in the envelope, not on the operator's path | `LAF-32`, `LAF-29`, `LAF-40`, `LAF-36` | §4 |
| A4 — review-first binds a process, not a decision | `LAF-34`, `LAF-35`, v1 `LAF-16` | §5 |

## 2. Reconciliation owns the identity change, not `resubscribe`

### The residue

`marketplace status` reports `source-unavailable` for every artifact installed before an adopted
identity change, forever. `marketplace update` reports `selected canonical installations were not
found`. The installation record pins `source.declared_id`; `resubscribe` rebinds the configuration
and the snapshot store and cannot touch the record. The resubscription review says the opposite will
happen.

### Why the obvious fix is wrong

The tempting fix is for `resubscribe` to rewrite installation records. It cannot, and it must not:
`DESIGN-source-subscription-lifecycle.md` §3 makes project isolation a hard invariant, proved by
`tests/source_project_isolation_test.py` — no source operation writes beneath a project. AART also
does not know which projects exist. A source-side command that reaches into projects would trade a
visible residue for an invisible one.

### The change

**`declared_id` in an installation record becomes evidence of what was installed, not the key used to
find its source.** Reconciliation resolves through the subscription — alias, origin, ref — and then
compares:

| Record vs subscription | Reported status | What it means |
|---|---|---|
| alias not configured | `source-unavailable` | the subscription is gone (§3 governs the message) |
| alias configured, `declared_id` equal | existing statuses | unchanged behaviour |
| alias configured, `declared_id` differs | **`identity-changed`** (new) | the origin was adopted under a new identity |

`identity-changed` is a first-class reconciliation status beside `update-available` and
`removed-upstream`, and it is actionable in exactly one place: `marketplace update` in that project,
under the normal review, which states both identities and rebinds the record on finalize. One
project, one review, one operator — the same shape as every other reconciliation.

This is what makes the resubscription review's promise true: installed artifacts do surface through
normal reconciliation, in the project that owns them, at the time that project is reconciled.

### The second half of A2

`LAF-37`: a registry whose `aart-registry.json` and `aart-source.json` declare different identities
is refused by `registry validate --strict --frozen` and accepted by every consumer path. The value
the whole model pins is the one no consumer-side gate checks.

**Snapshot compilation validates the identity agreement whenever both documents are present.** A
registry snapshot whose `registry_id` and `source_id` disagree is refused at acquisition with a typed
diagnostic naming both values and the file each came from. This is the one-way adaptation rule
applied consistently: the consumer does not soften a rule the publisher's own tooling enforces.

**A root `aart-registry.json` that is present must be readable.** The rule above says *whenever both
documents are present*, and `2.2.0` implemented it as *whenever both documents parse* — so a broken
registry marker left a third state nobody chose: the comparison was skipped and the subscription
admitted in silence. The plan recorded that as `RS-08` and said it deserved its own decision, because
the fix is a new refusal rather than a tightening of this one. The decision is taken here: a snapshot
carrying a root entry named `aart-registry.json` must have it as a regular file that parses as a
registry manifest, or the subscription is refused, naming the file and what the parser could not
read. Absence is untouched — a source publishing only `aart-source.json` is an ordinary native source
and stays one. What is refused is a snapshot that takes the marker's reserved name and then does not
honour it, since the identity the whole model pins is exactly what cannot be read there. On the
registry path the workspace validation already refused first; this makes the direct and local paths
say the same thing.

## 3. One vocabulary for resolution failure

### The residue

Three unrelated stressors — subscription removed, subscription removed mid-operation, cold cache with
nothing to resolve from — all produce `artifact-not-found: artifact <name> in source <alias> was not
found`, with empty remediation. The artifact name is the only part of the request that was never
wrong. And `marketplace uninstall` fails this way for an artifact it has a complete record of.

### The change

Two rules.

**Uninstall does not resolve through the source.** Removing an installation needs the manifest — the
recorded effects, digests, and destinations — and nothing else. Resolution is removed from the
uninstall path entirely, which makes `source remove`'s review honest: uninstalling really is a valid
exit after the subscription is gone.

Two consequences fall out of that sentence, and both are load-bearing. First, uninstall stops being
a *content operation*: the `no-source-configured` precondition, which fires before resolution and
demands at least one enabled subscription, does not apply to removing what a project already holds.
It is the only refusal this release loosens, and only here. Second, collections are the exception
that proves the rule — a collection is a grouping the registry publishes and the manifest never
records, so expanding one still needs a catalog. Naming the members remains the route that works
after the subscription is gone.

**Resolution failure names the layer that failed**, and each layer carries its own remediation:

| Cause | Diagnostic | Remediation names |
|---|---|---|
| alias not configured | `source-unavailable` | `aart source add --alias <a> …`, or `aart marketplace uninstall` |
| alias configured, no snapshot | `source-not-synchronized` | `aart source sync --alias <a>` |
| snapshot present, artifact absent | `artifact-not-found` | `aart marketplace list --source <a>` |
| offline, nothing cached | `source-not-synchronized` | drop `--offline`, or sync while connected |

`artifact-not-found` survives only for the case where it is true.

## 4. Remediation is a rendered property, not a stored one

### The residue

`SL-5` proved every remediation string names a command the parser accepts. The run found the
remaining half of the problem: `aart source sync` prints the message and drops the remediation in
text mode, so the `aart source resubscribe` line that `2.1.0` exists to deliver is `--json`-only;
`tui_sources.py` still tells an operator to run `source doctor`, removed in `2.0.0` and recorded in
no release document; and two failures carry empty remediation with a raw errno or a wrong cause.

### The change

**Every renderer renders remediation.** The per-source text renderer prints remediation lines under
their diagnostic, exactly as the single-operation renderer already does. A test asserts *renderer
parity*: for a representative refusal on every command family, the set of remediation lines in text
output equals the set in the JSON envelope. Parser parity proves the command exists; renderer parity
proves the operator sees it.

**The dead-end guard extends past `Diagnostic`.** `tests/source_remediation_test.py` scans
`Diagnostic.remediation`. It is widened to scan every user-visible `aart …` mention in the package —
display reasons, TUI hints, help epilogues — and to parse each one. `source doctor` is the proof that
the narrow version was not enough.

**Two message fixes follow from the same rule.** The stale-lock refusal reports the holder's age and
whether its pid is alive, and names how long the stale window is; the object-store failure carries a
remediation line instead of a bare errno.

**And the removal is recorded.** `source doctor` is added to a compatibility addendum for the `2.0.0`
series, because a user migrating from `1.x` reads that table and it is currently incomplete.

## 5. A review a human can carry to a finalize

### The residue

`plan_digest` — and the `review_digest` derived from it — includes `source_age_seconds`, so the
consent digest changes every second on an unchanged workspace. Independently, `source resubscribe`
re-validates its transition only inside the process that computed it, so a human who reviews in one
command and finalizes in another adopts whatever the origin declares at the second call, under a
review sentence that says "this exact identity change".

These are one defect. The product's mutation contract is *review, then finalize*, and the artefact
that is supposed to bind the two cannot cross the gap between two commands.

### The change

**The plan digest describes the plan, not the moment.** `source_age_seconds` leaves
`_plan_review_value`. Freshness stays in the review *output*, where an operator wants it, and out of
the identity of the plan. The digest then depends only on inputs that are stable while the world is:
coordinates, source identity and revision, snapshot digest, artifact and object digests,
destinations, modes, policy.

**A reviewed decision can be carried.** Every review-first command accepts `--expect <digest>`:

```sh
aart marketplace install la-a/skill/x --json      # review; read review_digest
aart marketplace install la-a/skill/x --yes --expect sha256:…   # finalize that exact plan
```

If the recomputed plan does not match, the command refuses and shows the new review. `source
resubscribe --expect <from>:<to>` is the same contract for the transition, which makes
`SourceIdentityTransition` — already carrying both sides for precisely this reason — checkable across
invocations rather than only within one.

`--yes` without `--expect` keeps today's meaning: finalize what this process just computed. Nothing
becomes mandatory; what changes is that the two-command workflow the review text prescribes can now
be safe.

## 6. What this design does not do

- It does not weaken any refusal. Every gate the run exercised stays; three of them get a second gate
  on the consumer side.
- It does not let a source operation write into a project. §2 puts the rebinding in the project's own
  reconciliation for exactly that reason.
- It does not touch the protocol, the schemas, the store layouts, or any on-disk format. `LAS-31`
  showed `2.0.0` ↔ `2.1.0` interoperate; this work keeps that true. `identity-changed` is a computed
  status, not a stored one.
- It does not fold `LAF-30`, `LAF-38`, and `LAF-39` into the four attractors. They are separate
  decisions, taken in §7, and they land as their own work packages — one of them in the next major.
- It does not address `LAF-17` (teardown litter) structurally — that one is small and independent,
  and the plan carries it as a standalone package rather than pretending it belongs to an attractor.

## 7. Three decisions, taken

The run left three `question` findings — behaviour that is defensible but undocumented, needing a
decision rather than a fix. All three were decided by the maintainer on 2026-08-14, and the reasoning
is recorded here so it outlives the conversation.

### 7.1 `LAF-30` — the published wheel becomes byte-reproducible

**Decision: do it.** `scripts/build_wheel.py` derives zip entry timestamps from the tagged commit's
date rather than from build time, so rebuilding at the tag reproduces the published archive digest
exactly, not merely its contents.

The reason is what AART is: a tool that installs other people's files into other people's projects.
"You can verify the published artefact yourself" is worth more here than freedom in the build. The
cost is that it becomes a standing promise — every later packaging change has to keep it — which is
accepted deliberately and held by a test rather than by intent.

### 7.2 `LAF-38` — dependencies stay inside one registry, and it is written down

**Decision: document the restriction as deliberate; do not extend `requires`.**

A cross-registry dependency is an artifact that breaks when a *different* maintainer changes
something in a registry its author does not control. That is a coupling AART should not make easy to
express. The workaround Registry B already used — vendor the dependency into the same registry — is
the honest form of the same intent: it puts the dependency, and its provenance, under one
maintainer's control.

What was actually wrong is that nothing said so. The rule becomes explicit in three places: the
registry protocol document, `registry` help, and the build refusal itself, which today reports
`skill/x requires missing skill/y` as though the artifact were merely absent rather than out of
scope. Federation at consumption and locality at publication are both intended, and they are now
stated together instead of being discovered one build failure at a time.

### 7.3 `LAF-39` — `source add` gains a review, in the next major

**Decision: add the review. It cannot ship in a minor.**

The value is not safety — `add` does nothing destructive. It is that "without `--yes` nothing
happens" becomes a rule with no exceptions, and a rule with no exceptions is the one operators
actually learn. Today the single verb that breaks it is the first one a new operator runs.

But `aart source add --alias … --kind … --location …` currently *adds*. Making it review instead is a
silent behaviour change for every script, tutorial, and registry CI workflow that already calls it:
they would keep exiting `0` and quietly stop configuring anything. That is precisely the "the report
states the opposite of the effect" shape this project keeps filing as a defect (v1 `LAF-11`), and no
amount of release-note prose makes it safe.

It is therefore a breaking change to a public command's contract — a **major** under the criterion
`compatibility-v8.md` applied to the nine removed verbs — and it is planned as `SI-10`, gated on
`3.0.0`. There is deliberately **no deprecation window**: `2.0.0` removed nine commands outright
rather than warning first, and a release in which `add` warns but still mutates would leave the rule
broken for longer while teaching nobody.

The part that can ship now is the documentation of the asymmetry at the family level, so that until
`3.0.0` an operator reading `aart source --help` is told which verb reviews and which does not.

## 8. Acceptance criteria

1. An artifact installed before an adopted identity change reports `identity-changed`, not
   `source-unavailable`, and `marketplace update` rebinds it under review in its own project.
2. `marketplace uninstall` removes an installation whose subscription no longer exists, without
   resolving through any source.
3. A resolution failure names the layer that failed, and every one of the four cases carries
   remediation that the parser accepts.
4. A registry snapshot whose `registry_id` and `source_id` disagree is refused at acquisition, naming
   both values and both files.
5. Text output and JSON output carry the same remediation lines for the same refusal, asserted by
   test for every command family.
6. Every `aart …` mention anywhere in the package parses, including display reasons and TUI hints.
7. Two review-only runs of the same command on an unchanged workspace, minutes apart, produce the
   same `review_digest`.
8. `--expect <digest>` finalizes the reviewed plan and refuses a changed one, for every review-first
   command; `source resubscribe --expect <from>:<to>` refuses an origin that moved after review.
9. No source operation writes beneath a project directory — the existing isolation proof still
   passes, unmodified.
10. Rebuilding the wheel at the release tag reproduces the published archive digest, not only its
    member contents.
11. The intra-registry scope of `requires` is stated in the protocol document and in `registry` help,
    and the build refusal says the dependency is out of scope rather than merely missing.
12. `aart source --help` states which verbs review and which mutate immediately. (`source add`'s own
    review is `SI-10`, and lands with `3.0.0`.)
