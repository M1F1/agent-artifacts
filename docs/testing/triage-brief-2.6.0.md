# What is broken, and should 2.6.0 be released?

Written on `2026-08-15`. The full list of open problems lives in
[`residue-register.md`](residue-register.md). That file says **what is open**. This file says **what
it costs you, and what to do first**. If the two disagree, the register is correct and this file is
out of date.

---

## The short answer

**Do not release 2.6.0 yet. Fix 3 things first. All 3 are small.**

The release itself is healthy: 1528 tests pass, all 9 quality gates are green, and we proved by
machine that no data format changed.

The problem is different. 2.6.0 adds three commands for reading setup receipts. All 3 bugs below are
in exactly those commands. So the release would ship with its own main feature broken in visible ways.

| # | Bug | How bad | Why it matters right now |
|---|---|---|---|
| 1 | `LAF-63` | **high** | A password or token can be written to disk in plain text. 2.6.0 adds the command that prints that file on screen. |
| 2 | `LAF-66` | **high** | `receipt verify` says "everything is fine" about a folder it never actually checks. |
| 3 | `LAF-65` | medium | The receipt text tells the user "no command can undo a setup". 2.6.0 *is* the release that adds that command. |

None of these 3 bugs is new. They only became important now, because 2.6.0 is the release that lets
users see them.

Two more things you should know before deciding. Neither is a reason to wait:

- **2 of the 7 planned acceptance tests were never run** on real published content (`LAF-67`). They
  were only tested with a local test fixture.
- **No registry and no real project has ever run this version.** Details in the version table at the
  bottom.

---

## How to read the two ratings

Every problem below has two ratings. They mean different things.

### Severity = how bad is it, if it happens?

| Rating | Meaning |
|---|---|
| **high** | A password leaks, data is lost, or a command says "OK" / "true" when the truth is the opposite. |
| **medium** | The tool promises something in its own text, but does not do it. A person can fix it by hand. |
| **low** | Annoying, or dead code, or a limit that nobody wrote down. Nothing is actually wrong. |

### Priority = when should you spend time on it?

| Rating | Meaning |
|---|---|
| **P1** | Fix before the next release. |
| **P2** | Fix soon, in the next round of work. |
| **P3** | Fix later, when you are already editing that part of the code anyway. |

**You will see one "high + P3" combination below.** That is not a mistake. It means: *if this happens
it is bad, but it is very hard to reach, and almost nobody will hit it.* It is explained where it
appears.

---

## The 3 problems to fix before release

### 1. `LAF-63` — a token can be saved to disk in plain text

**Severity: high. Priority: P1.**

**What goes wrong.** The tool tries to hide passwords and tokens before writing logs. It looks for
words like `token`, `password`, `secret`, `api_key`. But it only finds them when the word stands
alone. If the name has a prefix, it does not match.

Here is the real test I ran:

```
hidden   TOKEN=ghp_aaa              ->  TOKEN=[redacted]
LEAKED   GITHUB_TOKEN=ghp_bbb       ->  GITHUB_TOKEN=ghp_bbb
LEAKED   AWS_SECRET_ACCESS_KEY=s2   ->  AWS_SECRET_ACCESS_KEY=s2
LEAKED   MY_API_KEY=k2              ->  MY_API_KEY=k2
```

The names with a prefix are the names real projects actually use.

**Why it matters.** This text is saved into a file on disk, not only shown on screen. And 2.6.0 adds
`receipt show`, which reads that file and prints it. So this release adds a second way to expose the
same secret.

**Good news.** Not everything is affected. When the token sits in a named field, it *is* hidden
correctly. The leak only happens in free text: error messages, build logs, step details.

**Cost to fix: small.** It is one pattern plus its tests. The test already exists
(`tests/setup_render_test.py::test_laf63_...`) and today it checks that the bug is still there. So
the fix is: change the pattern, flip the test.

**One extra decision.** Fixing the pattern does not clean files that were already written. Old files
keep the secret. You need to decide separately: add a cleanup command, or just warn people in the
release notes.

---

### 2. `LAF-66` — `verify` reports "fine" about a folder it never looks at

**Severity: high. Priority: P1.**

**What goes wrong.** When a setup run is killed, it can leave a leftover working folder. `receipt
verify` is supposed to notice this and tell you. It looks in the project folder. But real runs create
that folder somewhere else — in the data folder. The two are never the same place.

