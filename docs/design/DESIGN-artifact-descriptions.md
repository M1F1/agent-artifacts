# Design: first-class artifact descriptions

Status: implemented for issue #16

## 1. Context

Catalog selectors currently identify an artifact only by type and name. The source formats already
usually carry descriptions, but parsers discard them, list JSON omits them, and the TUI cannot
explain why an item is useful. Bundles are the exception: their description is parsed and shown.

Issue #16 makes descriptions a catalog invariant and a presentation contract. The design also
needs to leave clean extension points for the immediately following TUI work:

- #17 will add structured action outcomes;
- #18 will attach install-mode capability/status to choices;
- #19 will attach scope support and resolved destinations;
- #20 will attach setup-installer metadata;
- #21 will retain choices in a basket and render their descriptions in Review.

Descriptions must therefore be domain data, not text scraped from source files by a frontend and
not information encoded only inside a rendered label.

## 2. Goals and non-goals

### Goals

- Give every parsed artifact and bundle a normalized, concise, single-line description.
- Reject missing, blank, non-string, or multiline descriptions at the catalog boundary with an
  error that names the artifact and its canonical descriptor path.
- Carry the description through compatibility filtering and choice construction without rereading
  source files.
- Expose equivalent descriptions through human list output, list JSON, the text TUI, and curses.
- Keep curses selector rows to one visual terminal line and make the complete description
  available on demand.
- Preserve uninstall availability when a catalog source cannot be opened.

### Non-goals

- Persist descriptions in the consumer manifest. A description is catalog presentation metadata,
  while the manifest remains an installation/effect record.
- Add the wizard/navigation state required by #21.
- Add action-result summaries, install modes, scopes, or setup metadata from #17-#20.
- Add a YAML dependency. The runtime remains Python-standard-library-only.
- Judge prose quality algorithmically beyond the structural invariant. Contributor guidance and
  review enforce value-oriented wording.

## 3. Domain model and invariants

`Artifact` gains `description: str`. It remains a frozen value object. The field has an empty
default only to avoid making manually assembled test/domain values unrelated to catalog parsing
invalid; every catalog parser must populate a validated non-empty value.

The parser boundary establishes this invariant for both artifacts and bundles:

1. the `description` key exists;
2. its value is a string scalar;
3. trimming leading/trailing whitespace produces a non-empty value;
4. the normalized value contains no CR or LF;
5. Markdown block-scalar markers and continuation lines are rejected as multiline input.

Normalization is deliberately conservative: trim only the outer whitespace and preserve internal
spacing and punctuation. Frontends consume the normalized value verbatim.

Canonical error labels include both the domain identity and path, for example:

```text
skill 'code-review' (skills/code-review/SKILL.md): missing required 'description' key
mcp 'postgres' (mcp/postgres/mcp.json): 'description' must be a single line
```

## 4. Parsing contract

Metadata is read from one authoritative location per artifact shape:

| Type | Descriptor | Description source |
|---|---|---|
| skill | `skills/<name>/SKILL.md` | flat Markdown frontmatter |
| guideline | `guidelines/<name>.md` | flat Markdown frontmatter |
| memory | `memory/<name>.md` | flat Markdown frontmatter |
| MCP | `mcp/<name>.json` or directory descriptor | JSON `description` |
| hook | `hooks/<name>/hook.json` | JSON `description` |
| bundle | `bundles/<name>.json` | JSON `description` |

Guideline and memory frontmatter is no longer optional because their description is mandatory.
Skills already require frontmatter. The small flat-frontmatter parser remains intentionally
YAML-ish rather than a general YAML parser; block scalars are invalid for this single-line field.

Pure parsing helpers return `Ok(normalized_description)` or `Err`. Type-specific parsers compose
that result with name, compatibility, and descriptor validation, then construct the immutable
domain value. `Source.catalog()` continues to partition and accumulate parser errors, so catalog
validation reports all invalid files in one run.

## 5. Presentation model

The TUI `_Choice` record gains a separate `description` field. Choice construction is a pure
projection from `Artifact` or `Bundle`; filtering returns the same description-bearing value and
does not reload a descriptor.

The default row form is:

```text
[skill] code-review — Review changes for common bugs, risks, and style problems.
```

Bundle availability information remains presentation state on `_Choice` and is appended after the
description. Future issues can add scope/mode/setup facts as fields and let the Review stage render
them without parsing this label.

For update and uninstall choices, the row uses catalog metadata when the matching artifact or
bundle exists. Catalog loading for uninstall is best-effort: inability to load metadata must not
prevent removal based on the manifest.

## 6. Width and detail behavior

Curses rendering uses one pure ellipsis function. Given an available width it returns the original
line when it fits, otherwise a prefix ending in `…`; it never emits more than the supplied width.
The cursor and checkbox prefix count against that width. This replaces silent slicing.

On an artifact/bundle selector, `?` opens a read-only detail view for the current row. The detail
view wraps the complete normalized description, supports arrow/page scrolling when it exceeds the
screen, and returns to the unchanged selection. The text frontend truncates rows to its detected
terminal width and accepts `?N` at the selection prompt to print the full description for item
`N`.

## 7. CLI output contract

Human `aart list` output appends ` — <description>` to every artifact row. Bundle rows retain their
description and extends annotation.

Each object in JSON `artifacts` gains a required `description` property. Bundle JSON already has
the same property. Filtering affects membership only, never object shape, so all frontends receive
the same metadata.

## 8. Functional core / imperative shell boundary

The change follows the existing functional architecture:

- pure core: description validation/normalization, parsing, compatibility filtering, choice
  projection, label construction, and ellipsis;
- imperative shell: filesystem reads in `Source`, printing list output, terminal drawing, and key
  input;
- effects remain represented and dispatched by existing `Request`/command paths.

No frontend reads catalog files and no parser writes state.

## 9. Compatibility and migration

Catalogs without descriptions will fail validation after this change. This is intentional and
actionable. All shipped catalog entries and reusable fixtures are migrated in the same change.
Fixtures intentionally exercising malformed inputs remain malformed for one explicit reason and
receive descriptions when needed to avoid accidental multi-error coupling.

The list JSON addition is backward-compatible for consumers that ignore unknown fields. The
consumer manifest schema is unchanged. Direct test construction of `Artifact(type, name, root)`
continues to work, but no parsed catalog can contain an empty description.

## 10. Risks and mitigations

- **Frontmatter is not full YAML.** Reject block/continued values explicitly and document the flat
  scalar contract.
- **Strict validation breaks old external catalogs.** Include path-rich errors and authoring
  examples; strictness is required by #16.
- **Narrow terminals raise curses boundary errors.** Centralize width handling and test widths of
  zero, one, and small selector rows with a fake screen.
- **Uninstall becomes coupled to a remote source.** Source metadata lookup is best-effort and
  manifest-driven uninstall remains available offline.
- **Future wizard work parses labels.** Keep description and availability facts as `_Choice`
  fields so #21 can consume structured state.

## 11. Acceptance mapping

- Domain field and every parser: sections 3-4.
- Strict validation and actionable errors: sections 3-4.
- Shipped artifacts/fixtures and author guidance: sections 9 and README changes.
- Text/curses rows, truncation, full detail: sections 5-6.
- Human/JSON parity: section 7.
- Compatibility/update/uninstall preservation: section 5.
- All five types, bundle, invalid, width, JSON tests: enforced by the implementation plan.
