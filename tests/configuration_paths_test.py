from __future__ import annotations

import unittest

from agent_artifacts.configuration.paths import (
    PathOverrides,
    Platform,
    resolve_config_paths,
)


class ConfigurationPathsTest(unittest.TestCase):
    def test_macos_defaults_are_derived_only_from_injected_home(self) -> None:
        paths = resolve_config_paths(Platform.DARWIN, home="/fake/home")

        self.assertEqual(
            paths.user_config_file,
            "/fake/home/Library/Application Support/agent-artifacts/config.json",
        )
        self.assertEqual(
            paths.data_root,
            "/fake/home/Library/Application Support/agent-artifacts",
        )
        self.assertEqual(paths.cache_root, "/fake/home/Library/Caches/agent-artifacts")
        self.assertEqual(
            paths.policy_file,
            "/Library/Application Support/agent-artifacts/policy.json",
        )

    def test_linux_uses_xdg_roots_and_falls_back_to_injected_home(self) -> None:
        xdg = resolve_config_paths(
            Platform.LINUX,
            home="/fake/home",
            xdg_config_home="/fake/xdg-config",
            xdg_data_home="/fake/xdg-data",
            xdg_cache_home="/fake/xdg-cache",
        )
        fallback = resolve_config_paths(Platform.LINUX, home="/fake/home")

        self.assertEqual(xdg.user_config_file, "/fake/xdg-config/agent-artifacts/config.json")
        self.assertEqual(xdg.data_root, "/fake/xdg-data/agent-artifacts")
        self.assertEqual(xdg.cache_root, "/fake/xdg-cache/agent-artifacts")
        self.assertEqual(
            fallback.user_config_file, "/fake/home/.config/agent-artifacts/config.json"
        )
        self.assertEqual(fallback.data_root, "/fake/home/.local/share/agent-artifacts")
        self.assertEqual(fallback.cache_root, "/fake/home/.cache/agent-artifacts")
        self.assertEqual(fallback.policy_file, "/etc/agent-artifacts/policy.json")

    def test_each_test_override_is_independent_and_absolute(self) -> None:
        paths = resolve_config_paths(
            Platform.LINUX,
            home="/unused/home",
            overrides=PathOverrides(
                config_root="/test/config",
                data_root="/test/data",
                cache_root="/test/cache",
                policy_file="/test/policy/policy.json",
            ),
        )

        self.assertEqual(paths.user_config_file, "/test/config/config.json")
        self.assertEqual(paths.data_root, "/test/data")
        self.assertEqual(paths.cache_root, "/test/cache")
        self.assertEqual(paths.policy_file, "/test/policy/policy.json")

        with self.assertRaises(ValueError):
            resolve_config_paths(Platform.LINUX, home="relative/home")
        with self.assertRaises(ValueError):
            resolve_config_paths(
                Platform.LINUX,
                home="/fake/home",
                overrides=PathOverrides(data_root="relative/data"),
            )


if __name__ == "__main__":
    unittest.main()
