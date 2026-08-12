"""Declarative setup protocol: strict parser and pure planning/state core (issue #20)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .model import (
    Artifact,
    Err,
    InstallScope,
    Ok,
    Result,
    SetupCapability,
    SetupEffect,
    SetupHelpUrl,
    SetupInput,
    SetupInstaller,
    SetupManualReference,
    SetupPlan,
    SetupQueueItem,
    SetupState,
    SetupStateRecord,
    SetupStep,
)
from .tui_layout import CONTENT_MEASURE, field_block, wrap

_TOP_FIELDS = {
    "schema_version",
    "protocol_version",
    "artifact",
    "purpose",
    "platforms",
    "help_urls",
    "required_tools",
    "capabilities",
    "inputs",
    "steps",
    "custom_entrypoint",
}
_CAPABILITIES = {"keychain", "filesystem", "docker", "network", "process", "custom-code"}
_MODULES: Mapping[str, tuple[Optional[SetupCapability], frozenset[str], frozenset[str]]] = {
    "macos-keychain.store@1": (
        "keychain",
        frozenset({"input", "service", "account", "replace_existing"}),
        frozenset({"input", "service", "account"}),
    ),
    "shell.env-from-keychain@1": (
        "filesystem",
        frozenset({"file", "variables"}),
        frozenset({"file", "variables"}),
    ),
    "file.managed-block@1": (
        "filesystem",
        frozenset({"file", "content", "marker"}),
        frozenset({"file", "content"}),
    ),
    "json.managed-merge@1": (
        "filesystem",
        frozenset({"file", "path", "value", "replace_existing"}),
        frozenset({"file", "path", "value"}),
    ),
    "directory.create@1": (
        "filesystem",
        frozenset({"path"}),
        frozenset({"path"}),
    ),
    "docker.pull@1": (
        "docker",
        frozenset({"image", "official_url"}),
        frozenset({"image"}),
    ),
    "command.verify@1": (
        "process",
        frozenset({"argv", "timeout", "cwd"}),
        frozenset({"argv"}),
    ),
    "restart.notice@1": (
        None,
        frozenset({"message"}),
        frozenset({"message"}),
    ),
}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_ARTIFACT_KEY = re.compile(r"^(skill|hook|mcp)/[A-Za-z0-9][A-Za-z0-9._-]*$")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key|api[_-]?token)\s*[:=]\s*[^\s,;]+"
)
_CANONICAL_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SETUP_STATE_REF = re.compile(r"^[a-z0-9][a-z0-9._-]{0,255}$")
_TRUST_CLASSES = {
    "unverified",
    "local",
    "direct-source",
    "registry-reviewed",
    "company-reviewed",
}
_CANONICAL_EVIDENCE_FIELDS = (
    "object_digest",
    "recipe_digest",
    "trust",
    "trust_evidence_digest",
    "policy_digest",
    "capability_plan_digest",
    "canonical_review_digest",
    "setup_state_ref",
)
_MANUAL_SETUP_HEADER = b"# AART manual setup: see ../SETUP.md"


class _Invalid(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _single_line(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise _Invalid(f"{label} must be a non-empty single-line string")
    return value.strip()


def _https(value: object, label: str) -> str:
    url = _single_line(value, label)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise _Invalid(f"{label} must be an https URL")
    return url


def _string_list(value: object, label: str) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise _Invalid(f"{label} must be a list")
    return tuple(_single_line(item, f"{label} entry") for item in value)


def _relative_setup_entrypoint(value: object) -> str:
    path = _single_line(value, "custom_entrypoint")
    normalized = os.path.normpath(path)
    if (
        os.path.isabs(path)
        or normalized.startswith(".." + os.sep)
        or normalized == ".."
        or os.sep in normalized
        or normalized != path
    ):
        raise _Invalid("custom_entrypoint must be a relative file directly below setup/")
    return normalized


def custom_entrypoint_name(raw: bytes) -> Result:
    """Read only the optional custom filename, without accepting the recipe as valid."""

    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or "custom_entrypoint" not in data:
            return Ok(None)
        return Ok(_relative_setup_entrypoint(data["custom_entrypoint"]))
    except (UnicodeDecodeError, json.JSONDecodeError, _Invalid) as exc:
        return Err(f"invalid setup installer: {exc}", code=2)


def has_manual_setup_header(raw: bytes) -> bool:
    """Return whether a custom script begins with the standard manual-route comment.

    A POSIX shebang may precede the comment so direct execution remains possible.  The source
    loader calls this only for version-2 descriptors; retained version-1 custom scripts remain
    valid exactly as published.
    """

    lines = raw.splitlines()
    if lines and lines[0].startswith(b"#!"):
        lines = lines[1:]
    return bool(lines) and lines[0].strip() == _MANUAL_SETUP_HEADER


def _manual_path(descriptor_path: str) -> str:
    """Derive the one conventional package-root manual route from a recipe path."""

    normalized = os.path.normpath(descriptor_path)
    if descriptor_path == normalized == os.path.join("setup", "installer.json"):
        return "SETUP.md"
    package = os.path.dirname(os.path.dirname(normalized))
    if (
        not package
        or normalized != descriptor_path
        or os.path.isabs(normalized)
        or os.path.basename(os.path.dirname(normalized)) != "setup"
        or os.path.basename(normalized) != "installer.json"
        or package == ".."
        or package.startswith(".." + os.sep)
    ):
        raise _Invalid("version-2 installer path must be below a package setup/ directory")
    return os.path.join(package, "SETUP.md")


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _validate_path(value: object, label: str) -> str:
    path = _single_line(value, label)
    expanded = path[2:] if path.startswith("~/") else path
    if "\x00" in path or any(part == ".." for part in expanded.split("/")):
        raise _Invalid(f"{label} cannot contain path traversal")
    return path


def _contains_secret_interpolation(value: object, secret_ids: set[str]) -> bool:
    if isinstance(value, str):
        return any(
            f"${{{secret_id}}}" in value or f"{{{{{secret_id}}}}}" in value
            for secret_id in secret_ids
        )
    if isinstance(value, dict):
        return any(_contains_secret_interpolation(item, secret_ids) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_interpolation(item, secret_ids) for item in value)
    return False


def _validate_step(
    raw: object,
    *,
    step_ids: set[str],
    secret_ids: set[str],
    capabilities: set[str],
) -> SetupStep:
    if not isinstance(raw, dict):
        raise _Invalid("steps entries must be objects")
    unknown = set(raw) - {"id", "use", "with"}
    if unknown:
        raise _Invalid(f"step has unknown field(s): {', '.join(sorted(unknown))}")
    missing = {"id", "use", "with"} - set(raw)
    if missing:
        raise _Invalid(f"step missing field(s): {', '.join(sorted(missing))}")
    step_id = _single_line(raw["id"], "step.id")
    if not _IDENTIFIER.fullmatch(step_id):
        raise _Invalid(f"invalid step id {step_id!r}")
    if step_id in step_ids:
        raise _Invalid(f"duplicate step id {step_id!r}")
    step_ids.add(step_id)
    use = _single_line(raw["use"], f"step {step_id}.use")
    spec = _MODULES.get(use)
    if spec is None:
        raise _Invalid(f"unknown or unsupported setup module {use!r}")
    capability, allowed, required = spec
    if capability is not None and capability not in capabilities:
        raise _Invalid(f"step {step_id!r} requires undeclared capability {capability!r}")
    config = raw["with"]
    if not isinstance(config, dict):
        raise _Invalid(f"step {step_id}.with must be an object")
    unknown_config = set(config) - allowed
    missing_config = required - set(config)
    if unknown_config:
        raise _Invalid(
            f"step {step_id!r} has unknown field(s): {', '.join(sorted(unknown_config))}"
        )
    if missing_config:
        raise _Invalid(f"step {step_id!r} missing field(s): {', '.join(sorted(missing_config))}")
    if use == "macos-keychain.store@1":
        input_id = _single_line(config["input"], f"step {step_id}.input")
        if input_id not in secret_ids:
            raise _Invalid(f"step {step_id!r} references undeclared secret input {input_id!r}")
        _single_line(config["service"], f"step {step_id}.service")
        _single_line(config["account"], f"step {step_id}.account")
        if "replace_existing" in config and not isinstance(config["replace_existing"], bool):
            raise _Invalid(f"step {step_id}.replace_existing must be a boolean")
    elif use == "shell.env-from-keychain@1":
        _validate_path(config["file"], f"step {step_id}.file")
        variables = config["variables"]
        if not isinstance(variables, dict) or not variables:
            raise _Invalid(f"step {step_id}.variables must be a non-empty object")
        for name, lookup in variables.items():
            if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                raise _Invalid(f"step {step_id!r} has invalid environment variable {name!r}")
            if not isinstance(lookup, dict) or set(lookup) != {"service", "account"}:
                raise _Invalid(f"step {step_id}.{name} must contain service and account")
            _single_line(lookup["service"], f"step {step_id}.{name}.service")
            _single_line(lookup["account"], f"step {step_id}.{name}.account")
    elif use == "file.managed-block@1":
        _validate_path(config["file"], f"step {step_id}.file")
        _single_line(config["marker"], f"step {step_id}.marker") if "marker" in config else None
        if not isinstance(config["content"], str):
            raise _Invalid(f"step {step_id}.content must be a string")
    elif use == "json.managed-merge@1":
        _validate_path(config["file"], f"step {step_id}.file")
        path = config["path"]
        if not isinstance(path, list) or not path:
            raise _Invalid(f"step {step_id}.path must be a non-empty string list")
        for part in path:
            _single_line(part, f"step {step_id}.path entry")
        if "replace_existing" in config and not isinstance(config["replace_existing"], bool):
            raise _Invalid(f"step {step_id}.replace_existing must be a boolean")
    elif use == "directory.create@1":
        _validate_path(config["path"], f"step {step_id}.path")
    elif use == "docker.pull@1":
        image = _single_line(config["image"], f"step {step_id}.image")
        if not re.search(r"@sha256:[0-9a-fA-F]{64}$", image):
            raise _Invalid(f"step {step_id}.image must use an immutable sha256 digest")
        if "official_url" in config:
            _https(config["official_url"], f"step {step_id}.official_url")
        for required_cap in ("network", "process"):
            if required_cap not in capabilities:
                raise _Invalid(f"step {step_id!r} requires undeclared capability {required_cap!r}")
    elif use == "command.verify@1":
        argv = config["argv"]
        if not isinstance(argv, list) or not argv:
            raise _Invalid(f"step {step_id}.argv must be a non-empty string list")
        for arg in argv:
            _single_line(arg, f"step {step_id}.argv entry")
        if "cwd" in config:
            _validate_path(config["cwd"], f"step {step_id}.cwd")
        if "timeout" in config and (
            not isinstance(config["timeout"], int) or not 1 <= config["timeout"] <= 300
        ):
            raise _Invalid(f"step {step_id}.timeout must be an integer from 1 to 300")
    elif use == "restart.notice@1":
        _single_line(config["message"], f"step {step_id}.message")
    if use != "macos-keychain.store@1" and _contains_secret_interpolation(config, secret_ids):
        raise _Invalid(f"step {step_id!r} cannot interpolate a secret input")
    frozen = _freeze(config)
    assert isinstance(frozen, Mapping)
    return SetupStep(id=step_id, use=use, config=frozen)


def parse_installer(
    raw: bytes,
    *,
    artifact_key: str,
    descriptor_path: str,
    custom_bytes: Optional[bytes] = None,
) -> Result:
    """Strictly parse and hash a versioned declarative installer."""

    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise _Invalid("installer must be a JSON object")
        unknown = set(data) - _TOP_FIELDS
        if unknown:
            raise _Invalid(f"unknown field(s): {', '.join(sorted(unknown))}")
        required = _TOP_FIELDS - {"custom_entrypoint"}
        missing = required - set(data)
        if missing:
            raise _Invalid(f"missing field(s): {', '.join(sorted(missing))}")
        schema_version = data["schema_version"]
        protocol_version = data["protocol_version"]
        if (
            type(schema_version) is not int
            or type(protocol_version) is not int
            or (schema_version, protocol_version) not in {(1, 1), (2, 2)}
        ):
            raise _Invalid(
                "schema_version and protocol_version must be the matching pair 1/1 or 2/2"
            )
        artifact = _single_line(data["artifact"], "artifact")
        if not _ARTIFACT_KEY.fullmatch(artifact):
            raise _Invalid("artifact must be a directory-shaped skill, hook, or mcp TYPE/NAME")
        if artifact != artifact_key:
            raise _Invalid(f"artifact {artifact!r} does not match containing {artifact_key!r}")
        purpose = _single_line(data["purpose"], "purpose")
        platforms = _string_list(data["platforms"], "platforms")
        if (
            not platforms
            or len(set(platforms)) != len(platforms)
            or any(platform != "darwin" for platform in platforms)
        ):
            raise _Invalid("platforms must be the non-empty list ['darwin'] in protocol v1")
        help_raw = data["help_urls"]
        if not isinstance(help_raw, list):
            raise _Invalid("help_urls must be a list")
        help_urls = []
        for index, entry in enumerate(help_raw):
            if not isinstance(entry, dict) or set(entry) != {"label", "url"}:
                raise _Invalid(f"help_urls[{index}] must contain exactly label and url")
            help_urls.append(
                SetupHelpUrl(
                    _single_line(entry["label"], f"help_urls[{index}].label"),
                    _https(entry["url"], f"help_urls[{index}].url"),
                )
            )
        required_tools = _string_list(data["required_tools"], "required_tools")
        if len(set(required_tools)) != len(required_tools):
            raise _Invalid("required_tools must not contain duplicates")
        capabilities_raw = _string_list(data["capabilities"], "capabilities")
        if len(set(capabilities_raw)) != len(capabilities_raw):
            raise _Invalid("capabilities must not contain duplicates")
        unknown_capabilities = set(capabilities_raw) - _CAPABILITIES
        if unknown_capabilities:
            raise _Invalid(f"unknown capabilities: {', '.join(sorted(unknown_capabilities))}")
        capabilities = tuple(capabilities_raw)
        inputs_raw = data["inputs"]
        if not isinstance(inputs_raw, list):
            raise _Invalid("inputs must be a list")
        inputs = []
        input_ids: set[str] = set()
        for index, entry in enumerate(inputs_raw):
            if not isinstance(entry, dict):
                raise _Invalid(f"inputs[{index}] must be an object")
            unknown_input = set(entry) - {"id", "type", "prompt", "help_url"}
            missing_input = {"id", "type", "prompt"} - set(entry)
            if unknown_input or missing_input:
                raise _Invalid(f"inputs[{index}] has invalid fields")
            input_id = _single_line(entry["id"], f"inputs[{index}].id")
            if not _IDENTIFIER.fullmatch(input_id) or input_id in input_ids:
                raise _Invalid(f"invalid or duplicate input id {input_id!r}")
            input_ids.add(input_id)
            if entry["type"] != "secret":
                raise _Invalid(f"inputs[{index}].type must be 'secret'")
            inputs.append(
                SetupInput(
                    id=input_id,
                    type="secret",
                    prompt=_single_line(entry["prompt"], f"inputs[{index}].prompt"),
                    help_url=(
                        _https(entry["help_url"], f"inputs[{index}].help_url")
                        if "help_url" in entry
                        else None
                    ),
                )
            )
        steps_raw = data["steps"]
        if not isinstance(steps_raw, list) or not steps_raw:
            raise _Invalid("steps must be a non-empty list")
        step_ids: set[str] = set()
        steps = tuple(
            _validate_step(
                entry,
                step_ids=step_ids,
                secret_ids=input_ids,
                capabilities=set(capabilities),
            )
            for entry in steps_raw
        )
        custom_entrypoint = None
        custom_hash = None
        if "custom_entrypoint" in data:
            custom_entrypoint = _relative_setup_entrypoint(data["custom_entrypoint"])
            if "custom-code" not in capabilities or "process" not in capabilities:
                raise _Invalid("custom_entrypoint requires custom-code and process capabilities")
            if custom_bytes is None:
                raise _Invalid("custom_entrypoint bytes are required for hash binding")
            custom_hash = _sha256(custom_bytes)
        elif custom_bytes is not None:
            raise _Invalid("custom bytes supplied without custom_entrypoint")
        typed_capabilities = tuple(capabilities)
        return Ok(
            SetupInstaller(
                schema_version=schema_version,
                protocol_version=protocol_version,
                artifact=artifact,
                purpose=purpose,
                platforms=platforms,
                help_urls=tuple(help_urls),
                required_tools=required_tools,
                capabilities=typed_capabilities,  # type: ignore[arg-type]
                inputs=tuple(inputs),
                steps=steps,
                descriptor_path=descriptor_path,
                descriptor_hash=_sha256(raw),
                custom_entrypoint=custom_entrypoint,
                custom_hash=custom_hash,
                manual_path=_manual_path(descriptor_path) if schema_version == 2 else None,
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _Invalid) as exc:
        return Err(f"invalid setup installer for {artifact_key}: {exc}", code=2)


def build_queue(
    artifacts: Sequence[Artifact],
    profiles: Sequence[str],
    *,
    scope: InstallScope,
    source_label: str,
    source_root: str,
    source_url: str = "",
) -> Tuple[SetupQueueItem, ...]:
    """Create a stable, de-duplicated queue from selected setup-capable artifacts."""

    out = []
    seen = set()
    for artifact in artifacts:
        if artifact.setup is None:
            continue
        for profile in profiles:
            key = (artifact.type, artifact.name, profile, scope)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                SetupQueueItem(
                    artifact_type=artifact.type,
                    artifact_name=artifact.name,
                    profile=profile,
                    scope=scope,
                    source_label=source_label,
                    source_root=source_root,
                    installer=artifact.setup,
                    source_url=source_url,
                )
            )
    return tuple(out)


def _resolve_target(path: str, target_root: str, home_root: str) -> str:
    if path == "~":
        return os.path.abspath(home_root)
    if path.startswith("~/"):
        return os.path.normpath(os.path.join(os.path.abspath(home_root), path[2:]))
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(os.path.abspath(target_root), path))


def _shell_quote(value: str) -> str:
    return shlex.quote(value)


def _shell_block(item: SetupQueueItem, variables: Mapping[str, object]) -> str:
    rows = []
    for name, raw_lookup in variables.items():
        assert isinstance(raw_lookup, Mapping)
        service = str(raw_lookup["service"])
        account = str(raw_lookup["account"])
        rows.append(
            f'export {name}="$(/usr/bin/security find-generic-password '
            f'-a {_shell_quote(account)} -s {_shell_quote(service)} -w 2>/dev/null)"'
        )
    return "\n".join(rows)


def _effect_for_step(
    item: SetupQueueItem, step: SetupStep, target_root: str, home_root: str
) -> SetupEffect:
    config = step.config
    capability = _MODULES[step.use][0]
    target = ""
    argv: Tuple[str, ...] = ()
    reversible = False
    summary = step.use
    planned_config = dict(config)
    if step.use == "macos-keychain.store@1":
        service = str(config["service"])
        account = str(config["account"])
        target = f"Keychain generic password service={service!r} account={account!r}"
        replace_existing = bool(config.get("replace_existing", False))
        argv_parts = [
            "/usr/bin/security",
            "add-generic-password",
        ]
        if replace_existing:
            argv_parts.append("-U")
        argv_parts.extend(
            (
                "-a",
                account,
                "-s",
                service,
                "-w",
            )
        )
        argv = tuple(argv_parts)
        planned_config["replace_existing"] = replace_existing
        reversible = not replace_existing
        replacement = (
            "; replace an existing value (not automatically reversible)"
            if replace_existing
            else "; preserve an existing value"
        )
        summary = f"Store {target}; the security tool prompts without echo{replacement}"
    elif step.use == "shell.env-from-keychain@1":
        target = _resolve_target(str(config["file"]), target_root, home_root)
        variables = config["variables"]
        assert isinstance(variables, Mapping)
        marker = f"{item.artifact_type}/{item.artifact_name}@{item.profile}"
        planned_config.update({"marker": marker, "content": _shell_block(item, variables)})
        reversible = True
        summary = f"Manage Keychain lookup block in {target}"
    elif step.use == "file.managed-block@1":
        target = _resolve_target(str(config["file"]), target_root, home_root)
        planned_config.setdefault(
            "marker", f"{item.artifact_type}/{item.artifact_name}@{item.profile}:{step.id}"
        )
        reversible = True
        summary = f"Manage owned block in {target}"
    elif step.use == "json.managed-merge@1":
        target = _resolve_target(str(config["file"]), target_root, home_root)
        replace_existing = bool(config.get("replace_existing", False))
        planned_config["replace_existing"] = replace_existing
        reversible = not replace_existing
        collision = (
            "; replacing a different existing value is not automatically reversible"
            if replace_existing
            else "; a different existing value is a conflict"
        )
        summary = f"Merge owned JSON value in {target}{collision}"
    elif step.use == "directory.create@1":
        target = _resolve_target(str(config["path"]), target_root, home_root)
        reversible = True
        summary = f"Create directory {target}"
    elif step.use == "docker.pull@1":
        target = str(config["image"])
        argv = ("docker", "pull", target)
        summary = f"Pull digest-pinned Docker image {target}"
    elif step.use == "command.verify@1":
        raw_argv = config["argv"]
        assert isinstance(raw_argv, tuple)
        argv = tuple(str(arg) for arg in raw_argv)
        if "cwd" in config:
            planned_config["cwd"] = _resolve_target(str(config["cwd"]), target_root, home_root)
        summary = f"Verify with argv: {' '.join(shlex.quote(arg) for arg in argv)}"
    elif step.use == "restart.notice@1":
        summary = str(config["message"])
    frozen_config = _freeze(planned_config)
    assert isinstance(frozen_config, Mapping)
    return SetupEffect(
        step_id=step.id,
        module=step.use,
        capability=capability,
        summary=summary,
        target=target,
        argv=argv,
        reversible=reversible,
        config=frozen_config,
    )


def _plan_payload(
    item: SetupQueueItem,
    effects: Sequence[SetupEffect],
    status: object,
    target_root: str,
    home_root: str,
    run_root: str,
) -> dict:
    return {
        "artifact": f"{item.artifact_type}/{item.artifact_name}",
        "profile": item.profile,
        "scope": item.scope,
        "source": item.source_label,
        "installer_hash": item.installer.descriptor_hash,
        "custom_hash": item.installer.custom_hash,
        "preflight_status": status,
        "target_root": os.path.abspath(target_root),
        "home_root": os.path.abspath(home_root),
        "run_root": os.path.abspath(run_root),
        "effects": [
            {
                "step": effect.step_id,
                "module": effect.module,
                "capability": effect.capability,
                "summary": effect.summary,
                "target": effect.target,
                "argv": list(effect.argv),
                "reversible": effect.reversible,
                "config": _plain(effect.config),
            }
            for effect in effects
        ],
    }


def plan_setup(
    item: SetupQueueItem,
    *,
    target_root: str,
    platform: str,
    home_root: Optional[str] = None,
    run_root: Optional[str] = None,
) -> SetupPlan:
    """Resolve exact non-secret effects and bind them to a deterministic plan hash."""

    status = None
    detail = ""
    resolved_target_root = os.path.abspath(target_root)
    resolved_home_root = os.path.abspath(home_root or target_root)
    effects: Tuple[SetupEffect, ...]
    if platform not in item.installer.platforms:
        status = "unsupported"
        detail = (
            f"setup supports {', '.join(item.installer.platforms)}; current platform is {platform}"
        )
        effects = ()
    else:
        effects = tuple(
            _effect_for_step(item, step, resolved_target_root, resolved_home_root)
            for step in item.installer.steps
        )
        if item.installer.custom_entrypoint is not None:
            script_path = os.path.join(
                item.source_root,
                os.path.dirname(item.installer.descriptor_path),
                item.installer.custom_entrypoint,
            )
            effects += (
                SetupEffect(
                    step_id="custom",
                    module="custom.install@1",
                    capability="custom-code",
                    summary=(
                        f"Run reviewed custom plan/apply/verify protocol at {script_path} "
                        f"sha256:{item.installer.custom_hash}"
                    ),
                    target=os.path.normpath(script_path),
                    argv=(os.path.normpath(script_path),),
                    reversible=True,
                    config=MappingProxyType(
                        {
                            "script_hash": item.installer.custom_hash or "",
                            "descriptor_hash": item.installer.descriptor_hash,
                            "artifact": f"{item.artifact_type}/{item.artifact_name}",
                            "profile": item.profile,
                            "scope": item.scope,
                            "source_label": item.source_label,
                        }
                    ),
                ),
            )
    resolved_run_root = os.path.abspath(run_root or target_root)
    payload = _plan_payload(
        item,
        effects,
        status,
        resolved_target_root,
        resolved_home_root,
        resolved_run_root,
    )
    digest = _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return SetupPlan(
        item=item,
        effects=effects,
        plan_hash=digest,
        target_root=resolved_target_root,
        home_root=resolved_home_root,
        run_root=resolved_run_root,
        preflight_status=status,  # type: ignore[arg-type]
        preflight_detail=detail,
    )


@dataclass(frozen=True, slots=True)
class SetupEffectReview:
    """Allowlisted, display-safe facts for one reviewed setup effect."""

    index: int
    identity: str
    target: str
    capability: str
    recovery: str
    details: str


@dataclass(frozen=True, slots=True)
class SetupReview:
    """The pure, shareable setup review consumed by every presentation adapter."""

    artifact: str
    profile: str
    scope: str
    purpose: str
    source_label: str
    recipe_path: str
    recipe_hash: str
    plan_hash: str
    capabilities: Tuple[str, ...]
    required_tools: Tuple[str, ...]
    manual: SetupManualReference
    effects: Tuple[SetupEffectReview, ...]
    preflight_status: Optional[str]
    preflight_detail: str


_PINNED_SOURCE_URL = re.compile(r"^https://[^/]+/.+/blob/[0-9a-f]{40,64}$", re.IGNORECASE)


def _public_text(value: str) -> str:
    """Redact the credential-shaped fragments that author-controlled review text may contain."""

    return _SENSITIVE_ASSIGNMENT.sub("[redacted]", value.replace("\r", " ").replace("\n", " "))


def _contained_manual_path(item: SetupQueueItem, relative_path: str) -> str:
    root = os.path.abspath(item.source_root)
    candidate = os.path.abspath(os.path.join(root, relative_path))
    if os.path.commonpath((root, candidate)) != root:
        return ""
    return candidate


def manual_reference(item: SetupQueueItem) -> SetupManualReference:
    """Resolve the v2 manual route without reading filesystem, environment, or terminal state."""

    relative_path = item.installer.manual_path
    if relative_path is None:
        return SetupManualReference(None, None, legacy=True)
    local_path = _contained_manual_path(item, relative_path)
    if not local_path:
        return SetupManualReference(None, None, legacy=True)
    source_url = item.source_url.rstrip("/")
    if _PINNED_SOURCE_URL.fullmatch(source_url):
        path = relative_path.replace(os.sep, "/")
        return SetupManualReference(relative_path, f"{source_url}/{path}")
    return SetupManualReference(relative_path, local_path)


def _effect_identity(effect: SetupEffect) -> str:
    return {
        "macos-keychain.store@1": "Store a secret in macOS Keychain",
        "shell.env-from-keychain@1": "Add a Keychain environment lookup",
        "file.managed-block@1": "Write an owned configuration block",
        "json.managed-merge@1": "Merge an owned JSON value",
        "directory.create@1": "Create a directory",
        "docker.pull@1": "Pull a digest-pinned Docker image",
        "command.verify@1": "Run a verification command",
        "restart.notice@1": "Show a restart notice",
        "custom.install@1": "Run reviewed custom setup protocol",
    }.get(effect.module, "Run a reviewed setup effect")


def _effect_details(effect: SetupEffect) -> str:
    if effect.module == "macos-keychain.store@1":
        return "required tool: /usr/bin/security"
    if effect.module == "shell.env-from-keychain@1":
        return "Keychain lookup content is withheld from review"
    if effect.module == "file.managed-block@1":
        return "managed content is withheld from review"
    if effect.module == "json.managed-merge@1":
        return "managed JSON value is withheld from review"
    if effect.module == "docker.pull@1":
        return "required tool: docker"
    if effect.module == "command.verify@1":
        return "reviewed command arguments are withheld from review"
    if effect.module == "custom.install@1":
        return "custom script body is withheld from review"
    return "no additional automated command"


def project_setup_review(plan: SetupPlan) -> SetupReview:
    """Project exact setup facts into records that cannot expose secret-bearing inputs or bodies."""

    installer = plan.item.installer
    effects = tuple(
        SetupEffectReview(
            index=index,
            identity=_effect_identity(effect),
            target=_public_text(effect.target) if effect.target else "no filesystem target",
            capability=effect.capability or "none",
            recovery=(
                "removes only changes created by this run"
                if effect.reversible
                else "manual recovery is required"
            ),
            details=_effect_details(effect),
        )
        for index, effect in enumerate(plan.effects, start=1)
    )
    return SetupReview(
        artifact=f"{plan.item.artifact_type}/{plan.item.artifact_name}",
        profile=plan.item.profile,
        scope=plan.item.scope,
        purpose=_public_text(installer.purpose),
        source_label=_public_text(plan.item.source_label),
        recipe_path=installer.descriptor_path,
        recipe_hash=installer.descriptor_hash,
        plan_hash=plan.plan_hash,
        capabilities=tuple(_public_text(value) for value in installer.capabilities),
        required_tools=tuple(_public_text(value) for value in installer.required_tools),
        manual=manual_reference(plan.item),
        effects=effects,
        preflight_status=plan.preflight_status,
        preflight_detail=_public_text(plan.preflight_detail),
    )


_SETUP_COMPLETE = frozenset({"configured", "already_configured", "already-configured"})
# Statuses that prove no effect was attempted, so the manual route is the only remaining work.
# ``skipped`` is deliberately absent: a completed rollback also reports it, and effects did run.
_SETUP_UNSTARTED = frozenset({"declined", "planning-failed", "unsupported"})


def render_manual_alternative(
    reference: SetupManualReference,
    *,
    width: int = CONTENT_MEASURE,
    incomplete: bool = False,
) -> Tuple[str, ...]:
    """Render the non-executing manual route before consent or after an incomplete outcome."""

    lines: Tuple[str, ...] = ("Manual alternative",)
    if reference.legacy:
        return lines + field_block(
            (("instructions", "legacy installer; manual documentation unavailable"),),
            indent=2,
            width=width,
        )
    assert reference.relative_path is not None and reference.source is not None
    return lines + field_block(
        (
            ("instructions", _public_text(reference.relative_path)),
            ("source", _public_text(reference.source)),
            (
                "status",
                (
                    "Automated setup is incomplete; manual action may be needed."
                    if incomplete
                    else "No setup effect has run."
                ),
            ),
        ),
        indent=2,
        width=width,
    )


def render_setup_outcome(
    *,
    artifact: str,
    profile: str,
    scope: str,
    status: str,
    detail: str,
    retry_command: str = "",
    rollback_command: str = "",
    recovery: Sequence[str] = (),
    manual: SetupManualReference | None = None,
    width: int = CONTENT_MEASURE,
) -> Tuple[str, ...]:
    """Render one post-payload setup result as a bounded, redacted terminal record."""

    incomplete = status not in _SETUP_COMPLETE
    lines = wrap(f"Setup outcome: {artifact}@{profile} ({scope})", width=width)
    fields: list[tuple[str, str]] = [
        ("status", _public_text(status)),
        ("details", _public_text(redact_text(detail))),
    ]
    if retry_command:
        fields.append(("retry", _public_text(redact_text(retry_command))))
    if rollback_command:
        fields.append(("rollback", _public_text(redact_text(rollback_command))))
    lines += field_block(tuple(fields), indent=2, width=width)
    if recovery:
        lines += ("Recovery",)
        for item in recovery:
            lines += wrap(f"  {_public_text(redact_text(item))}", width=width)
    if incomplete and manual is not None:
        lines += render_manual_alternative(
            manual, width=width, incomplete=status not in _SETUP_UNSTARTED
        )
    return lines


def render_setup_review(plan: SetupPlan, *, width: int = CONTENT_MEASURE) -> Tuple[str, ...]:
    """Render the shared review as bounded records, never as horizontal effect sentences."""

    review = project_setup_review(plan)
    lines = wrap(
        f"Setup review: {review.artifact}@{review.profile} ({review.scope})",
        width=width,
    )
    lines += field_block(
        (
            ("purpose", review.purpose),
            ("source", review.source_label),
            ("recipe", review.recipe_path),
            ("recipe hash", f"sha256:{review.recipe_hash}"),
            ("plan hash", f"sha256:{review.plan_hash}"),
            ("capabilities", ", ".join(review.capabilities) or "none"),
            ("required tools", ", ".join(review.required_tools) or "none"),
        ),
        indent=2,
        width=width,
    )
    lines += render_manual_alternative(review.manual, width=width)
    lines += ("Effects",)
    for effect in review.effects:
        lines += wrap(f"{effect.index}. {effect.identity}", width=width)
        lines += field_block(
            (
                ("target", effect.target),
                ("capability", effect.capability),
                ("recovery", effect.recovery),
                ("details", effect.details),
            ),
            indent=3,
            width=width,
        )
    if review.preflight_status is not None:
        lines += ("Preflight",) + field_block(
            (
                ("status", review.preflight_status),
                ("details", review.preflight_detail),
            ),
            indent=2,
            width=width,
        )
    return lines


def retry_command(item: SetupQueueItem) -> str:
    return (
        f"aart setup retry {shlex.quote(f'{item.artifact_type}/{item.artifact_name}')} "
        f"--profile {shlex.quote(item.profile)} --scope {item.scope}"
    )


def rollback_command(item: SetupQueueItem) -> str:
    return (
        f"aart setup rollback {shlex.quote(f'{item.artifact_type}/{item.artifact_name}')} "
        f"--profile {shlex.quote(item.profile)} --scope {item.scope}"
    )


def receipt_matches_plan(receipt: Mapping[str, object], plan: SetupPlan) -> bool:
    """Validate every rollback locator against one exact reviewed non-secret effect plan."""

    step_id = receipt.get("step_id")
    effect = next((candidate for candidate in plan.effects if candidate.step_id == step_id), None)
    if effect is None or receipt.get("module") != effect.module:
        return False
    if "path" in receipt and receipt.get("path") != effect.target:
        return False
    if effect.module == "macos-keychain.store@1":
        return receipt.get("service") == effect.config.get("service") and receipt.get(
            "account"
        ) == effect.config.get("account")
    if effect.module in ("shell.env-from-keychain@1", "file.managed-block@1"):
        return receipt.get("marker") == effect.config.get("marker")
    if effect.module == "json.managed-merge@1":
        configured_path = effect.config.get("path")
        return (
            receipt.get("json_path") == list(configured_path)
            if isinstance(configured_path, tuple)
            else False
        )
    if effect.module == "directory.create@1":
        return receipt.get("path") == effect.target
    if effect.module == "docker.pull@1":
        return receipt.get("image") == effect.target
    if effect.module == "custom.install@1":
        run_dir = str(receipt.get("run_dir", ""))
        expected_runs = os.path.join(plan.run_root, ".agent-artifacts", "setup-runs")
        script = str(receipt.get("script", ""))
        try:
            inside_runs = (
                os.path.commonpath((expected_runs, run_dir)) == expected_runs
                and os.path.commonpath((run_dir, script)) == run_dir
            )
        except ValueError:
            inside_runs = False
        return (
            receipt.get("script_source") == effect.target
            and receipt.get("script_hash") == effect.config.get("script_hash")
            and receipt.get("plan_hash") == plan.plan_hash
            and inside_runs
        )
    return effect.module in ("restart.notice@1", "command.verify@1")


def mark_unstarted_skipped(
    items: Sequence[SetupQueueItem], *, detail: str
) -> Tuple[SetupStateRecord, ...]:
    return tuple(
        SetupStateRecord(
            item.artifact_type,
            item.artifact_name,
            item.profile,
            item.scope,
            "skipped",
            detail,
            source_label=item.source_label,
            installer_path=item.installer.descriptor_path,
            installer_hash=item.installer.descriptor_hash,
            custom_hash=item.installer.custom_hash or "",
            schema_version=item.installer.schema_version,
            protocol_version=item.installer.protocol_version,
            retry_command=retry_command(item),
        )
        for item in items
    )


def setup_state_path(scope_root: str) -> str:
    return os.path.join(scope_root, ".agent-artifacts", "setup-state.json")


def redact_text(value: str) -> str:
    return _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", value)


def _redact(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, item in value.items():
            label = str(key)
            if re.search(
                r"(?i)(token|password|passwd|secret|api[_-]?key|stdout|stderr|env)", label
            ):
                out[label] = "[redacted]"
            else:
                out[label] = _redact(item)
        return out
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    return value


def _record_to_dict(record: SetupStateRecord) -> dict:
    evidence = tuple(getattr(record, key) for key in _CANONICAL_EVIDENCE_FIELDS)
    if any(evidence) and not _valid_canonical_evidence(record):
        raise ValueError("canonical setup evidence is incomplete or invalid")
    value = {
        "artifact_type": record.artifact_type,
        "artifact_name": record.artifact_name,
        "profile": record.profile,
        "scope": record.scope,
        "status": record.status,
        "detail": redact_text(record.detail),
        "source_label": record.source_label,
        "installer_path": record.installer_path,
        "installer_hash": record.installer_hash,
        "custom_hash": record.custom_hash,
        "schema_version": record.schema_version,
        "protocol_version": record.protocol_version,
        "plan_hash": record.plan_hash,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "exit_status": record.exit_status,
        "retry_command": record.retry_command,
        "rollback_command": record.rollback_command,
        "receipt_path": record.receipt_path,
        "receipt": _redact(record.receipt),
    }
    for key in _CANONICAL_EVIDENCE_FIELDS:
        field_value = getattr(record, key)
        if field_value:
            value[key] = field_value
    return value


def _valid_canonical_evidence(record: SetupStateRecord) -> bool:
    digests = (
        record.object_digest,
        record.recipe_digest,
        record.trust_evidence_digest,
        record.policy_digest,
        record.capability_plan_digest,
        record.canonical_review_digest,
    )
    return (
        all(_CANONICAL_DIGEST.fullmatch(value) is not None for value in digests)
        and record.trust in _TRUST_CLASSES
        and _SETUP_STATE_REF.fullmatch(record.setup_state_ref) is not None
    )


def dump_setup_state(state: SetupState) -> str:
    return json.dumps(
        {"version": 1, "records": [_record_to_dict(record) for record in state.records]},
        indent=2,
        sort_keys=False,
    )


def parse_setup_state(text: str) -> Result:
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise _Invalid("setup state version must be 1")
        records_raw = raw.get("records")
        if not isinstance(records_raw, list):
            raise _Invalid("setup state records must be a list")
        records = []
        valid_statuses = {
            "configured",
            "already_configured",
            "cancelled",
            "skipped",
            "unsupported",
            "prerequisite_missing",
            "apply_failed_rolled_back",
            "rollback_incomplete",
            "verification_failed",
        }
        for entry in records_raw:
            if not isinstance(entry, dict):
                raise _Invalid("setup state records must be objects")
            status = entry.get("status")
            if status not in valid_statuses:
                raise _Invalid(f"invalid setup terminal status {status!r}")
            artifact_type = entry.get("artifact_type")
            if artifact_type not in ("skill", "guideline", "mcp", "hook", "memory"):
                raise _Invalid(f"invalid artifact type {artifact_type!r}")
            scope = entry.get("scope")
            if scope not in ("project", "user"):
                raise _Invalid(f"invalid setup scope {scope!r}")
            receipt_raw = entry.get("receipt", [])
            if not isinstance(receipt_raw, list) or not all(
                isinstance(x, dict) for x in receipt_raw
            ):
                raise _Invalid("setup receipt must be a list of objects")
            frozen_receipts = tuple(_freeze(x) for x in receipt_raw)
            if not all(isinstance(x, Mapping) for x in frozen_receipts):
                raise _Invalid("setup receipt entries must be immutable objects")
            record = SetupStateRecord(
                artifact_type=artifact_type,
                artifact_name=str(entry.get("artifact_name", "")),
                profile=str(entry.get("profile", "")),
                scope=scope,
                status=status,
                detail=str(entry.get("detail", "")),
                source_label=str(entry.get("source_label", "")),
                installer_path=str(entry.get("installer_path", "")),
                installer_hash=str(entry.get("installer_hash", "")),
                custom_hash=str(entry.get("custom_hash", "")),
                schema_version=int(entry.get("schema_version", 1)),
                protocol_version=int(entry.get("protocol_version", 1)),
                plan_hash=str(entry.get("plan_hash", "")),
                started_at=str(entry.get("started_at", "")),
                finished_at=str(entry.get("finished_at", "")),
                exit_status=entry.get("exit_status"),
                retry_command=str(entry.get("retry_command", "")),
                rollback_command=str(entry.get("rollback_command", "")),
                receipt_path=str(entry.get("receipt_path", "")),
                receipt=frozen_receipts,  # type: ignore[arg-type]
                object_digest=str(entry.get("object_digest", "")),
                recipe_digest=str(entry.get("recipe_digest", "")),
                trust=str(entry.get("trust", "")),
                trust_evidence_digest=str(entry.get("trust_evidence_digest", "")),
                policy_digest=str(entry.get("policy_digest", "")),
                capability_plan_digest=str(entry.get("capability_plan_digest", "")),
                canonical_review_digest=str(entry.get("canonical_review_digest", "")),
                setup_state_ref=str(entry.get("setup_state_ref", "")),
            )
            evidence = tuple(getattr(record, key) for key in _CANONICAL_EVIDENCE_FIELDS)
            if any(evidence) and not _valid_canonical_evidence(record):
                raise _Invalid("canonical setup evidence is incomplete or invalid")
            records.append(record)
        return Ok(SetupState(tuple(records)))
    except (json.JSONDecodeError, _Invalid, TypeError, ValueError) as exc:
        return Err(f"corrupt setup state: {exc}", code=5)


def upsert_setup_record(state: SetupState, record: SetupStateRecord) -> SetupState:
    key = (record.artifact_type, record.artifact_name, record.profile, record.scope)
    out = []
    replaced = False
    for existing in state.records:
        existing_key = (
            existing.artifact_type,
            existing.artifact_name,
            existing.profile,
            existing.scope,
        )
        if existing_key == key:
            out.append(record)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(record)
    return SetupState(tuple(out))


def incomplete_records(records: Iterable[SetupStateRecord]) -> Tuple[SetupStateRecord, ...]:
    complete = {"configured", "already_configured"}
    return tuple(record for record in records if record.status not in complete)


def recovery_messages(record: SetupStateRecord) -> Tuple[str, ...]:
    """Return stable, redacted manual recovery guidance from non-secret receipts."""

    messages = []
    seen = set()
    for receipt in record.receipt:
        raw = receipt.get("recovery", "")
        if not isinstance(raw, str) or not raw.strip():
            continue
        message = redact_text(raw.strip())
        if message not in seen:
            seen.add(message)
            messages.append(message)
    return tuple(messages)


def managed_block(existing: str, marker: str, content: str) -> tuple[str, bool, Optional[str]]:
    """Insert/replace exactly one marker-owned block and return prior owned content."""

    start = f"# >>> aart setup: {marker} >>>"
    end = f"# <<< aart setup: {marker} <<<"
    block = f"{start}\n{content.rstrip()}\n{end}"
    pattern = re.compile(rf"(?ms)^({re.escape(start)}\n.*?\n{re.escape(end)})$")
    matches = list(pattern.finditer(existing))
    if len(matches) > 1:
        raise ValueError(f"multiple managed blocks for {marker}")
    prior = matches[0].group(1) if matches else None
    if prior == block:
        return existing, False, prior
    if matches:
        return pattern.sub(block, existing, count=1), True, prior
    separator = (
        ""
        if not existing
        else ("" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n")
    )
    return f"{existing}{separator}{block}\n", True, None


def rollback_managed_block(
    current: str, marker: str, installed_block: str, prior_block: Optional[str]
) -> Optional[str]:
    """Undo only when the currently owned block still equals this run's installed block."""

    start = f"# >>> aart setup: {marker} >>>"
    end = f"# <<< aart setup: {marker} <<<"
    pattern = re.compile(rf"(?ms)^({re.escape(start)}\n.*?\n{re.escape(end)})\n?")
    match = pattern.search(current)
    if match is None or match.group(1) != installed_block:
        return None
    replacement = f"{prior_block}\n" if prior_block is not None else ""
    return pattern.sub(replacement, current, count=1)
