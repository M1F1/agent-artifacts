# Optional registry-owned usage reporting v1

AART usage reporting is an optional post-outcome operation. A new user configuration defaults to
`prompt` without a central destination. In that mode AART routes each terminal artifact result only
to the configured registry through which that artifact was selected, and only when that registry's
already-published local snapshot advertises a valid reporting service. Direct sources and artifact
upstreams are never implicit reporting destinations.

Users or organizations may select `disabled` to suppress all reporting prompts, or name one
explicit registry destination to centralize reports under reviewed policy. `automatic` always
requires such an explicit destination; a registry advertisement can never enable automatic
submission.

## Destination and submission

AART reads the selected registry's already-published local snapshot without fetching. Its
`aart-registry.json` and `aart.index.json` must agree on registry identity and services. The
`usage_reporting` service must use `github-issues`; its repository coordinate is combined with the
GitHub or GitHub Enterprise host of that exact configured registry.

- `disabled`: no source read, prompt, preview, queue, browser, authentication check, or network;
- `prompt` without `destination`: group results by their registry endpoint, show all destinations,
  then ask separately for each with default No consent, an exact payload preview, and a second
  default No confirmation before opening the prefilled issue in a browser;
- `prompt` with `destination`: send one explicitly centralized report through the same two-consent
  browser flow;
- `automatic`: exact interactive preview followed by `gh auth status --hostname HOST` and
  `gh issue create` with the issue body on stdin; an explicit destination is mandatory.

Two aliases or refs advertising the same host/repository endpoint are deduplicated into one report.
A registry receives only results routed through its aliases and cannot see another registry's
artifacts. Source aliases remain local routing metadata and are never serialized.

Provider and projection failures produce warnings only. They never change the completed artifact
or setup outcome and never change its exit code.

## Event privacy boundary

Schema v1 is canonical, bounded JSON with one result per routed artifact/profile/scope. It
allowlists AART version, interface, platform, action, aggregate status, artifact type/name, profile,
scope, requested/actual mode, artifact/setup outcome, optional installer digest, and typed failure
enums. It deliberately excludes source aliases, repository/origin data, revisions, paths,
destinations, user/machine identity, timestamps, credentials, raw errors, stdout, stderr, and logs.

Consumer terminal `detail` and setup messages are never copied into the event. Partial sessions
retain all terminal items. Server-owned GitHub issue creation time supplies the optional aggregate
day dimension; clients do not create persistent identifiers or timestamps.

## Registry ingestion and dashboard

`aart registry init` installs inert, deterministic templates in addition to registry CI:

- `.github/ISSUE_TEMPLATE/usage-report.yml` for disclosure and browser prefill;
- `.github/workflows/aart-usage-validate.yml` to read the issue body as a file, validate it, and
  label or close the report;
- `.github/workflows/aart-usage-dashboard.yml` to export only validated bodies plus server
  timestamps, aggregate them, and publish a static GitHub Pages artifact.

The workflows never interpolate issue content into shell source. They grant only the permissions
needed for issue validation or Pages publication. Input size, structure, field names, strings,
result count, derived summary, and timestamps are checked before aggregation. Invalid records are
counted but not rendered as content.

Maintainers can run the same boundaries locally:

```console
aart reporting validate-event event.json
aart reporting validate-issue issue-body.md
aart reporting aggregate usage-issues.json --output usage-dashboard
```

The dashboard states that reports are voluntary and incomplete. It presents counts, not a safety
or adoption guarantee, and contains no author dimension.
