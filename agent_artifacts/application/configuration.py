"""Configuration application service expressed through injected filesystem ports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    UserConfiguration,
    default_organization_policy,
    default_user_configuration,
)
from agent_artifacts.configuration.paths import ConfigPaths
from agent_artifacts.configuration.policy import (
    EffectiveConfiguration,
    RuntimeOverrides,
    apply_configuration,
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


ReadPort = Callable[[ConfigReadRequest], Result[bytes | None]]
WritePort = Callable[[ConfigDocument], Result[ConfigWriteReceipt]]
RecoveryPort = Callable[[ConfigRecoveryPlan], Result[ConfigRecoveryReceipt]]


@dataclass(frozen=True, slots=True)
class ConfigurationPorts:
    read: ReadPort
    write: WritePort
    recover: RecoveryPort


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
    effective: EffectiveConfiguration
    first_run: FirstRunOptions | None
    recovery: ConfigRecoveryPlan | None
    diagnostics: tuple[Diagnostic, ...]


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
    evaluation_policy = policy.value
    previewed_required_sources = bool(
        first_run is not None and not request.content_required and policy.value.required_sources
    )
    if previewed_required_sources:
        evaluation_policy = replace(policy.value, required_sources=())
    effective = apply_configuration(configuration, request.overrides, evaluation_policy)
    if isinstance(effective, Err):
        return effective
    if previewed_required_sources:
        effective = Ok(replace(effective.value, policy=policy.value))
    if request.content_required and not any(
        source.enabled for source in effective.value.configuration.sources
    ):
        return _failure(
            "no-source-configured",
            "this content operation requires at least one enabled source",
            "aart source add",
        )
    return Ok(LoadedConfiguration(effective.value, first_run, recovery, diagnostics))


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


def recover_user_configuration(
    plan: ConfigRecoveryPlan,
    ports: ConfigurationPorts,
) -> Result[ConfigRecoveryReceipt]:
    return ports.recover(plan)
