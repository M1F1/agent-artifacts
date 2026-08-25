# What is broken, and should 2.6.0 be released?

Written on `2026-08-15`. The full list of open problems lives in
[`residue-register.md`](residue-register.md). That file says **what is open**. This file says **what
it costs you, and what to do first**. If the two disagree, the register is correct and this file is
out of date.

---

## The short answer

**The 3 blockers are fixed. 2.6.0 is ready to release.**

> This section was written on `2026-08-15` saying *do not release yet, fix 3 things first*. That was
> the right call, and the 3 things are now done. The original reasoning is kept below rather than
> deleted, because a brief edited until it agrees with the code stops being a record of the decision
> it was written for.

The release was already healthy — 1549 tests pass, all 9 quality gates are green, and no data format
changed. What was wrong was that 2.6.0 adds three commands for reading setup receipts, and all 3 bugs
below were in exactly those commands. The release would have shipped with its own main feature broken
in visible ways.

| # | Bug | How bad | State |
|---|---|---|---|
| 1 | `LAF-63` | **high** | **fixed.** And measuring it found a bigger one, `LAF-72` — see below. |
| 2 | `LAF-66` | **high** | **fixed.** `receipt verify` now looks where runs really are. |
| 3 | `LAF-65` | medium | **fixed.** The receipt names the undo command that exists. |

**The one thing worth knowing.** Fixing bug 1 turned up something worse than the bug. There were
**two** functions hiding passwords, with different rules — and the weaker one was the one used when
writing to disk. So a password could be correctly hidden on screen and written out in full to a file,
in the same run. That is `LAF-72`, it is also fixed, and it is the reason this took a second pass
rather than a one-line patch.

Two more things you should know. Neither is a reason to wait:

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

## The 3 problems that had to be fixed before release

All three are now fixed. Each one below keeps the diagnosis as it was written, and ends with **what
actually happened** when it was fixed — which in one case was not what the diagnosis predicted.

### 1. `LAF-63` — a token can be saved to disk in plain text

**Severity: high. Priority: P1. Now: fixed.**

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

**What actually happened.** The "cost: small" estimate was wrong, and usefully so.

Before changing the pattern I measured it, and the measurement showed **two** functions doing this
job, not one. They had different rules, neither covered everything the other did, and the weaker of
the two was the one on the path that writes the file. So the version of the check protecting your
screen was stronger than the version protecting your disk. That is `LAF-72`, and it is the defect
that mattered.

Both are now one function. It hides: a credential name with any prefix, a password inside a web
address (a `user:secret` userinfo), a password in a URL query string, and a value that simply
*looks* like a credential with no name beside it at all — which is the case none of the others can
reach, and the case a `git clone` failure actually prints. It recognises credentials by shape and
never by randomness, so the long checksums a receipt exists to record are left alone.

Two things did **not** change, because nothing was wrong with them, and it is worth stating plainly
since the whole question was "can a token leak":

- **The tool never receives your token.** It runs macOS's own `security` command with the value flag
  left empty, so `security` asks you at the terminal, with no echo, and reads it directly. The token
  goes from your keyboard into the Keychain. It never passes through this program.
- **What gets written into your shell profile is the question, not the answer** — a lookup that asks
  the Keychain for the value each time, not the value itself.

**On the extra decision above:** old files keep the secret, and nothing rewrites them, on purpose — a
receipt is evidence of what a run did. What `receipt verify` now does is *tell you*: it reports that
a record contains credential-shaped text, without printing the value, and says that deleting the
record and re-running setup is the only thing that removes it. Your call, stated clearly, rather than
a silent rewrite.

---

### 2. `LAF-66` — `verify` reports "fine" about a folder it never looks at

**Severity: high. Priority: P1. Now: fixed.**

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

**What actually happened.** Fixed as described, and the bonus landed: `LAF-61` is now visible — the
leftover folder is named and left exactly where it is, never deleted for you.

