import json
import unittest

from agent_artifacts.model import Artifact, Bundle, Catalog, Err, Ok, Request
from agent_artifacts.upstreams import (
    UpstreamCatalog,
    UpstreamEntry,
    UpstreamKey,
    UpstreamSelection,
    UpstreamSource,
    UpstreamSync,
    dump_upstreams,
    parse_upstream_key,
    parse_upstreams,
    select_upstreams,
)


def _artifact(artifact_type, name):
    roots = {
        "skill": f"skills/{name}",
        "guideline": f"guidelines/{name}.md",
        "mcp": f"mcp/{name}.json",
        "hook": f"hooks/{name}",
        "memory": f"memory/{name}.md",
    }
    return Artifact(type=artifact_type, name=name, root=roots[artifact_type])


def _bundle(name, includes):
    return Bundle(name=name, description="", extends=(), includes=includes, pins={})


def _catalog():
    artifacts = (
        _artifact("skill", "superpowers"),
        _artifact("skill", "untracked-skill"),
        _artifact("skill", "ambiguous"),
        _artifact("guideline", "python-style"),
        _artifact("mcp", "postgres"),
        _artifact("memory", "karpathy"),
        _artifact("memory", "ambiguous"),
    )
    bundles = (
        _bundle(
            "base",
            {
                "skill": ("superpowers", "untracked-skill"),
                "guideline": ("python-style",),
                "mcp": ("postgres",),
                "memory": ("karpathy",),
            },
        ),
    )
    return Catalog(
        artifacts={(a.type, a.name): a for a in artifacts},
        bundles={b.name: b for b in bundles},
    )


def _entry(artifact_type, name):
    key = UpstreamKey(artifact_type, name)
    return UpstreamEntry(
        key=key,
        source=UpstreamSource(
            kind="github",
            repo=f"example/{name}",
            ref="main",
            path=f"{artifact_type}s/{name}",
        ),
        last_synced=UpstreamSync(
            sha=f"{name}-sha",
            content_hash=f"sha256:{name}",
            synced_at="2026-06-22T10:00:00Z",
        ),
    )


def _upstreams(*keys):
    entries = {_key.type + "/" + _key.name: _entry(_key.type, _key.name) for _key in keys}
    return UpstreamCatalog(
        version=1,
        entries={entry.key: entry for entry in entries.values()},
    )


def _selected_keys(result):
    assert isinstance(result, Ok), result
    return tuple(str(entry.key) for entry in result.value.entries)


class UpstreamKeyTests(unittest.TestCase):
    def test_parse_and_format_type_name_key(self):
        key = UpstreamKey.parse("skill/superpowers")

        self.assertEqual(key, Ok(UpstreamKey("skill", "superpowers")))
        self.assertEqual(parse_upstream_key("memory/karpathy"), Ok(UpstreamKey("memory", "karpathy")))
        self.assertEqual(str(UpstreamKey("guideline", "python-style")), "guideline/python-style")
        self.assertEqual(UpstreamKey("mcp", "postgres").format(), "mcp/postgres")

    def test_rejects_invalid_key_strings(self):
        cases = ("skill", "skill/", "/name", "unknown/name", "skill/foo/bar")

        for raw in cases:
            with self.subTest(raw=raw):
                result = UpstreamKey.parse(raw)
                self.assertIsInstance(result, Err)
                self.assertIn(raw, result.reason)


