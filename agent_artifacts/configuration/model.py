"""Frozen domain values for user configuration and organization policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit

from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.protocol.capabilities import Capability

_SCP_GIT_RE = re.compile(r"^(?P<user>git)@(?P<host>[A-Za-z0-9.-]+):(?P<path>[^\s?#]+)$")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_GIT_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)$")
TRUST_CLASSES = frozenset(
    {"unverified", "local", "direct-source", "registry-reviewed", "company-reviewed"}
)


class SourceKind(str, Enum):
    REGISTRY_GIT = "registry-git"
    SOURCE_GIT = "source-git"
    SOURCE_LOCAL = "source-local"


class SyncMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ReportingMode(str, Enum):
    DISABLED = "disabled"
    PROMPT = "prompt"
    AUTOMATIC = "automatic"


@dataclass(frozen=True, slots=True)
class ConfiguredSource:
    alias: SourceAlias
    kind: SourceKind
    location: str
    ref: str | None
    enabled: bool

    def __post_init__(self) -> None:
        if not self.alias.value or not self.location:
            raise ValueError("configured source identity must be non-empty")
        if not isinstance(self.kind, SourceKind) or not isinstance(self.enabled, bool):
            raise ValueError("configured source kind/enabled value is invalid")
        if self.kind is SourceKind.SOURCE_LOCAL and self.ref is not None:
            raise ValueError("local sources do not have Git refs")
        if self.kind is not SourceKind.SOURCE_LOCAL and self.ref is None:
            raise ValueError("Git sources require a ref")

    @property
    def is_registry(self) -> bool:
        return self.kind is SourceKind.REGISTRY_GIT

    @property
    def is_git(self) -> bool:
        return self.kind in {SourceKind.REGISTRY_GIT, SourceKind.SOURCE_GIT}


@dataclass(frozen=True, slots=True)
class SyncSettings:
    mode: SyncMode = SyncMode.AUTO
    max_age_seconds: int = 900

    def __post_init__(self) -> None:
        if (
            not isinstance(self.mode, SyncMode)
            or not isinstance(self.max_age_seconds, int)
            or isinstance(self.max_age_seconds, bool)
            or not 0 <= self.max_age_seconds <= 2**31 - 1
        ):
            raise ValueError("sync settings are invalid")


@dataclass(frozen=True, slots=True)
class ReportingSettings:
    mode: ReportingMode = ReportingMode.DISABLED
    destination: SourceAlias | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ReportingMode):
            raise ValueError("reporting mode is invalid")
        if self.mode is not ReportingMode.DISABLED and self.destination is None:
            raise ValueError("enabled reporting requires an explicit destination")
        if self.destination is not None and not self.destination.value:
            raise ValueError("reporting destination must be non-empty")


@dataclass(frozen=True, slots=True)
class UserConfiguration:
    schema_version: int
    sources: tuple[ConfiguredSource, ...]
    default_registry: SourceAlias | None
    sync: SyncSettings
    reporting: ReportingSettings

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("user configuration schema version must be 1")
        ordered = tuple(sorted(self.sources, key=lambda item: item.alias.value))
        aliases = tuple(item.alias for item in ordered)
        if len(set(aliases)) != len(aliases):
            raise ValueError("configured source aliases must be unique")
        object.__setattr__(self, "sources", ordered)


@dataclass(frozen=True, slots=True)
class ReportingPolicy:
    mode: ReportingMode | None = None
    destination: SourceAlias | None = None
    deny_public_destinations: bool = False

    def __post_init__(self) -> None:
        if self.mode is not None and not isinstance(self.mode, ReportingMode):
            raise ValueError("reporting policy mode is invalid")
        if self.destination is not None and not self.destination.value:
            raise ValueError("reporting policy destination must be non-empty")
        if not isinstance(self.deny_public_destinations, bool):
            raise ValueError("reporting public-destination policy must be boolean")


@dataclass(frozen=True, slots=True, order=True)
class CompanyReviewedSource:
    """Exact organization-designated registry identity, independent of local alias."""

    source_id: SourceId
    git_host: str
    repository: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_id, SourceId)
            or not isinstance(self.git_host, str)
            or not isinstance(self.repository, str)
            or self.repository.startswith("/")
            or any(character in self.repository for character in "?#")
        ):
            raise ValueError("company-reviewed source identity is invalid")
        host = self.git_host.casefold()
        repository = _valid_repository_path(self.repository)
        if (
            _SLUG_RE.fullmatch(self.source_id.value) is None
            or _GIT_HOST_RE.fullmatch(host) is None
            or repository is None
        ):
            raise ValueError("company-reviewed source identity is invalid")
        object.__setattr__(self, "git_host", host)
        object.__setattr__(self, "repository", repository)


@dataclass(frozen=True, slots=True)
class OrganizationPolicy:
    schema_version: int
    recommended_sources: tuple[SourceAlias, ...] = ()
    required_sources: tuple[SourceAlias, ...] = ()
    allowed_git_hosts: tuple[str, ...] | None = None
    allowed_repository_prefixes: tuple[str, ...] | None = None
    allow_direct_sources: bool | None = None
    minimum_trust_for_user_scope: str | None = None
    allowed_setup_capabilities: tuple[Capability, ...] | None = None
    allow_custom_setup_entrypoints: bool | None = None
    reporting: ReportingPolicy = field(default_factory=ReportingPolicy)
    company_reviewed_sources: tuple[CompanyReviewedSource, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("organization policy schema version must be 1")
        for value in (self.allow_direct_sources, self.allow_custom_setup_entrypoints):
            if value is not None and not isinstance(value, bool):
                raise ValueError("organization policy switches must be boolean or absent")
        if (
            self.minimum_trust_for_user_scope is not None
            and self.minimum_trust_for_user_scope not in TRUST_CLASSES
        ):
            raise ValueError("organization policy minimum trust is invalid")
        if not isinstance(self.reporting, ReportingPolicy):
            raise ValueError("organization reporting policy is invalid")
        if not all(
            isinstance(source, CompanyReviewedSource) for source in self.company_reviewed_sources
        ):
            raise ValueError("organization company-reviewed source identities are invalid")
        recommended = tuple(sorted(set(self.recommended_sources)))
        required = tuple(sorted(set(self.required_sources)))
        if set(recommended) & set(required):
            raise ValueError("recommended and required sources must not overlap")
        object.__setattr__(self, "recommended_sources", recommended)
        object.__setattr__(self, "required_sources", required)
        reviewed = tuple(sorted(set(self.company_reviewed_sources)))
        if len(reviewed) != len(self.company_reviewed_sources):
            raise ValueError("company-reviewed source identities must be unique")
        object.__setattr__(self, "company_reviewed_sources", reviewed)
        if self.allowed_git_hosts is not None:
            object.__setattr__(
                self,
                "allowed_git_hosts",
                tuple(sorted(set(self.allowed_git_hosts))),
            )
        if self.allowed_repository_prefixes is not None:
            object.__setattr__(
                self,
                "allowed_repository_prefixes",
                tuple(sorted(set(self.allowed_repository_prefixes))),
            )
        if self.allowed_setup_capabilities is not None:
            if not all(
                isinstance(capability, Capability) for capability in self.allowed_setup_capabilities
            ):
                raise ValueError("organization setup capabilities are invalid")
            object.__setattr__(
                self,
                "allowed_setup_capabilities",
                tuple(sorted(set(self.allowed_setup_capabilities))),
            )


def default_user_configuration() -> UserConfiguration:
    return UserConfiguration(1, (), None, SyncSettings(), ReportingSettings())


def default_organization_policy() -> OrganizationPolicy:
    return OrganizationPolicy(1)


def _valid_repository_path(raw: str) -> str | None:
    path = raw.lstrip("/").removesuffix(".git")
    if (
        not path
        or path.endswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(character in "\\%" for character in path)
        or any(character.isspace() or ord(character) < 32 for character in path)
    ):
        return None
    return path


def git_location_parts(location: str) -> tuple[str, str] | None:
    """Return normalized host/repository path without ever returning URL credentials."""

    scp = _SCP_GIT_RE.fullmatch(location)
    if scp is not None:
        path = _valid_repository_path(scp.group("path"))
        return None if path is None else (scp.group("host").casefold(), path)
    try:
        parsed = urlsplit(location)
    except ValueError:
        return None
    if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
        return None
    if parsed.password is not None or parsed.query or parsed.fragment:
        return None
    if parsed.scheme == "https" and parsed.username is not None:
        return None
    if parsed.scheme == "ssh" and parsed.username not in {None, "git"}:
        return None
    path = _valid_repository_path(parsed.path)
    return None if path is None else (parsed.hostname.casefold(), path)