I tested it with a real leftover folder:

| Where I put the leftover folder | What `verify` said |
|---|---|
| Where the check looks | "found it", correct |
| Where runs really are | **"true: no working copy was left behind"** — wrong |

**Why it matters.** The whole point of `verify` is to answer "is this still true?". The design
document even says that a checker which quietly passes things it cannot see is worse than no checker
at all. This is that exact case. It does not say "I don't know". It says "everything is fine".

**Cost to fix: small.** Point the check at the correct folder.

**Bonus.** Another open problem (`LAF-61`, the leftover folder itself) becomes visible to users the
moment this is fixed.

---

### 3. `LAF-65` — the receipt contradicts the program that printed it

**Severity: medium. Priority: P1.**

**What goes wrong.** Every receipt contains a line of help text:

```
rollback  no command reverses a completed setup; undo ... by hand,
          then re-run setup
```

That sentence was true before. It is false now, because 2.6.0 adds `receipt undo`.

**Why it matters.** This is not an old document we forgot. It is a field this release *writes*. Every
new receipt from now on will carry a sentence that the same program contradicts. A user who reads the
receipt instead of the release notes will do manual work that one command already does.

**Cost to fix: small.** Change the text.

---

## Everything else, grouped by what is broken

Each section is named after the thing a user would say is broken.

### Passwords and tokens

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-63` | high | **P1** | Explained above. |
| `RS-12` | medium | P2 | Setup steps run without `HOME`. Docker then cannot read its login file, so a private base image cannot be downloaded at all. |

### Setup receipts — the 2.6.0 feature

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-66` | high | **P1** | Explained above. |
| `LAF-65` | medium | **P1** | Explained above. |
| `LAF-61` | medium | P2 | A killed run leaves its working folder behind and nothing removes it. We thought `verify` reported it; `LAF-66` proved it does not. |
| `LAF-58` | medium | P2 | If a Docker image tag already existed before a setup run, undo cannot restore what it pointed to before. Nobody wrote down the old value. The undo screen does warn you about this before you confirm. |
| `LAF-67` | medium | P2 | No published artifact uses the Docker *build* step. So 2 of the 7 planned acceptance tests cannot be run against real content at all. |

**About `LAF-67`.** This is not a bug in the code. It is a gap in testing. The acceptance tests were
written by looking at the code, not by looking at what the registries actually publish. Worth knowing
before you decide what "tested" means for this release.

### Uninstall

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-47` | medium | P2 | Uninstall leaves the `.mcp.json` file behind, empty: `{"mcpServers": {}}`. |
| `RS-10` | medium | P2 | Same thing for any merged file: the last uninstall leaves the file. |
| `LAF-57` | low | P3 | The two install methods produce the same content but report different image identity. |

The first two are really one bug. The design document claimed `verify` would make them visible. It
does not, and we checked: `verify` reads *setup* records, but these are *install* effects, and the
only thing it checks is that the file exists — which is true for an empty file too.

### Getting artifacts from other repositories

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-62` | medium | P2 | A user on AART 2.4.0 or older cannot add a registry that was rebuilt with 2.5.0. It fails immediately. |
| `RS-03` | medium | P3 | A repository containing *any* symlink cannot be imported at all. This is stricter than the rule the design describes. |
| `LAF-43` | medium | P3 | Import refuses `file://` sources, so some behaviour cannot be tested locally. |
| `RS-01` | medium | P2 | A locally-owned `mcp` package with a badly shaped descriptor is never checked. |
| `RS-08` | medium | P2 | If `aart-registry.json` is broken, the identity check is skipped completely instead of failing. |
| `RS-04` | low | P3 | `vendor` only creates. When it refuses, it cannot mention `revendor`, which is the command that would work. |

**These matter for what you asked me to do next.** If the acceptance repo becomes a source that
registries copy from, then `RS-03` decides whether it may contain any symlink, and `LAF-62` decides
who can still read the registries afterwards.

### Error messages

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `RS-09` | medium | P2 | No `registry` error message tells you how to fix the problem. The field is empty everywhere. |
| `RS-07` | medium | P2 | If your only source is removed, `marketplace status` says "no source configured" instead of "source unavailable". Different problem, wrong message. |
| `LAF-45` | medium | P2 | `audit --check-upstream` prints nothing when everything is up to date. You cannot tell success from a forgotten flag. |
| `LAF-49` | low | P3 | Git runs without `https_proxy`, and this is not documented. Behind a company proxy it fails with no hint why. |

