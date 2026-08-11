"""Pure macOS/Linux configuration path resolution with explicit test overrides."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from enum import Enum


class Platform(str, Enum):
    DARWIN = "darwin"
    LINUX = "linux"


@dataclass(frozen=True, slots=True)
class PathOverrides:
    config_root: str | None = None
    data_root: str | None = None
    cache_root: str | None = None
    policy_file: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    user_config_file: str
    data_root: str
    cache_root: str
    policy_file: str

    def __post_init__(self) -> None:
        for path in (
            self.user_config_file,
            self.data_root,
            self.cache_root,
            self.policy_file,
        ):
            if not posixpath.isabs(path) or posixpath.normpath(path) != path:
                raise ValueError("configuration paths must be normalized absolute paths")


def _absolute(path: str, label: str) -> str:
    if not posixpath.isabs(path) or posixpath.normpath(path) != path:
        raise ValueError(f"{label} must be a normalized absolute path")
    return path


def config_lock_directory(paths: ConfigPaths) -> str:
    """The lock guarding compare-and-swap writes of the user configuration (CFG02).

    It sits beside the configuration file so the lock and the file it protects always share a
    directory, and therefore a filesystem.
    """

    return paths.user_config_file + ".lock"


def resolve_config_paths(
    platform: Platform,
    *,
    home: str,
    xdg_config_home: str | None = None,
    xdg_data_home: str | None = None,
    xdg_cache_home: str | None = None,
    overrides: PathOverrides | None = None,
) -> ConfigPaths:
    """Resolve paths from supplied values; this function never reads the process environment."""

    if not isinstance(platform, Platform):
        raise ValueError("unsupported configuration platform")
    home = _absolute(home, "home")
    overrides = PathOverrides() if overrides is None else overrides
    for label, value in (
        ("config override", overrides.config_root),
        ("data override", overrides.data_root),
        ("cache override", overrides.cache_root),
        ("policy override", overrides.policy_file),
        ("XDG config home", xdg_config_home),
        ("XDG data home", xdg_data_home),
        ("XDG cache home", xdg_cache_home),
    ):
        if value is not None:
            _absolute(value, label)
    if platform is Platform.DARWIN:
        default_data = posixpath.join(
            home,
            "Library",
            "Application Support",
            "agent-artifacts",
        )
        config_root = overrides.config_root or default_data
        data_root = overrides.data_root or default_data
        cache_root = overrides.cache_root or posixpath.join(
            home,
            "Library",
            "Caches",
            "agent-artifacts",
        )
        policy_file = overrides.policy_file or (
            "/Library/Application Support/agent-artifacts/policy.json"
        )
    else:
        config_root = overrides.config_root or posixpath.join(
            xdg_config_home or posixpath.join(home, ".config"),
            "agent-artifacts",
        )
        data_root = overrides.data_root or posixpath.join(
            xdg_data_home or posixpath.join(home, ".local", "share"),
            "agent-artifacts",
        )
        cache_root = overrides.cache_root or posixpath.join(
            xdg_cache_home or posixpath.join(home, ".cache"),
            "agent-artifacts",
        )
        policy_file = overrides.policy_file or "/etc/agent-artifacts/policy.json"
    return ConfigPaths(
        posixpath.join(config_root, "config.json"),
        data_root,
        cache_root,
        policy_file,
    )