One extra thing was needed. If the check has no folder to look in, it now says **"I don't know"**
instead of "fine". That was the real shape of this bug: not a missing check, but a check that
answered confidently about a place it had never looked. And the test that proves the fix drives the
*real* function that creates these folders together with the *real* function that finds them, then
checks that the old wrong location finds nothing — so the fix cannot pass by simply searching
everywhere.

---

### 3. `LAF-65` — the receipt contradicts the program that printed it

**Severity: medium. Priority: P1. Now: fixed.**

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

**What actually happened.** The text changed, and one more thing was added, because the interesting
question was *why nobody noticed*. The tool already checks that every `aart …` command it prints is a
command that really exists — it hands them to its own command parser. It never checked these two,
because they are not printed messages: they are fields written into a file that nothing ever read
back. Now they go through the same parser. A future release that renames `receipt undo` will fail its
own tests instead of quietly writing wrong advice into every receipt.

---

## Everything else, grouped by what is broken

Each section is named after the thing a user would say is broken.

### Passwords and tokens

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-63` | high | ~~P1~~ **fixed** | Explained above. |
| `LAF-72` | high | ~~P1~~ **fixed** | Two functions hid passwords, with different rules, and the weaker one was the one writing to disk. Found while measuring `LAF-63`. |
| `RS-12` | medium | P2 | Setup steps run without `HOME`. Docker then cannot read its login file, so a private base image cannot be downloaded at all. |

### Setup receipts — the 2.6.0 feature

| ID | Sev | Pri | What goes wrong |
|---|---|---|---|
| `LAF-66` | high | ~~P1~~ **fixed** | Explained above. |
| `LAF-65` | medium | ~~P1~~ **fixed** | Explained above. |
| `LAF-61` | medium | P2 | A killed run leaves its working folder behind and nothing removes it. `verify` now tells you it is there and where; removing it is still your job. |
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

**What happened afterwards.** All four moved, and past `2.5.0` rather than to it: your machine runs
`2.6.0` from the published release asset, and Registry B, the acceptance project and Registry A's own
three workflows all pin `v2.6.0` and are merged. `LAF-70`, `LAF-71` and `LAF-68` are closed in the
register. The rows above are left as they were written, because a brief is a snapshot of what was
true when a decision was being made, and a brief edited until it agrees with the outcome cannot be
used to judge the decision.

Two upgrades were written and neither was merged. The one machine that authors content for all of
them is the oldest thing in the table. **Nothing here has ever run 2.6.0.**

**A mistake worth recording.** I first reported these pins backwards. I read them from local folders
on my disk instead of from GitHub. One folder was 7 commits out of date, the other was sitting on the
exact unmerged branch I was describing. The table above is the corrected version, read from
`origin/main`. This is why the skill I wrote makes "read the remote, not your local folder" a rule.

---

## What is left before 2.6.0 goes out

The code is done. What remains is not code:

1. **Re-run acceptance scenarios 3 and 6** from
   [`PROGRESS-live-acceptance-receipt.md`](PROGRESS-live-acceptance-receipt.md) — those are the two
   the fixes change. This needs a real machine, a real Docker daemon and a real Keychain, and you
   type the password yourself; I never type one.
2. **Decide the release itself.** Nothing is tagged, pushed or published, and nothing will be without
   you saying so.
3. **Say the honest thing in the release notes:** 2 of the 7 acceptance scenarios could not be run
   against published content (`LAF-67`). Do not round that up.

Then the version table above is the next job: three of the four rows have never run 2.6.0, and two
upgrades are sitting in unmerged pull requests.

## If you only have time for one thing (as written before the fixes)

> **Fix `LAF-63`.** It is the only problem here where the failure is *a password on disk and on
> screen*. The fix is one pattern and its tests.

Kept because it turned out to be the right instinct for a reason it did not state. `LAF-63` was worth
starting with not because it was the worst bug, but because *measuring* it was what exposed
`LAF-72` — the one that actually mattered. The lesson is not "pick the security bug first". It is
**measure the bug before you fix it**: the estimate said one pattern, and the measurement said two
functions with the weaker one on the disk path.
