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
from .redaction import redact_text
from .tui_layout import CONTENT_MEASURE, field_block, measure, wrap

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
_CAPABILITIES = {
    "keychain",
    "filesystem",
    "docker",
    "network",
    "process",
    "custom-code",
    "trust-store",
}
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
    "shell.env-from-input@1": (
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
    "docker.build@1": (
        "docker",
        frozenset({"context", "dockerfile"}),
        frozenset({"context"}),
    ),
    "trust-store.export-certificates@1": (
        "trust-store",
        frozenset({"subject_contains", "output"}),
        frozenset({"subject_contains", "output"}),
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
# What each module needs, in the vocabulary policy and the compiled index speak. It is deliberately
# not the author's vocabulary above: an author declares that a recipe touches `filesystem`, while an
# organization decides whether it will allow a `managed-file` write or a `docker-build`. Both the
# index compiler and the consumer read this table, because publishing one vocabulary and recomputing
# the other is how `LAF-51` made every non-trivial recipe unplannable.
_PLANNED_CAPABILITIES: Mapping[str, Tuple[str, ...]] = {
    "macos-keychain.store@1": ("keychain",),
    "shell.env-from-keychain@1": ("managed-file",),
    "shell.env-from-input@1": ("managed-file",),
    "file.managed-block@1": ("managed-file",),
    "json.managed-merge@1": ("managed-file",),
    "directory.create@1": ("managed-file",),
    "docker.pull@1": ("docker-pull", "network"),
    # A build reaches the network for its base image and its `RUN` lines, and runs a local process to
    # do it. An organization that denies either must be able to deny this.
    "docker.build@1": ("docker-build", "network", "process"),
    "trust-store.export-certificates@1": ("trust-store",),
    "command.verify@1": ("verify-command",),
    "restart.notice@1": (),
}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_ARTIFACT_KEY = re.compile(r"^(skill|hook|mcp)/[A-Za-z0-9][A-Za-z0-9._-]*$")
# The redactor is `redaction.redact_text`, imported above.  This module used to carry a second,
# weaker one, and `dump_setup_state` — the function that writes to disk — used that one, so a
# credentialed clone URL was hidden in a diagnostic and persisted in full (`LAF-72`).
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


def _package_relative_source(value: object, label: str) -> str:
    """Validate a name for something a recipe *reads* out of the package it ships in.

    Every other path in a recipe is a destination, resolved against the consumer's home or their
    project.  This is the one kind that points the other way, at the package itself, so it is
    validated separately and with its own error text: a failure here means a maintainer named
    something to read, not somewhere to write, and the two are diagnosed differently.

    The rule is `custom_entrypoint`'s — one relative name directly below its root, no separator, no
    `..`, nothing an author could steer at the rest of the store.
    """

    path = _single_line(value, label)
    normalized = os.path.normpath(path)
    if (
        os.path.isabs(path)
        or normalized in ("..", ".")
        or normalized.startswith(".." + os.sep)
        or os.sep in normalized
        or normalized != path
    ):
        raise _Invalid(f"{label} must be a relative name directly below the package root")
    return normalized


def _context_relative_file(value: object, label: str) -> str:
    """A file inside a materialized build context, named relative to the context root."""

    path = _single_line(value, label)
    normalized = os.path.normpath(path)
    if (
        os.path.isabs(path)
        or normalized != path
        or normalized == "."
        or any(part == ".." for part in normalized.split(os.sep))
    ):
        raise _Invalid(f"{label} must be a relative file inside the build context")
    return normalized


def planned_capabilities(installer: SetupInstaller) -> Tuple[str, ...]:
    """What this recipe's steps need, in the vocabulary policy and the compiled index speak.

    The recipe's own `capabilities` field is the author's declaration and is checked against the
    modules used.  This is the other side: what a consumer's organization is being asked to allow.
    A registry publishes this so that a policy can refuse a build without first reading the recipe,
    and a consumer recomputes it from the same bytes so that a tampered index does not decide.
    """

    values: set[str] = set()
    for step in installer.steps:
        values.update(_PLANNED_CAPABILITIES.get(step.use, ()))
    if installer.custom_entrypoint is not None:
        values.add("custom-code")
    return tuple(sorted(values))


def image_tag(item: "SetupQueueItem") -> str:
    """The one tag a locally built image may carry, derived from identity and version.

    A build has no digest to pin before it runs and two machines building one context get two image
    ids, so the tag cannot be evidence.  What it can be is unambiguous: derived rather than
    authored, so two versions of one artifact cannot collide, so a descriptor can name the image
    before the build exists, and so rollback knows exactly what it is allowed to remove.
    """

    return f"aart/{item.artifact_type}/{item.artifact_name}:{item.artifact_version}"


def build_context_source(item: "SetupQueueItem") -> str:
    """Resolve the single build context this recipe declares, or the empty string for none."""

    for step in item.installer.steps:
        if step.use == "docker.build@1":
            return resolve_package_source(item, str(step.config["context"]))
    return ""


def resolve_package_source(item: "SetupQueueItem", path: str) -> str:
    """Resolve one validated package-relative name against the package this recipe belongs to.

    Resolution happens at plan time, never at apply time, so the review already names exactly what
    will be read.  The containment check is redundant against a validated name and is kept anyway:
    it is the boundary that keeps the object store readable-only-here if the validator ever widens.
    """

    root = os.path.abspath(
        os.path.join(
            os.path.abspath(item.source_root),
            os.path.dirname(os.path.dirname(os.path.normpath(item.installer.descriptor_path))),
        )
    )
    candidate = os.path.abspath(os.path.join(root, path))
    if candidate == root or os.path.commonpath((root, candidate)) != root:
        raise _Invalid(f"package source {path!r} escapes the package root")
    return candidate


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

    A POSIX shebang may precede the comment so direct execution remains possible.  The one current
    setup protocol requires this header on every custom entrypoint.
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
    text_ids: set[str],
    capabilities: set[str],
    required_tools: Sequence[str],
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
    elif use == "shell.env-from-input@1":
        _validate_path(config["file"], f"step {step_id}.file")
        variables = config["variables"]
        if not isinstance(variables, dict) or not variables:
            raise _Invalid(f"step {step_id}.variables must be a non-empty object")
        for name, raw_input_id in variables.items():
            if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                raise _Invalid(f"step {step_id!r} has invalid environment variable {name!r}")
            input_id = _single_line(raw_input_id, f"step {step_id}.{name}")
            if input_id not in text_ids:
                raise _Invalid(f"step {step_id!r} references undeclared text input {input_id!r}")
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
    elif use == "docker.build@1":
        _package_relative_source(config["context"], f"step {step_id}.context")
        if "dockerfile" in config:
            _context_relative_file(config["dockerfile"], f"step {step_id}.dockerfile")
        for required_cap in ("network", "process"):
            if required_cap not in capabilities:
                raise _Invalid(f"step {step_id!r} requires undeclared capability {required_cap!r}")
        if "docker" not in required_tools:
            # A build that cannot find the tool must fail as a missing prerequisite, before any
            # consent is asked for, rather than as a build error halfway through the recipe.
            raise _Invalid(f"step {step_id!r} requires 'docker' in required_tools")
    elif use == "trust-store.export-certificates@1":
        _single_line(config["subject_contains"], f"step {step_id}.subject_contains")
        _context_relative_file(config["output"], f"step {step_id}.output")
        if "/usr/bin/security" not in required_tools:
            raise _Invalid(f"step {step_id!r} requires '/usr/bin/security' in required_tools")
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
            or (schema_version, protocol_version) != (2, 2)
        ):
            raise _Invalid(
                "schema_version and protocol_version must both be 2; a superseded recipe is "
                "migrated by raising both to 2 and adding the package-root SETUP.md route"
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
            raise _Invalid("platforms must be the non-empty list ['darwin']")
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
        secret_ids: set[str] = set()
        text_ids: set[str] = set()
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
            input_type = entry["type"]
            if input_type not in {"secret", "text"}:
                raise _Invalid(f"inputs[{index}].type must be 'secret' or 'text'")
            (secret_ids if input_type == "secret" else text_ids).add(input_id)
            inputs.append(
                SetupInput(
                    id=input_id,
                    type=input_type,
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
                secret_ids=secret_ids,
                text_ids=text_ids,
                capabilities=set(capabilities),
                required_tools=required_tools,
            )
            for entry in steps_raw
        )
        uses = [step.use for step in steps]
        if "trust-store.export-certificates@1" in uses:
            # A certificate export writes into the build context and nowhere else, so a recipe
            # without a build has nowhere to put it, and one that exports after the build has
            # already built without it.
            if "docker.build@1" not in uses:
                raise _Invalid(
                    "trust-store.export-certificates@1 requires a docker.build@1 step to write into"
                )
            if uses.index("trust-store.export-certificates@1") > uses.index("docker.build@1"):
                raise _Invalid(
                    "trust-store.export-certificates@1 must come before the docker.build@1 step"
                )
        if sum(step.use == "docker.build@1" for step in steps) > 1:
            # One recipe, one build context: it is materialized once for the run and every step
            # that contributes a file contributes to that one copy.
            raise _Invalid("a recipe may declare at most one docker.build@1 step")
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
                manual_path=_manual_path(descriptor_path),
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
    artifact_version: str = "",
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
                    artifact_version=artifact_version,
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
    item: SetupQueueItem,
    step: SetupStep,
    target_root: str,
    home_root: str,
    context_source: str = "",
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
        input_id = str(config["input"])
        input_prompt = next(
            declared.prompt for declared in item.installer.inputs if declared.id == input_id
        )
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
        summary = (
            f"{input_prompt}: store {target}; the security tool prompts without echo{replacement}"
        )
    elif step.use == "shell.env-from-keychain@1":
        target = _resolve_target(str(config["file"]), target_root, home_root)
        variables = config["variables"]
        assert isinstance(variables, Mapping)
        marker = f"{item.artifact_type}/{item.artifact_name}@{item.profile}"
        planned_config.update({"marker": marker, "content": _shell_block(item, variables)})
        reversible = True
        summary = f"Manage Keychain lookup block in {target}"
    elif step.use == "shell.env-from-input@1":
        target = _resolve_target(str(config["file"]), target_root, home_root)
        variables = config["variables"]
        assert isinstance(variables, Mapping)
        declared = {input_.id: input_ for input_ in item.installer.inputs}
        input_prompts = {
            str(input_id): declared[str(input_id)].prompt for input_id in variables.values()
        }
        marker = f"{item.artifact_type}/{item.artifact_name}@{item.profile}:{step.id}"
        planned_config.update({"marker": marker, "input_prompts": input_prompts})
        reversible = True
        summary = f"Manage echoed text input environment block in {target}"
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
    elif step.use == "docker.build@1":
        target = image_tag(item)
        dockerfile = str(config.get("dockerfile", "Dockerfile"))
        # The context is a working copy whose path exists only once the run opens, so the reviewed
        # argv names the Dockerfile and `.`, and the run makes that `.` the materialized copy.
        argv = ("docker", "build", "--tag", target, "--file", dockerfile, ".")
        planned_config.update({"dockerfile": dockerfile, "context_source": context_source})
        reversible = True
        summary = (
            f"Build local Docker image {target} from a copy of {context_source} "
            f"using {dockerfile}; the image is never pushed anywhere"
        )
    elif step.use == "trust-store.export-certificates@1":
        subject = str(config["subject_contains"])
        output = str(config["output"])
        target = f"{output} inside the build context"
        argv = ("/usr/bin/security", "find-certificate", "-a", "-c", subject, "-p")
        planned_config["context_source"] = context_source
        reversible = True
        summary = (
            f"Export certificates whose name contains {subject!r} into the build context "
            f"as {output}; no private key is read and nothing is stored"
        )
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
    elif not item.artifact_version and any(
        step.use == "docker.build@1" for step in item.installer.steps
    ):
        # The tag is derived from identity and version, so a record that carries no version cannot
        # be reviewed: there is nothing to show, and nothing rollback could later claim to own.
        status = "prerequisite_missing"
        detail = "a locally built image is tagged from the artifact version, which is not recorded"
        effects = ()
    else:
        effects = tuple(
            _effect_for_step(
                item,
                step,
                resolved_target_root,
                resolved_home_root,
                build_context_source(item),
            )
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


_PINNED_SOURCE_URL = re.compile(
    r"^https://[^/]+/.+/blob/[0-9a-f]{40,64}(?:/.*)?$",
    re.IGNORECASE,
)


_REDACTED_ASSIGNMENT = re.compile(r"[A-Za-z0-9_.-]*\s*[:=]\s*\[redacted\]")


def public_text(value: str) -> str:
    """Redact the credential-shaped fragments that author-controlled review text may contain.

    Stricter than `redact_text` by one step: the name goes too.  Everywhere else `TOKEN=[redacted]`
    is the better rendering, because it tells the operator what kind of thing was hidden.  Review
    text is the exception — the string is chosen by the *author* of a recipe the operator has not
    yet consented to, so it is shown with the least of it that still reads as text.

    `redact_text` decides what counts as a credential; this decides how much of it to show.  There
    is still only one answer to the first question, which is the point of `RR-10A`.
    """

    return _REDACTED_ASSIGNMENT.sub(
        "[redacted]", redact_text(value.replace("\r", " ").replace("\n", " "))
    )


def _contained_manual_path(item: SetupQueueItem, relative_path: str) -> str:
    root = os.path.abspath(item.source_root)
    candidate = os.path.abspath(os.path.join(root, relative_path))
    if os.path.commonpath((root, candidate)) != root:
        return ""
    return candidate


def manual_reference(item: SetupQueueItem) -> SetupManualReference:
    """Resolve the manual route without reading filesystem, environment, or terminal state."""

    relative_path = item.installer.manual_path
    local_path = _contained_manual_path(item, relative_path)
    if not local_path:
        # A derived route cannot escape the package, so this only guards a future producer:
        # name the route inside the package rather than publish a path outside the source root.
        return SetupManualReference(relative_path, relative_path)
    source_url = item.source_url.rstrip("/")
    if _PINNED_SOURCE_URL.fullmatch(source_url):
        path = relative_path.replace(os.sep, "/")
        return SetupManualReference(relative_path, f"{source_url}/{path}")
    return SetupManualReference(relative_path, local_path)


def _effect_identity(effect: SetupEffect) -> str:
    return {
        "macos-keychain.store@1": "Store a secret in macOS Keychain",
        "shell.env-from-keychain@1": "Add a Keychain environment lookup",
        "shell.env-from-input@1": "Export a prompted text input",
        "file.managed-block@1": "Write an owned configuration block",
        "json.managed-merge@1": "Merge an owned JSON value",
        "directory.create@1": "Create a directory",
        "docker.pull@1": "Pull a digest-pinned Docker image",
        "docker.build@1": "Build a local Docker image from this package",
        "trust-store.export-certificates@1": "Export certificates into the build context",
        "command.verify@1": "Run a verification command",
        "restart.notice@1": "Show a restart notice",
        "custom.install@1": "Run reviewed custom setup protocol",
    }.get(effect.module, "Run a reviewed setup effect")


def _effect_details(effect: SetupEffect) -> str:
    if effect.module == "macos-keychain.store@1":
        return "required tool: /usr/bin/security"
    if effect.module == "shell.env-from-keychain@1":
        return "Keychain lookup content is withheld from review"
    if effect.module == "shell.env-from-input@1":
        prompts = effect.config.get("input_prompts", {})
        if isinstance(prompts, Mapping):
            rendered = "; ".join(str(prompt) for prompt in prompts.values())
        else:
            rendered = "declared text input"
        return f"prompts with echo before effects: {rendered}"
    if effect.module == "file.managed-block@1":
        return "managed content is withheld from review"
    if effect.module == "json.managed-merge@1":
        return "managed JSON value is withheld from review"
    if effect.module == "docker.pull@1":
        return "required tool: docker"
    if effect.module == "docker.build@1":
        # A build is not a pull. It executes the Dockerfile's instructions, and `RUN` is arbitrary
        # code with network access, so the review says that in those words rather than in a tag.
        return (
            f"required tool: docker; runs the instructions in "
            f"{effect.config.get('dockerfile', 'Dockerfile')} with network access, from a copy of "
            f"{effect.config.get('context_source', '')}; the image stays on this machine"
        )
    if effect.module == "trust-store.export-certificates@1":
        return (
            "required tool: /usr/bin/security; reads public certificates from the login and "
            "System keychains, exports no private key, and writes only into the build context"
        )
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
            target=public_text(effect.target) if effect.target else "no filesystem target",
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
        purpose=public_text(installer.purpose),
        source_label=public_text(plan.item.source_label),
        recipe_path=installer.descriptor_path,
        recipe_hash=installer.descriptor_hash,
        plan_hash=plan.plan_hash,
        capabilities=tuple(public_text(value) for value in installer.capabilities),
        required_tools=tuple(public_text(value) for value in installer.required_tools),
        manual=manual_reference(plan.item),
        effects=effects,
        preflight_status=plan.preflight_status,
        preflight_detail=public_text(plan.preflight_detail),
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
    return lines + field_block(
        (
            ("instructions", public_text(reference.relative_path)),
            ("source", public_text(reference.source)),
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


def home_relative(path: str, home: str = "") -> str:
    """`~/.zshrc`, not `/Users/someone/.zshrc`.

    This path is printed for a person to copy.  Spelling out their home directory is noise, and it
    reads like a value the tool baked in rather than one it found (`AD-35`).

    `~` is left unquoted, because a quoted tilde is a literal one and the shell would look for a
    directory named `~`.  Anything needing quotes is quoted after the first slash, where quoting
    costs nothing.
    """

    root = (home or os.path.expanduser("~")).rstrip("/")
    if not root or not path.startswith(root + "/"):
        return shlex.quote(path)
    return f"~/{shlex.quote(path[len(root) + 1 :])}"


def shell_reload_suffix(shell_file: str, home: str = "") -> str:
    """The ` && source ~/.zshrc` tail, or nothing when this run wrote no shell file.

    Storing the secret alone changes nothing a running shell can see — the managed block is read
    when a shell starts — so the reload is joined to the command rather than left as a step to
    remember (`AD-31`).
    """

    if not shell_file:
        return ""
    return f" && source {home_relative(shell_file, home)}"


_SHELL_MODULES = ("shell.env-from-keychain@1", "shell.env-from-input@1")


def _shell_file_of(receipts: Sequence[Mapping[str, object]]) -> str:
    """The file whose managed block puts the secret in the environment, if this run wrote one."""

    for receipt in receipts:
        if receipt.get("module") in _SHELL_MODULES:
            path = receipt.get("path")
            if isinstance(path, str) and path:
                return path
    return ""


def _command_strings(value: object) -> Tuple[str, ...]:
    """Commands out of an untyped receipt field, narrowed once instead of at each reader."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        return ()
    return tuple(str(one) for one in value)


def _shell_files_of(receipts: Sequence[Mapping[str, object]]) -> Tuple[str, ...]:
    """Every distinct shell file this run put variables in, in the order it wrote them.

    Only the two `shell.env-*` modules qualify, because variables in a shell file are their whole
    purpose.  `file.managed-block@1` writes content this tool cannot read as exports, so it is
    left out rather than guessed at.
    """

    files: list[str] = []
    for receipt in receipts:
        if receipt.get("module") not in _SHELL_MODULES:
            continue
        path = receipt.get("path")
        if isinstance(path, str) and path and path not in files:
            files.append(path)
    return tuple(files)


def advisory_messages(record: SetupStateRecord) -> Tuple[Mapping[str, object], ...]:
    """Advisory findings a completed run recorded, in the shape every surface renders.

    The sibling of `recovery_messages`, and it exists for the same reason: a receipt field that no
    surface reads is a fact the run established and threw away.  `AD-34`'s warning was read by the
    JSON command path alone, so an operator who ran setup through the wizard — which is how it is
    normally run — saw nothing at all (`AD-36`).
    """

    shell_file = _shell_file_of(record.receipt)
    reload_shell = shell_reload_suffix(shell_file)
    messages: list[Mapping[str, object]] = []
    for receipt in record.receipt:
        detail = receipt.get("advisory")
        if not isinstance(detail, str) or not detail.strip():
            continue
        commands = list(_command_strings(receipt.get("remediation_commands")))
        if reload_shell:
            commands = [
                one if one.endswith(reload_shell) else one + reload_shell for one in commands
            ]
        messages.append({"detail": redact_text(detail.strip()), "commands": tuple(commands)})
    return tuple(messages)


def render_setup_advisories(
    advisories: Sequence[Mapping[str, object]],
    *,
    width: int = CONTENT_MEASURE,
    heading: str = "Warning",
) -> Tuple[str, ...]:
    """Print advisories last, because the operator reads the end of a run, not its middle.

    An advisory is not a failure: the run configured what it was asked to.  It is printed after
    everything else so that the command it carries is the last thing on screen, ready to copy.
    """

    lines: Tuple[str, ...] = ()
    for advisory in advisories:
        detail = str(advisory.get("detail", ""))
        commands = _command_strings(advisory.get("commands"))
        if not detail and not commands:
            continue
        lines += (heading,)
        if detail:
            lines += field_block((("what", detail),), indent=2, width=width)
        if commands:
            lines += ("  to replace what is stored: copy the token to the clipboard, then run:",)
            # Commands are never wrapped: a wrapped command is a command that cannot be copied.
            lines += tuple(f"    {command}" for command in commands)
            # The last step nobody remembers. A server inherits its environment once, at start, so
            # a corrected Keychain and a reloaded shell still leave it authenticating as nobody
            # until it is restarted (`AD-31`).
            lines += ("  then restart the agent harness, or the server keeps what it started with",)
    return lines


def _recovery_lines(item: str, *, width: int) -> Tuple[str, ...]:
    """Prose wrapped and indented; a command on its own line, printed whole.

    `wrap` collapses embedded newlines, which is right for prose and wrong for the one part of a
    recovery note the operator has to copy.  A command folded across three lines is repaired by
    hand before it can be run, and its continuation arrives with no indent at all (`AD-36`).
    """

    prose, _, command = item.partition("\n")
    lines = tuple(f"  {line}" for line in wrap(public_text(prose), width=width - 2))
    # Sanitised per segment rather than whole, because `public_text` flattens line breaks and
    # would erase the split before it could be read.  Each segment is still sanitised, and there
    # is still only one split: a recovery note is at most one sentence and one command.
    tail = public_text(command).strip()
    return lines + ((f"    {tail}",) if tail else ())


def shell_reload_reminder(record: SetupStateRecord) -> Tuple[Mapping[str, object], ...]:
    """The step a run cannot take for the operator, said once, at the end.

    A setup that writes variables into a shell file has changed nothing a shell already open can
    see, and no effect can fix that: a child process cannot alter its parent's environment, which
    is the same reason `cd` is not a program.  What it can do is stop the operator having to
    remember (`AD-37`).

    The file is not guessed.  It is the `path` of the receipt written by the step that put the
    variables there, so this holds for any recipe without the recipe saying anything.
    """

    return _reminders_for(_shell_files_of(record.receipt))


def _reminders_for(shell_files: Sequence[str]) -> Tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "file": display,
            "detail": (
                f"this run put variables in {display}, and a shell that is already open "
                "does not have them yet"
            ),
            "commands": (f"source {display}",),
            "alternative": "or open a new terminal window and start the agent harness from there",
        }
        for display in (home_relative(shell_file) for shell_file in shell_files)
    )


def run_reload_reminders(
    records: Sequence[Optional[SetupStateRecord]],
) -> Tuple[Mapping[str, object], ...]:
    """The same reminder, once for the run instead of once per artifact (`AD-39`).

    `_shell_files_of` already returns each distinct file once, in write order, so the whole fix
    is to hand it every receipt in the run rather than one item's.  Reloading a shell is a fact
    about the machine, not about an artifact: three servers writing to `~/.zshrc` need the
    command run once, and printing it three times is how the instruction stopped being read.
    """

    receipts: list[Mapping[str, object]] = []
    for record in records:
        if record is not None:
            receipts.extend(record.receipt)
    return _reminders_for(_shell_files_of(tuple(receipts)))


def render_setup_reminders(
    reminders: Sequence[Mapping[str, object]], *, width: int = CONTENT_MEASURE
) -> Tuple[str, ...]:
    """A next step is not a warning, so it does not borrow the word."""

    lines: Tuple[str, ...] = ()
    for reminder in reminders:
        detail = str(reminder.get("detail", ""))
        if not detail:
            continue
        lines += ("Next step",)
        lines += field_block((("what", detail),), indent=2, width=width)
        # Never wrapped, for the same reason as every other command this tool prints.
        lines += tuple(f"    {command}" for command in _command_strings(reminder.get("commands")))
        alternative = str(reminder.get("alternative", ""))
        if alternative:
            lines += tuple(f"  {line}" for line in wrap(alternative, width=width - 2))
    return lines


def render_recovery_notes(notes: Sequence[str], *, width: int = CONTENT_MEASURE) -> Tuple[str, ...]:
    """The `Recovery` block, written once so that both surfaces print the same thing.

    Each note is one sentence and, sometimes, one command, and the command is the part that must
    not be folded — `_recovery_lines` is what knows that. A second implementation on the other
    surface is a second place for the fold to come back (`AD-42`).
    """

    if not notes:
        return ()
    lines: Tuple[str, ...] = ("Recovery",)
    for note in notes:
        lines += _recovery_lines(note, width=width)
    return lines


def setup_retry_command(*, coordinate: str, profile: str, scope: str) -> str:
    """The one command that repeats exactly this item, written once for both surfaces.

    Both the wizard and the `--json` path print a retry, and a retry assembled twice is two
    commands that drift — the flags that authorize a setup queue are the whole difference between
    one that runs and one that refuses (`AD-36`).
    """

    return (
        f"aart marketplace setup {coordinate} --profile {profile} "
        f"--scope {scope} --yes --approve-setup-effects"
    )


SETUP_QUEUE_PROMPT = "Run setup? [Y/s/n]: "
"""The one question asked before a setup queue runs.  There is no second one by default."""

SETUP_EFFECT_PROMPT = "Approve this exact effect? [y/N]: "
"""Asked per step only after the operator asked to be asked.  See `setup_queue_choice`."""


def setup_queue_question(*, artifacts: int, steps: int) -> Tuple[str, ...]:
    """What is about to happen, in two lines, before the one question about it.

    The wizard used to print every step in full and then ask whether to finalize the queue, and
    then ask again about each step in turn.  That is a wall of text in front of someone who has
    already decided -- they chose to install the artifact -- and reading all of it was the price
    of answering any of it (`#113`).  The count is what a person needs to answer this question;
    the detail is one keystroke away for anyone who wants it.
    """

    step_word = "step" if steps == 1 else "steps"
    artifact_word = "artifact" if artifacts == 1 else "artifacts"
    return (
        f"Setup: {steps} {step_word} for {artifacts} {artifact_word}.",
        "Enter runs them. Type s to see and approve each step, or n to stop.",
    )


def setup_queue_choice(answer: Optional[str]) -> str:
    """Read the answer to `SETUP_QUEUE_PROMPT` as one of `run`, `show` or `stop`.

    `None` is not an empty line: it is no terminal at all, and a queue that installed itself
    because nobody was there to say otherwise is the one outcome this question must never have.
    An answer nobody planned for stops as well -- the queue is repeatable, and a typo that runs
    every step is worse than a typo that runs none.
    """

    if answer is None:
        return "stop"
    reply = answer.strip().casefold()
    if reply in ("", "y", "yes", "run"):
        return "run"
    if reply in ("s", "show", "v", "verbose"):
        return "show"
    return "stop"


_BANNER_MINIMUM_RULE = 6
"""Fewer dashes than this around a label is not a rule, so the banner changes shape instead."""


def setup_banner(
    *,
    phase: str,
    artifact: str = "",
    profile: str = "",
    scope: str = "",
    position: int = 0,
    total: int = 0,
    width: int = CONTENT_MEASURE,
) -> Tuple[str, ...]:
    """A rule that says which setup this is and whether it is opening or closing.

    A queue prints the same shapes for every item — effects, prompts, a `security` password
    request that names nothing — so without a boundary the run is one wall of text and the
    operator cannot tell whose credential is being asked for (`AD-40`).  The profile is part of
    the label rather than decoration: the queue is an artifacts x profiles product, so one MCP
    server selected for two harnesses is two items whose labels would otherwise be identical.
    The version is deliberately absent — a coordinate carries one, and two cannot be queued.
    """

    parts = []
    if artifact:
        subject = f"{artifact}@{profile}" if profile else artifact
        parts.append(f"{subject} ({scope})" if scope else subject)
    if total > 0:
        parts.append(f"setup {position}/{total}")
    parts.append(phase)
    label = f" {' — '.join(parts)} "
    bound = measure(width, bound=CONTENT_MEASURE)
    fill = bound - len(label)
    if fill >= _BANNER_MINIMUM_RULE:
        left = fill // 2
        return (f"{'-' * left}{label}{'-' * (fill - left)}",)
    # Too narrow to hold the label inside a rule. The words are the point and the rule is the
    # decoration, so the rule is what gives way; nothing here is ever truncated to fit. The
    # separator degrades with it, because a wrapped line ending in a dangling em dash reads as
    # damage rather than as a boundary.
    return wrap(", ".join(parts), width=bound) + ("-" * bound,)


def render_run_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    reminders: Sequence[Mapping[str, object]] = (),
    width: int = CONTENT_MEASURE,
) -> Tuple[str, ...]:
    """What the whole run did, once, after the per-item blocks that stay exactly as they were.

    Per-item output answers "what happened to this artifact".  It cannot answer "what happened
    to the run", and a queue of six prints six blocks in which the one that failed is somewhere
    in the middle.  Two facts are run-scoped rather than item-scoped and belong only here: the
    tally, and reloading a shell file, which is a property of the machine and was printed once
    per artifact before (`AD-39`).
    """

    if not rows:
        return ()
    total = len(rows)
    done = sum(1 for row in rows if bool(row.get("successful")))
    # The blank belongs to the block, not to the caller: two surfaces spacing it themselves is
    # two surfaces spacing it differently.
    lines: Tuple[str, ...] = ("",) + setup_banner(phase="RUN SUMMARY", width=width)
    lines += field_block(
        (("selected", str(total)), ("configured", str(done)), ("incomplete", str(total - done))),
        indent=2,
        width=width,
    )
    incomplete = tuple(row for row in rows if not bool(row.get("successful")))
    if incomplete:
        lines += ("Not configured",)
        for row in incomplete:
            heading = f"{row.get('artifact', '')}@{row.get('profile', '')} ({row.get('scope', '')})"
            lines += tuple(f"  {line}" for line in wrap(public_text(heading), width=width - 2))
            # Redacted here as well as in the per-item block. This summary repeats a detail that
            # was already printed once, and a repeat is a second chance to print a credential.
            lines += field_block(
                (
                    ("status", public_text(str(row.get("status", "")))),
                    ("why", public_text(redact_text(str(row.get("detail", ""))))),
                ),
                indent=4,
                width=width,
            )
            retry = public_text(redact_text(str(row.get("retry_command", ""))))
            if retry:
                # Never wrapped, for the same reason as every other command this tool prints.
                lines += (f"    {retry}",)
    lines += render_setup_reminders(reminders, width=width)
    return lines


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
    advisories: Sequence[Mapping[str, object]] = (),
    reminders: Sequence[Mapping[str, object]] = (),
    manual: SetupManualReference | None = None,
    position: int = 0,
    total: int = 0,
    width: int = CONTENT_MEASURE,
) -> Tuple[str, ...]:
    """Render one post-payload setup result as a bounded, redacted terminal record.

    The heading is a rule rather than a sentence so that it closes the item visibly.  A queue
    prints these back to back, and a line that reads like prose does not separate one artifact's
    output from the next one's (`AD-40`).
    """

    incomplete = status not in _SETUP_COMPLETE
    lines: Tuple[str, ...] = setup_banner(
        artifact=artifact,
        profile=profile,
        scope=scope,
        phase="SUMMARY",
        position=position,
        total=total,
        width=width,
    )
    lines += field_block(
        (("status", public_text(status)), ("details", public_text(redact_text(detail)))),
        indent=2,
        width=width,
    )
    # Commands are headed and then printed whole on their own line, never as an aligned value: a
    # field block wraps, and a folded command is pasted broken. This is the same fold `AD-34` and
    # `AD-35` were opened about, and the retry was still being printed through it.
    for label, command in (("retry", retry_command), ("rollback", rollback_command)):
        if command:
            lines += (f"  {label}", f"    {public_text(redact_text(command))}")
    lines += render_recovery_notes(recovery, width=width)
    lines += render_setup_advisories(advisories, width=width)
    lines += render_setup_reminders(reminders, width=width)
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
    """The command that runs this item's setup again.

    `aart setup` was one of the nine top-level commands removed in `2.0.0`; the canonical verb is
    `aart marketplace setup`, which re-runs the declared recipe for an installed artifact and is
    therefore the retry.  `--approve-setup-effects` is named because without it every reviewed
    effect is declined, and a retry that declines everything is not a retry.
    """

    coordinate = shlex.quote(f"{item.artifact_type}/{item.artifact_name}")
    return (
        f"aart marketplace setup {coordinate} --profile {shlex.quote(item.profile)} "
        f"--scope {item.scope} --yes --approve-setup-effects"
    )


def rollback_command(item: SetupQueueItem) -> str:
    """The command that reverses effects this item already applied.

    This used to say *no command reverses a completed setup*, and that was true when it was
    written: the engine reversed its own effects on a failed apply, and `rollback_setup` had no CLI
    surface.  `2.6.0` gave it one, and the sentence became a field that every new record carried
    and the same executable contradicted (`LAF-65`).

    It is a written field and not printed prose, which is why it went stale unnoticed: nothing
    reads a persisted record back and checks its claims against the command surface.  The test for
    this parses the string with the real CLI parser, so the next time the surface moves, this fails
    rather than lying.
    """

    return rollback_command_for(item.artifact_type, item.artifact_name, item.profile, item.scope)


def rollback_command_for(artifact_type: str, artifact_name: str, profile: str, scope: str) -> str:
    """The same command, composed from a persisted record's own coordinates.

    `LAF-73`: `verify` has to be able to say *this is the command that works* about a record
    written before `2.6.0`, and it has only the record to say it from.  Composing the string
    there as well would give the sentence two sources and one of them would go stale — which is
    the whole shape of `LAF-65`.  So there is one function, and both callers use it.
    """

    coordinate = shlex.quote(f"{artifact_type}/{artifact_name}")
    return (
        f"aart marketplace receipt undo {coordinate} --profile {shlex.quote(profile)} "
        f"--scope {scope} --yes"
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
    if effect.module in (
        "shell.env-from-keychain@1",
        "shell.env-from-input@1",
        "file.managed-block@1",
    ):
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
    if effect.module == "docker.build@1":
        return receipt.get("tag") == effect.target
    if effect.module == "trust-store.export-certificates@1":
        return receipt.get("output") == effect.config.get("output")
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
