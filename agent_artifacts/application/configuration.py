"""Configuration application service expressed through injected filesystem ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    UserConfiguration,
    default_organization_policy,
    default_user_configuration,
)
from agent_artifacts.configuration.paths import ConfigPaths, config_lock_directory
from agent_artifacts.configuration.policy import (
    EffectiveConfiguration,
    RuntimeOverrides,
    apply_configuration,
    apply_configuration_for_source_management,
)
from agent_artifacts.configuration.schema import (
    parse_organization_policy,
    parse_user_configuration,
    user_configuration_bytes,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import sha256_bytes


@dataclass(frozen=True, slots=True)
class ConfigReadRequest:
    path: str


@dataclass(frozen=True, slots=True)
class ConfigDocument:
    path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ConfigWriteReceipt:
    path: str
    digest: ObjectDigest


@dataclass(frozen=True, slots=True)
class ConfigRecoveryPlan:
    path: str
    backup_path: str
    expected_digest: ObjectDigest
    replacement: bytes


@dataclass(frozen=True, slots=True)
class ConfigRecoveryReceipt:
    path: str
    backup_path: str
    original_digest: ObjectDigest
    replacement_digest: ObjectDigest


@dataclass(frozen=True, slots=True)
class CheckedConfigDocument:
    """One configuration write and the exact prior state it may replace.

    ``expected_digest`` of ``None`` means the file must not exist yet.
    """

    path: str
    content: bytes
    expected_digest: ObjectDigest | None
    lock_directory: str


ReadPort = Callable[[ConfigReadRequest], Result[bytes | None]]
WritePort = Callable[[ConfigDocument], Result[ConfigWriteReceipt]]
RecoveryPort = Callable[[ConfigRecoveryPlan], Result[ConfigRecoveryReceipt]]
# Injected like every other filesystem concern: the application layer states the contract, the io
# layer implements the lock and the compare-and-swap (CFG02).
CheckedWritePort = Callable[[CheckedConfigDocument], Result[ConfigWriteReceipt]]


def _unavailable_checked_write(_document: CheckedConfigDocument) -> Result[ConfigWriteReceipt]:
    return _failure(
        "config-unavailable",
        "this configuration port cannot perform a compare-and-swap write",
        "construct ConfigurationPorts with a checked writer",
    )


@dataclass(frozen=True, slots=True)
class ConfigurationPorts:
    read: ReadPort
    write: WritePort
    recover: RecoveryPort
    # Defaulted so existing three-argument constructions keep working; a caller that reaches the
    # reviewed source-management write must supply a real one.
    write_checked: CheckedWritePort = _unavailable_checked_write


@dataclass(frozen=True, slots=True)
class ConfigurationRequest:
    paths: ConfigPaths
    overrides: RuntimeOverrides
    content_required: bool


@dataclass(frozen=True, slots=True)
class FirstRunOptions:
    recommended_sources: tuple[SourceAlias, ...]
    required_sources: tuple[SourceAlias, ...]
    allow_direct_sources: bool
    allow_no_source: bool


@dataclass(frozen=True, slots=True)
class LoadedConfiguration:
    user_configuration: UserConfiguration
    effective: EffectiveConfiguration
    first_run: FirstRunOptions | None
    recovery: ConfigRecoveryPlan | None
    diagnostics: tuple[Diagnostic, ...]
    # Digest of the exact bytes this load observed, or ``None`` when no configuration file existed.
    # A later compare-and-swap write names this value as the state it is allowed to replace, so a
    # writer that lands in between is refused instead of silently overwritten (CFG02).
    observed_digest: ObjectDigest | None = None


def _failure(code: str, message: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                DiagnosticCode(code),
                Severity.ERROR,
                message,
                remediation=tuple(remediation),
            ),
        )
    )


def _read_documents(
    paths: ConfigPaths, ports: ConfigurationPorts
) -> Result[tuple[bytes | None, bytes | None]]:
    policy = ports.read(ConfigReadRequest(paths.policy_file))
    if isinstance(policy, Err):
        return policy
    user = ports.read(ConfigReadRequest(paths.user_config_file))
    if isinstance(user, Err):
        return user
    return Ok((policy.value, user.value))


def _policy(data: bytes | None) -> Result[OrganizationPolicy]:
    if data is None:
        return Ok(default_organization_policy())
    parsed = parse_organization_policy(data)
    if isinstance(parsed, Err):
        return _failure(
            "policy-invalid",
            "organization policy is invalid; configuration loading failed closed",
            "ask an administrator to repair the organization policy",
        )
    return parsed


def _recovery_plan(path: str, corrupt: bytes) -> ConfigRecoveryPlan:
    digest = sha256_bytes(corrupt)
    return ConfigRecoveryPlan(
        path,
        f"{path}.corrupt-{digest.value[:12]}",
        digest,
        user_configuration_bytes(default_user_configuration()),
    )


def load_configuration(
    request: ConfigurationRequest,
    ports: ConfigurationPorts,
) -> Result[LoadedConfiguration]:
    documents = _read_documents(request.paths, ports)
    if isinstance(documents, Err):
        return documents
    raw_policy, raw_user = documents.value
    policy = _policy(raw_policy)
    if isinstance(policy, Err):
        return policy
    first_run: FirstRunOptions | None = None
    recovery: ConfigRecoveryPlan | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    if raw_user is None:
        configuration = default_user_configuration()
        first_run = FirstRunOptions(
            policy.value.recommended_sources,
            policy.value.required_sources,
            policy.value.allow_direct_sources is not False,
            not policy.value.required_sources,
        )
    else:
        parsed_user = parse_user_configuration(raw_user)
        if isinstance(parsed_user, Err):
            recovery = _recovery_plan(request.paths.user_config_file, raw_user)
            if request.content_required:
                return _failure(
                    "config-invalid",
                    "user configuration is invalid and cannot drive a content operation",
                    "recover the configuration and retry",
                )
            configuration = default_user_configuration()
            diagnostics = (
                Diagnostic(
                    DiagnosticCode("config-invalid"),
                    Severity.WARNING,
                    "user configuration is invalid; using safe defaults until explicit recovery",
                ),
            )
        else:
            configuration = parsed_user.value
    effective = (
        apply_configuration(configuration, request.overrides, policy.value)
        if request.content_required
        else apply_configuration_for_source_management(
            configuration,
            policy.value,
            request.overrides,
        )
    )
    if isinstance(effective, Err):
        return effective
    if request.content_required and not any(
        source.enabled for source in effective.value.configuration.sources
    ):
        return _failure(
            "no-source-configured",
            "this content operation requires at least one enabled source",
            "run `aart source add --help` to configure one non-interactively, or use Add in the TUI Sources stage, then retry",
        )
    return Ok(
        LoadedConfiguration(
            configuration,
            effective.value,
            first_run,
            recovery,
            diagnostics,
            None if raw_user is None else sha256_bytes(raw_user),
        )
    )


def save_user_configuration(
    configuration: UserConfiguration,
    policy: OrganizationPolicy,
    paths: ConfigPaths,
    ports: ConfigurationPorts,
) -> Result[ConfigWriteReceipt]:
    allowed = apply_configuration(configuration, RuntimeOverrides(), policy)
    if isinstance(allowed, Err):
        return allowed
    return ports.write(
        ConfigDocument(paths.user_config_file, user_configuration_bytes(configuration))
    )


def save_user_configuration_checked(
    configuration: UserConfiguration,
    policy: OrganizationPolicy,
    paths: ConfigPaths,
    ports: ConfigurationPorts,
    *,
    expected_digest: ObjectDigest | None,
) -> Result[ConfigWriteReceipt]:
    """Persist a reviewed source-management state, refusing to overwrite a concurrent change.

    This is the CFG02 replacement for :func:`save_user_configuration_for_source_management` on the
    reviewed source-management path.  The caller's earlier read is not trusted on its own: the
    expected digest is re-checked under a configuration lock immediately before the atomic replace,
    which closes the window a pre-write re-read alone cannot.
    """

    allowed = apply_configuration_for_source_management(configuration, policy)
    if isinstance(allowed, Err):
        return allowed
    return ports.write_checked(
        CheckedConfigDocument(
            paths.user_config_file,
            user_configuration_bytes(configuration),
            expected_digest,
            config_lock_directory(paths),
        )
    )


def save_user_configuration_for_source_management(
    configuration: UserConfiguration,
    policy: OrganizationPolicy,
    paths: ConfigPaths,
    ports: ConfigurationPorts,
) -> Result[ConfigWriteReceipt]:
    """Persist a policy-valid source-onboarding state without enabling content operations.

    This is intentionally separate from :func:`save_user_configuration`: it is usable only by the
    reviewed source-management boundary, and it permits missing required aliases while preserving
    every other organization policy constraint.
    """

    allowed = apply_configuration_for_source_management(configuration, policy)
    if isinstance(allowed, Err):
        return allowed
    return ports.write(
        ConfigDocument(paths.user_config_file, user_configuration_bytes(configuration))
    )


def recover_user_configuration(
    plan: ConfigRecoveryPlan,
    ports: ConfigurationPorts,
) -> Result[ConfigRecoveryReceipt]:
    return ports.recover(plan)
