#!/usr/bin/env python3
"""The install commands for *this* checkout, naming the instance it actually lives on.

A README cannot do this. Nothing interpolates a repository variable into a markdown file -- GitHub
renders it as text and nothing else -- so a fork's README shows whatever placeholder host upstream
wrote, and the reader edits it by hand or gets it wrong. Which is the same class of problem the CI
portability work solved by reading the runner's own values instead of asking someone to write them
down twice.

So the commands are printed rather than published: derived from the `origin` remote at the moment
someone asks, and composed into the release body at the moment a release is cut. Both come out of
`lines()`, so the page and the terminal cannot come to disagree.

    python scripts/install_commands.py            # this checkout, at its current version
    python scripts/install_commands.py --version 2.9.0

The git form leads because it is the only one that needs nothing arranged first: it goes through
git, and git already has the credentials you push with. The wheel URL is last and carries a warning,
because `pip`, `pipx` and `uv` send no token when fetching a URL -- on a private instance that
returns a sign-in page, and the installer fails on a corrupt archive rather than on a refusal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_api  # noqa: E402
import version as versioning  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def lines(url: str, version: str) -> str:
    """The install block for `url` at `version`, as markdown."""

    tag = f"v{version}"
    wheel = f"agent_artifacts-{version}-py3-none-any.whl"
    return "\n".join(
        (
            "### Install this version",
            "",
            "From the tag. Needs nothing arranged first -- it goes through git, and git uses the",
            "credentials you already push with.",
            "",
            "```sh",
            f'pipx install "git+{url}.git@{tag}"',
            "```",
            "",
            "```sh",
            f'python -m pip install --no-deps "git+{url}.git@{tag}"',
            "```",
            "",
            "```sh",
            f'uv tool install "git+{url}.git@{tag}"',
            "```",
            "",
            "From the wheel attached above, once it is on disk:",
            "",
            "```sh",
            f"pipx install ./{wheel}",
            "```",
            "",
            f"Its address is `{url}/releases/download/{tag}/{wheel}`, but `pip`, `pipx` and `uv`",
            "send no token when they fetch a URL. On a private instance that answers with a",
            "sign-in page and the installer fails on a corrupt archive, so download it with",
            "something that authenticates and install from the file.",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="the version to name; defaults to this checkout's")
    parser.add_argument("--remote", default="origin", help="which remote names the repository")
    parsed = parser.parse_args(argv)

    try:
        url = github_api.repository_url(parsed.remote)
    except github_api.GitHubError as error:
        print(error, file=sys.stderr)
        return 2
    version = parsed.version or str(versioning.read_version(ROOT))
    print(lines(url, version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