class ParseDumpTests(unittest.TestCase):
    def test_parse_and_dump_round_trip(self):
        text = json.dumps(
            {
                "version": 1,
                "artifacts": {
                    "memory/karpathy": {
                        "source": {
                            "kind": "github",
                            "repo": "example/karpathy-skills",
                            "ref": "main",
                            "path": "memory/prompting.md",
                        }
                    },
                    "skill/superpowers": {
                        "source": {
                            "kind": "github",
                            "repo": "example/superpowers",
                            "ref": "v1",
                            "path": "skills/superpowers",
                        },
                        "last_synced": {
                            "sha": "abc123",
                            "content_hash": "sha256:abc",
                            "synced_at": "2026-06-22T10:00:00Z",
                        },
                    },
                },
            }
        )

        parsed = parse_upstreams(text)

        self.assertIsInstance(parsed, Ok)
        catalog = parsed.value
        self.assertEqual(catalog.version, 1)
        self.assertEqual(
            catalog.entries[UpstreamKey("skill", "superpowers")].source.repo,
            "example/superpowers",
        )
        self.assertIsNone(catalog.entries[UpstreamKey("memory", "karpathy")].last_synced)

        dumped = dump_upstreams(catalog)
        self.assertTrue(dumped.endswith("\n"))
        self.assertEqual(parse_upstreams(dumped), parsed)
        self.assertEqual(dump_upstreams(parse_upstreams(dumped).value), dumped)

    def test_invalid_schema_accumulates_errors(self):
        text = json.dumps(
            {
                "version": 2,
                "artifacts": {
                    "ghost/name": {},
                    "skill/bad": {
                        "source": {"kind": "gitlab", "repo": 4, "ref": "", "path": ""},
                        "last_synced": {
                            "sha": 7,
                            "content_hash": [],
                            "synced_at": 8,
                        },
                    },
                },
            }
        )

        result = parse_upstreams(text)

        self.assertIsInstance(result, Err)
        for expected in (
            "version",
            "ghost/name",
            "source.kind",
            "source.repo",
            "source.ref",
            "source.path",
            "last_synced.sha",
            "last_synced.content_hash",
            "last_synced.synced_at",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, result.reason)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.upstreams = _upstreams(
            UpstreamKey("skill", "superpowers"),
            UpstreamKey("skill", "ambiguous"),
            UpstreamKey("guideline", "python-style"),
            UpstreamKey("memory", "karpathy"),
            UpstreamKey("memory", "ambiguous"),
        )

    def test_selects_by_name(self):
        result = select_upstreams(
            Request(command="upstream", names=("superpowers",)),
            self.catalog,
            self.upstreams,
        )

        self.assertEqual(_selected_keys(result), ("skill/superpowers",))
        self.assertEqual(result.value.warnings, ())

    def test_selects_explicit_type_name(self):
        result = select_upstreams(
            Request(command="upstream", names=("memory/karpathy",)),
            self.catalog,
            self.upstreams,
        )

        self.assertEqual(_selected_keys(result), ("memory/karpathy",))

    def test_type_filter_disambiguates_name_selection(self):
        result = select_upstreams(
            Request(command="upstream", names=("ambiguous",), type_filter="memory"),
            self.catalog,
            self.upstreams,
        )

        self.assertEqual(_selected_keys(result), ("memory/ambiguous",))

    def test_all_selects_every_tracked_catalog_artifact(self):
        result = select_upstreams(
            Request(command="upstream", all=True),
            self.catalog,
            self.upstreams,
        )

        self.assertEqual(
            _selected_keys(result),
            (
                "guideline/python-style",
                "memory/ambiguous",
                "memory/karpathy",
                "skill/ambiguous",
                "skill/superpowers",
            ),
        )

    def test_bundle_skips_untracked_members_with_warning(self):
        result = select_upstreams(
            Request(command="upstream", bundles=("base",)),
            self.catalog,
            self.upstreams,
        )

        self.assertEqual(
            result,
            Ok(
                UpstreamSelection(
                    entries=(
                        self.upstreams.entries[UpstreamKey("skill", "superpowers")],
                        self.upstreams.entries[UpstreamKey("guideline", "python-style")],
                        self.upstreams.entries[UpstreamKey("memory", "karpathy")],
                    ),
                    warnings=(
                        "bundle 'base': skipped untracked artifact skill/untracked-skill",
                        "bundle 'base': skipped untracked artifact mcp/postgres",
                    ),
                )
            ),
        )

    def test_explicit_untracked_selection_is_error(self):
        for request in (
            Request(command="upstream", names=("untracked-skill",)),
            Request(command="upstream", names=("skill/untracked-skill",)),
        ):
            with self.subTest(request=request):
                result = select_upstreams(request, self.catalog, self.upstreams)

                self.assertIsInstance(result, Err)
                self.assertEqual(result.code, 2)
                self.assertIn("untracked artifact skill/untracked-skill", result.reason)


if __name__ == "__main__":
    unittest.main()
