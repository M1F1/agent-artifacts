"""Where the wheel this package came from was built (`docs/ci/enterprise-fork-v1.md` §3.1).

Generated at build time by ``scripts/inject_build_origin.py``, the same way ``_commit.py`` is.
The committed source keeps empty strings: a real value here would churn on every commit, and an
editable or development install has no release to name.

``registry init`` reads this to stamp the workflows it writes, so a wheel built by a company
fork's release CI sends every registry created from it to that fork.  That is what makes the
delivery route stop mattering -- a wheel carries its own origin whether it arrives from a release
URL, an internal index, ``pipx``, or a file on a laptop.
"""

REPOSITORY_URL = ""
REF = ""
COMMIT = ""
VERSION = ""
