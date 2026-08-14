"""Source commit the package was built from (docs/design/DESIGN.md §15).

Generated at build time by ``scripts/inject_commit.py`` (WP-21). The ``"unknown"`` default
is used for editable/dev installs and is only consulted by ``check`` / ``upgrade`` (WP-16/17).
``COMMIT_EPOCH`` is that commit's committer date, and is what dates every member of the built
wheel so the archive reproduces from the tag rather than from the clock (SI-8).
"""

COMMIT = "unknown"
COMMIT_EPOCH = 0
