"""Catalog subscription domain and manifest compatibility tests."""

import json
import unittest

from agent_artifacts import manifest
from agent_artifacts.model import CatalogSubscription, Manifest, ManifestEntry, Ok, Request
from agent_artifacts.subscriptions import (
    group_entries_by_subscription,
    request_for_subscription,
    subscription_from_request,
)


class SubscriptionManifestTests(unittest.TestCase):
    def test_subscription_roundtrips_for_all_source_kinds(self):
        entries = (
            ManifestEntry(
                "packaged",
                "skill",
                "claude",
                "local:/pkg/catalog",
                subscription=CatalogSubscription("package", "/pkg/catalog"),
            ),
            ManifestEntry(
                "local",
                "skill",
                "claude",
                "local:/work/catalog",
                subscription=CatalogSubscription("local", "/work/catalog"),
            ),
            ManifestEntry(
                "remote",
                "skill",
                "claude",
                "main:abc",
                subscription=CatalogSubscription("github", "acme/catalog", "main"),
            ),
        )
        original = Manifest(repo="acme/catalog", installed=entries)

        parsed = manifest.parse_manifest(manifest.dump_manifest(original))

        self.assertEqual(parsed, Ok(original))

    def test_legacy_entry_without_subscription_remains_valid(self):
        parsed = manifest.parse_manifest(
            json.dumps(
                {
                    "repo": "acme/catalog",
                    "installed": [
                        {
                            "artifact": "demo",
                            "type": "skill",
                            "profile": "claude",
                            "source": "main:abc",
                            "files": {},
                        }
                    ],
                }
            )
        )

        self.assertIsInstance(parsed, Ok)
        self.assertIsNone(parsed.value.installed[0].subscription)

    def test_invalid_subscription_is_a_corrupt_manifest(self):
        parsed = manifest.parse_manifest(
            json.dumps(
                {
                    "repo": "acme/catalog",
                    "installed": [
                        {
                            "artifact": "demo",
                            "type": "skill",
                            "profile": "claude",
                            "source": "main:abc",
                            "subscription": {"kind": "gitlab", "location": "acme/catalog"},
                        }
                    ],
                }
            )
        )

        self.assertEqual(parsed.code, 5)
        self.assertIn("subscription.kind", parsed.reason)


class SubscriptionTransformTests(unittest.TestCase):
    def test_derives_package_local_and_github_subscriptions(self):
        self.assertEqual(
            subscription_from_request(Request(command="install"), "/pkg/catalog"),
            CatalogSubscription("package", "/pkg/catalog"),
        )
        self.assertEqual(
            subscription_from_request(
                Request(command="install", source_dir="./catalog"), "/abs/catalog"
            ),
            CatalogSubscription("local", "/abs/catalog"),
        )
        self.assertEqual(
            subscription_from_request(
                Request(command="install", repo="acme/catalog"), "/cache/snapshot"
            ),
            CatalogSubscription("github", "acme/catalog", "main"),
        )
        self.assertEqual(
            subscription_from_request(
                Request(command="install", repo="acme/catalog", version="v2"),
                "/cache/snapshot",
            ),
            CatalogSubscription("github", "acme/catalog", "v2"),
        )

    def test_rebuilds_update_request_without_leaking_previous_source_fields(self):
        base = Request(
            command="update",
            source_dir="old-local",
            repo="old/repo",
            version="old-ref",
            project="/project",
            names=("demo",),
        )

        local = request_for_subscription(base, CatalogSubscription("local", "/catalog"))
        remote = request_for_subscription(
            base, CatalogSubscription("github", "acme/catalog", "release")
        )

        self.assertEqual(local.source_dir, "/catalog")
        self.assertIsNone(local.repo)
        self.assertIsNone(local.version)
        self.assertIsNone(remote.source_dir)
        self.assertEqual(remote.repo, "acme/catalog")
        self.assertEqual(remote.version, "release")
        self.assertEqual(remote.project, "/project")
        self.assertEqual(remote.names, ("demo",))

    def test_package_subscription_reopens_the_current_installed_package(self):
        base = Request(command="update", project="/project")

        rebuilt = request_for_subscription(
            base, CatalogSubscription("package", "/old/virtualenv/catalog")
        )

        self.assertIsNone(rebuilt.source_dir)
        self.assertIsNone(rebuilt.repo)
        self.assertIsNone(rebuilt.version)

    def test_groups_entries_deterministically_by_subscription(self):
        local = CatalogSubscription("local", "/catalog")
        remote = CatalogSubscription("github", "acme/catalog", "main")
        entries = (
            ManifestEntry("one", "skill", "claude", "local:/catalog", subscription=local),
            ManifestEntry("two", "skill", "claude", "main:a", subscription=remote),
            ManifestEntry("three", "skill", "tabnine", "local:/catalog", subscription=local),
            ManifestEntry("legacy", "skill", "claude", "main:old"),
        )

        groups = group_entries_by_subscription(entries)

        self.assertEqual([group.subscription for group in groups], [local, remote, None])
        self.assertEqual(
            [[entry.artifact for entry in group.entries] for group in groups],
            [["one", "three"], ["two"], ["legacy"]],
        )


if __name__ == "__main__":
    unittest.main()