### What a setup recipe can express

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `RS-11` | low | P3 | A recipe can only ask for a secret. It cannot ask for a username. |
| `RS-13` | low | P3 | There is no ready-made module for editing `.zshrc`. |
| `RS-14` | low | P3 | The recipe format has no way to write a comment. |
| `RS-15` | low | P3 | A package cannot include a helper script at its top level. |

All four are the same decision, postponed: the recipe format is closed, and adding anything needs a
format change. Do them together as one piece of work, or not at all.

### The full-screen menu

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-64` | medium | P2 | One helper function returns two different types depending on an argument. A new caller writing the obvious code compiles fine, passes the type checker, and silently treats every successful choice as "cancel". |

This one costs more than its severity suggests. It was found by writing the *second* caller of a
function that had only ever had one. It cost a debugging session and only a test caught it. The next
person to add a caller pays the same cost again.

### Release process and version pins

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-69` | high | P2 | Our documentation check only catches one kind of mistake, and it is the harmless one. Explained below. |
| `LAF-70` | medium | P2 | The computer that authors registry content runs AART 2.0.0, while Registry A's CI checks that content with 2.5.0. The author's tool is older than the check that judges it. |
| `LAF-71` | medium | P2 | Every version upgrade is prepared and none is merged. Registry B PR #5 and acceptance-repo PR #1 are both still open. |
| `LAF-68` | medium | P2 | The acceptance project still pins 2.0.0, so its CI has never run 2.5.0. This is one example of `LAF-71`. |
| `RS-02` | low | P3 | Dead version numbers are stamped on registry requests. |

**About `LAF-69` — why high but only P2.** The documentation check makes sure our documents agree
with the register. But it only checks one direction. It complains when a document says a problem is
*still open* after we fixed it — harmless. It says nothing when a document says a problem is *fixed*
when it is actually open — which is the dangerous direction, because it is a false promise of safety.

This actually happened during this work. The register moved `LAF-61` back to "open", two release
documents still said it was handled, and the check stayed green. I fixed those documents by hand.

It is P2 and not P1 because it happened once, a human caught it in minutes, and the proper fix needs
thought: making the check symmetric means teaching it to read claims out of English prose, which is
the exact thing the register was created to avoid. Fix it carefully, not quickly.

### Dead weight

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `RS-05` | low | P3 | `io/cache.py` is not used by any shipping code. |
| `RS-06` | low | P3 | An old design document is not marked as replaced. |

---

## Version pins — who is running what

This is the table behind `LAF-70`, `LAF-71` and `LAF-68`.

| Repository | Version on `main` | Upgrade to 2.5.0 |
|---|---|---|
| Your machine (`pipx` install) | `2.0.0` | never started |
| Registry A | `v2.5.0` | done and merged |
| Registry B | `v2.0.0` | open **PR #5** |
| Acceptance project | `2.0.0` | open **PR #1** |

Two upgrades were written and neither was merged. The one machine that authors content for all of
them is the oldest thing in the table. **Nothing here has ever run 2.6.0.**

**A mistake worth recording.** I first reported these pins backwards. I read them from local folders
on my disk instead of from GitHub. One folder was 7 commits out of date, the other was sitting on the
exact unmerged branch I was describing. The table above is the corrected version, read from
`origin/main`. This is why the skill I wrote makes "read the remote, not your local folder" a rule.

---

## If you only have time for one thing

**Fix `LAF-63`.**

It is the only problem here where the failure is *a password on disk and on screen*. The fix is one
pattern and its tests. The test that proves it is already written and today it checks that the bug
still exists.

## If you want 2.6.0 released this week

Fix `LAF-63`, `LAF-66`, `LAF-65`. One round of work, all three small, all three in the feature this
release is about.

Then re-run acceptance scenarios 3 and 6 from
[`PROGRESS-live-acceptance-receipt.md`](PROGRESS-live-acceptance-receipt.md), because those are the
two the fixes change.

Then release — and write in the release notes that 2 of the 7 acceptance tests could not be run
against published content. Do not round that up.
