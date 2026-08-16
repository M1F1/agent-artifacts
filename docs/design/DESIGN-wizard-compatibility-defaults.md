# Design: the wizard offers a window the running AART is inside

The curses wizard suggests the compatibility bounds for a new registry. Pressing return at both
prompts must produce a registry the same executable can then read.

Response to `LAF-90`, recorded in
[`residue-register.md`](../testing/residue-register.md) while `RS-02` was being implemented.

## 1. What happens today

`registry init` asks two questions. The wizard supplies the answers an operator gets by pressing
return:

| Prompt | Default it offers |
|---|---|
| `Minimum AART version [1.0.0]: ` | `1.0.0` |
| `Maximum AART version (exclusive) [2.0.0]: ` | `2.0.0` |

The command accepts them, exits `0`, writes `requires_aart {min_inclusive: 1.0.0, max_exclusive:
2.0.0}` into `aart-registry.json`, and ends by advising four next commands. The first of them,
`aart registry validate`, exits `1`:

> registry workspace is incompatible with this AART version

The window stops one whole major short of the executable that wrote it. Nothing about the operator's
input was wrong; the suggestion was.

## 2. The rule already exists, one package away

`RS-02` removed the same two literals from every registry *request* and replaced them with a rule
derived from the running executable — `curation/model.py`:

```python
DEFAULT_MINIMUM_AART = str(EXECUTABLE_VERSION)
DEFAULT_MAXIMUM_AART = f"{EXECUTABLE_VERSION.major + 1}.0.0"
```

Above them sits a comment that describes this defect in advance: literals go stale on every release
and, once the floor reaches the old ceiling, make the pair unsatisfiable. The flag front-end has the
rule. The wizard is the one place that did not get it.

## 3. The decision

**One source of truth, used by both front-ends.** `DEFAULT_MINIMUM_AART` and
`DEFAULT_MAXIMUM_AART` are already the package's stated default window — `cli.py` uses them for the
flag defaults and `commands/registry.py` for the fallback. The wizard asks its questions with the
same two.

- The prompt shows the value it will use, so `Minimum AART version [2.6.0]: ` on a `2.6.0`
  executable. An operator sees what pressing return means before pressing it.
- The fallbacks in the same branch use the same constants. There are four literal sites today —
  two prompts, two fallbacks — and after this there are none.
- Nothing else changes. An operator who types a wider window still gets the window they typed;
  `test_rs02_init_still_carries_the_window_the_operator_asked_for` already holds that line and keeps
  holding it.

### What was rejected

- **Hard-coding `2.6.0`/`3.0.0`.** It is the same defect one release later, and the comment in
  `curation/model.py` was written because this project has already paid for it once.
- **Validating the pair at `init` and refusing a bad one.** That turns a suggestion the product
  makes into an error the operator has to solve. The suggestion should simply be right; an operator
  who deliberately declares a narrow window is a different case and stays allowed.
- **Deriving the bounds inside `tui.py`.** A second derivation is a second thing to keep in step. It
  is how the two front-ends drifted apart in the first place.

## 4. What proves it

A test that fails before the change and passes after, at the wizard's own boundary: drive
`_prompt_curation_request` for `CurationAction.INIT` with a reader that presses return at both
version prompts, and assert the resulting bounds contain the running `__version__`. That is the
`RS-02` test's own assertion — `VersionBounds(minimum, maximum).allows(running)` — applied to the
front-end that was missed, so both front-ends are held by the same statement.

The live half re-executes `LA-0-11` and `LA-0-12`, the scenarios that walked the defect, against a
wheel built from this change: `registry init` driven with returned defaults, then `registry
validate` on what it wrote, expecting exit `0` where it exited `1`.
