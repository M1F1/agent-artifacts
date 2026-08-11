# AART 1.1.1

AART `1.1.1` is a focused compatibility patch. It implements the optional per-artifact
`requires_aart` range already described by the `1.1.0` release contract.

Registry authors can now state that one artifact needs a particular AART capability without tying
unrelated artifacts to that minimum. The bound is carried through canonical manifests and compiled
indexes, exposed in marketplace JSON, and checked at selection/install time. Missing bounds remain
unrestricted. Incompatible skills remain visible: human output names the required range, JSON
includes `aart_compatible: false` plus a notice, and installation is refused instead of attempting a
possibly broken setup.

This is deliberately not version churn: AART never fills in or raises the field just because the
executable receives a patch. Maintainers change it only when an artifact begins using newer AART
behavior.

One bootstrap detail is explicit: `1.1.0` did not parse this field, so a source revision that first
authors it needs a source-level parser floor of `1.1.1`. That floor does not follow later AART patch
versions. See the [`1.1.1` compatibility matrix](compatibility-v3.md).

The installed runtime still uses only the Python standard library. Copy/Symlink behavior, project
and user scopes, configured sources, and the human TUI / agent JSON lifecycle are unchanged from
`1.1.0`.
