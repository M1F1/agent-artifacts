"""Imperative adapters and one-item setup transaction runtime (issue #20)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Sequence

from .io import fs
from .model import SetupEffect, SetupPlan, SetupStateRecord
from .setup import (
    _freeze,
    managed_block,
    redact_text,
    retry_command,
    rollback_command,
    rollback_managed_block,
)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


ProcessRunner = Callable[..., ProcessResult]
Consent = Callable[[SetupEffect], bool]
ToolLookup = Callable[[str], bool]


class RollbackIncompleteError(RuntimeError):
    """An effect may have mutated state and could not prove compensation."""

    def __init__(self, message: str, *, receipt: Optional[Mapping[str, object]] = None):
        super().__init__(message)
        self.receipt = receipt


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_process(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Optional[str],
    timeout: int,
    capture: bool,
) -> ProcessResult:
    """Run a fixed argv without a shell or broad inherited environment."""

    completed = subprocess.run(
        tuple(argv),
        shell=False,
        check=False,
        env=dict(env),
        cwd=cwd,
        timeout=timeout,
        text=True,
        capture_output=capture,
    )
    return ProcessResult(
        completed.returncode,
        (completed.stdout or "")[:4096] if capture else "",
        (completed.stderr or "")[:4096] if capture else "",
    )


def _actual_tool_exists(tool: str) -> bool:
    if os.path.isabs(tool):
        return os.path.isfile(tool) and os.access(tool, os.X_OK)
    return shutil.which(tool) is not None


@dataclass(frozen=True, slots=True)
class SetupRuntime:
    process: ProcessRunner = run_process
    platform: str = sys.platform
    environ: Mapping[str, str] = None  # type: ignore[assignment]
    tool_exists: ToolLookup = lambda _tool: True
    clock: Callable[[], str] = _now
    enforce_source_hash: bool = False

    def __post_init__(self) -> None:
        if self.environ is None:
            object.__setattr__(self, "environ", {})


def production_runtime() -> SetupRuntime:
    return SetupRuntime(
        process=run_process,
        platform=sys.platform,
        environ=os.environ,
        tool_exists=_actual_tool_exists,
        enforce_source_hash=True,
    )


def _minimal_env(runtime: SetupRuntime) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM")
    env = {name: runtime.environ[name] for name in allowed if name in runtime.environ}
    env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    return env


def _write_preserving_mode(path: str, content: str, previous_mode: Optional[int]) -> None:
    fs.write_atomic(path, content.encode("utf-8"))
    os.chmod(path, previous_mode if previous_mode is not None else 0o600)


def _read_regular_text(path: str) -> tuple[str, bool, Optional[int]]:
    if os.path.islink(path):
        raise RuntimeError(f"refusing to edit symlink: {path}")
    if not os.path.exists(path):
        return "", False, None
    if not os.path.isfile(path):
        raise RuntimeError(f"managed target is not a regular file: {path}")
    mode = stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)
    return fs.read_text(path), True, mode


def _keychain_receipt(
    module: str,
    service: str,
    account: str,
    *,
    created: bool,
    replaced: bool,
) -> dict:
    return {
        "module": module,
        "created": created,
        "replaced": replaced,
        "service": service,
        "account": account,
        "recovery": (
            "Re-enter the prior Keychain value with /usr/bin/security "
            f"add-generic-password -U -a {account!r} -s {service!r} -w."
            if replaced
            else ""
        ),
    }


def _keychain_apply(effect: SetupEffect, runtime: SetupRuntime) -> tuple[dict, bool]:
    service = str(effect.config["service"])
    account = str(effect.config["account"])
    env = _minimal_env(runtime)
    find_argv = (
        "/usr/bin/security",
        "find-generic-password",
        "-a",
        account,
        "-s",
        service,
    )
    exists = runtime.process(find_argv, env=env, cwd=None, timeout=30, capture=True).returncode == 0
    replace_existing = bool(effect.config.get("replace_existing", False))
    if exists and not replace_existing:
        return _keychain_receipt(
            effect.module, service, account, created=False, replaced=False
        ), False
    result = runtime.process(effect.argv, env=env, cwd=None, timeout=120, capture=False)
    if result.returncode != 0:
        if replace_existing:
            raise RollbackIncompleteError(
                "Keychain replacement failed and the prior value cannot be restored automatically",
                receipt=_keychain_receipt(
                    effect.module, service, account, created=False, replaced=True
                ),
            )
        appeared = (
            runtime.process(find_argv, env=env, cwd=None, timeout=30, capture=True).returncode == 0
        )
        if appeared:
            deleted = runtime.process(
                (
                    "/usr/bin/security",
                    "delete-generic-password",
                    "-a",
                    account,
                    "-s",
                    service,
                ),
                env=env,
                cwd=None,
                timeout=30,
                capture=True,
            )
            if deleted.returncode != 0:
                raise RollbackIncompleteError(
                    "Keychain add failed after creating an item and cleanup was incomplete",
                    receipt=_keychain_receipt(
                        effect.module, service, account, created=True, replaced=False
                    ),
                )
        raise RuntimeError("security add-generic-password failed")
    verify = runtime.process(find_argv, env=env, cwd=None, timeout=30, capture=True)
    if verify.returncode != 0:
        if replace_existing:
            raise RollbackIncompleteError(
                "Keychain replacement could not be verified and is not automatically reversible",
                receipt=_keychain_receipt(
                    effect.module, service, account, created=False, replaced=True
                ),
            )
        deleted = runtime.process(
            (
                "/usr/bin/security",
                "delete-generic-password",
                "-a",
                account,
                "-s",
                service,
            ),
            env=env,
            cwd=None,
            timeout=30,
            capture=True,
        )
        if deleted.returncode != 0:
            raise RollbackIncompleteError(
                "Keychain item verification failed and cleanup was incomplete",
                receipt=_keychain_receipt(
                    effect.module, service, account, created=True, replaced=False
                ),
            )
        raise RuntimeError("Keychain item was not found after add")
    return _keychain_receipt(
        effect.module,
        service,
        account,
        created=not exists,
        replaced=exists,
    ), True


def _managed_block_apply(effect: SetupEffect) -> tuple[dict, bool]:
    existing, existed, mode = _read_regular_text(effect.target)
    marker = str(effect.config["marker"])
    content = str(effect.config["content"])
    updated, changed, prior = managed_block(existing, marker, content)
    if not changed:
        return {
            "module": effect.module,
            "path": effect.target,
            "marker": marker,
            "changed": False,
        }, False
    _write_preserving_mode(effect.target, updated, mode)
    _updated, _changed, installed = managed_block("", marker, content)
    assert installed is None
    start = f"# >>> aart setup: {marker} >>>"
    end = f"# <<< aart setup: {marker} <<<"
    installed_block = f"{start}\n{content.rstrip()}\n{end}"
    return {
        "module": effect.module,
        "path": effect.target,
        "marker": marker,
        "changed": True,
        "file_existed": existed,
        "mode": mode,
        "prior_block": prior,
        "installed_block": installed_block,
    }, True


def _json_apply(effect: SetupEffect) -> tuple[dict, bool]:
    existing, existed, mode = _read_regular_text(effect.target)
    try:
        root = json.loads(existing) if existing.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON target {effect.target}: {exc}") from exc
    if not isinstance(root, dict):
        raise RuntimeError(f"JSON target must contain an object: {effect.target}")
    raw_path = effect.config["path"]
    assert isinstance(raw_path, tuple)
    path = tuple(str(part) for part in raw_path)
    cursor = root
    for part in path[:-1]:
        child = cursor.get(part)
        if child is None:
            child = {}
            cursor[part] = child
        if not isinstance(child, dict):
            raise RuntimeError(f"JSON path collision at {part!r}")
        cursor = child
    leaf = path[-1]
    had_prior = leaf in cursor
    prior = cursor.get(leaf)
    value = _json_value(effect.config["value"])
    if had_prior and prior == value:
        return {"module": effect.module, "path": effect.target, "changed": False}, False
    replace_existing = bool(effect.config.get("replace_existing", False))
    if had_prior and not replace_existing:
        raise RuntimeError(f"JSON path collision at {'.'.join(path)!r}")
    cursor[leaf] = value
    rendered = json.dumps(root, indent=2, sort_keys=False) + "\n"
    _write_preserving_mode(effect.target, rendered, mode)
    return {
        "module": effect.module,
        "path": effect.target,
        "json_path": list(path),
        "changed": True,
        "file_existed": existed,
        "mode": mode,
        "had_prior": had_prior,
        "replaced": had_prior,
        "installed": value,
        "reversible": not had_prior,
        "recovery": (
            f"Restore the prior value manually at {effect.target} JSON path {'.'.join(path)}."
            if had_prior
            else ""
        ),
    }, True


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _directory_apply(effect: SetupEffect) -> tuple[dict, bool]:
    if os.path.exists(effect.target):
        if not os.path.isdir(effect.target) or os.path.islink(effect.target):
            raise RuntimeError(f"directory target is not a regular directory: {effect.target}")
        return {"module": effect.module, "path": effect.target, "created": False}, False
    os.makedirs(effect.target, mode=0o700)
    return {"module": effect.module, "path": effect.target, "created": True}, True


def _docker_apply(effect: SetupEffect, runtime: SetupRuntime) -> tuple[dict, bool]:
    env = _minimal_env(runtime)
    inspect = runtime.process(
        ("docker", "image", "inspect", effect.target),
        env=env,
        cwd=None,
        timeout=30,
        capture=True,
    )
    if inspect.returncode == 0:
        return {"module": effect.module, "image": effect.target, "preexisting": True}, False
    pulled = runtime.process(effect.argv, env=env, cwd=None, timeout=300, capture=True)
    if pulled.returncode != 0:
        raise RuntimeError("docker pull failed")
    return {
        "module": effect.module,
        "image": effect.target,
        "preexisting": False,
        "recovery": "Image may be shared; remove it manually only after checking other users.",
    }, True


def _command_verify(effect: SetupEffect, runtime: SetupRuntime) -> tuple[dict, bool]:
    cwd = effect.config.get("cwd")
    raw_timeout = effect.config.get("timeout", 30)
    timeout = raw_timeout if isinstance(raw_timeout, int) else 30
    result = runtime.process(
        effect.argv,
        env=_minimal_env(runtime),
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        capture=True,
    )
    if result.returncode != 0:
        detail = redact_text(result.stderr or result.stdout or "verification command failed")
        raise RuntimeError(detail[:512])
    return {"module": effect.module, "verified": True}, False


def _file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_custom_entrypoint(path: str, expected_hash: object) -> bytes:
    """Read one executable without following links and bind the bytes before copying."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not bool(info.st_mode & 0o111):
            raise RuntimeError("custom setup entrypoint must be an executable regular file")
        chunks = []
        remaining = 1024 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(content) > 1024 * 1024:
        raise RuntimeError("custom setup entrypoint exceeds immutable copy limit")
    if not isinstance(expected_hash, str) or hashlib.sha256(content).hexdigest() != expected_hash:
        raise RuntimeError("custom setup entrypoint hash changed before immutable run copy")
    return content


def _validate_custom_result(path: str, expected: str) -> dict:
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError("custom setup did not create a regular result file")
    try:
        raw = json.loads(fs.read_text(path))
        if not isinstance(raw, dict):
            raise RuntimeError("custom setup result must be an object")
        allowed = {"status", "detail", "reversible", "recovery"}
        if set(raw) - allowed:
            raise RuntimeError("custom setup result contains undeclared fields")
        if raw.get("status") != expected:
            raise RuntimeError(f"custom setup result must report status {expected!r}")
        detail = raw.get("detail", "")
        recovery = raw.get("recovery", "")
        if not isinstance(detail, str) or not isinstance(recovery, str):
            raise RuntimeError("custom setup detail/recovery must be strings")
        if redact_text(detail) != detail or redact_text(recovery) != recovery:
            raise RuntimeError("custom setup result contains secret-shaped content")
        if not isinstance(raw.get("reversible", False), bool):
            raise RuntimeError("custom setup reversible must be a boolean")
        return {
            "status": expected,
            "detail": detail[:512],
            "reversible": bool(raw.get("reversible", False)),
            "recovery": recovery[:512],
        }
    except json.JSONDecodeError as exc:
        try:
            os.unlink(path)
        except (OSError, RuntimeError):
            pass
        raise RuntimeError(f"invalid custom setup result: {exc}") from exc
    except RuntimeError:
        try:
            os.unlink(path)
        except (OSError, RuntimeError):
            pass
        raise


def _custom_phase(
    effect: SetupEffect,
    runtime: SetupRuntime,
    *,
    phase: str,
    plan_hash: str,
    run_dir: str,
    receipt_path: Optional[str] = None,
) -> dict:
    script = effect.target
    if os.path.islink(script) or not os.path.isfile(script) or not os.access(script, os.X_OK):
        raise RuntimeError("custom setup entrypoint must remain an executable regular file")
    if _file_hash(script) != effect.config["script_hash"]:
        raise RuntimeError("custom setup script hash changed after review")
    result_path = os.path.join(run_dir, f"{phase}-result.json")
    argv = [script, phase]
    expected = phase
    if phase == "plan":
        argv.append("--json")
        expected = "planned"
    elif phase == "apply":
        argv.extend(("--plan-hash", plan_hash))
        expected = "configured"
    elif phase == "verify":
        argv.append("--json")
        expected = "verified"
    elif phase == "rollback":
        if receipt_path is None:
            raise RuntimeError("custom rollback requires a receipt")
        argv.extend(("--receipt", receipt_path))
        expected = "rolled_back"
    argv.extend(("--result", result_path))
    env = _minimal_env(runtime)
    env.update(
        {
            "AART_SETUP_PLAN_HASH": plan_hash,
            "AART_SETUP_RUN_DIR": run_dir,
            "AART_SETUP_ARTIFACT": str(effect.config.get("artifact", "")),
            "AART_SETUP_PROFILE": str(effect.config.get("profile", "")),
            "AART_SETUP_SCOPE": str(effect.config.get("scope", "")),
            "AART_SETUP_SOURCE": str(effect.config.get("source_label", "")),
            "AART_SETUP_INSTALLER_HASH": str(effect.config.get("descriptor_hash", "")),
        }
    )
    result = runtime.process(tuple(argv), env=env, cwd=run_dir, timeout=120, capture=True)
    if result.returncode != 0:
        raise RuntimeError(f"custom setup {phase} failed")
    return _validate_custom_result(result_path, expected)


def _custom_receipt(
    effect: SetupEffect,
    plan: SetupPlan,
    run_dir: str,
    applied: Mapping[str, object],
    *,
    script_source: str,
) -> dict:
    return {
        "module": effect.module,
        "script": effect.target,
        "script_source": script_source,
        "script_hash": effect.config["script_hash"],
        "run_dir": run_dir,
        "plan_hash": plan.plan_hash,
        "applied": applied,
        "reversible": bool(applied.get("reversible", True)),
        "recovery": "Retry the validated custom rollback with aart setup rollback.",
    }


def _custom_apply(effect: SetupEffect, runtime: SetupRuntime, plan: SetupPlan) -> tuple[dict, bool]:
    runs_root = os.path.join(
        plan.run_root,
        ".agent-artifacts",
        "setup-runs",
    )
    os.makedirs(runs_root, mode=0o700, exist_ok=True)
    os.chmod(runs_root, 0o700)
    run_dir = tempfile.mkdtemp(prefix=f"{plan.plan_hash[:16]}-", dir=runs_root)
    os.chmod(run_dir, 0o700)
    source_script = effect.target
    try:
        content = _read_custom_entrypoint(source_script, effect.config["script_hash"])
    except (OSError, RuntimeError):
        shutil.rmtree(run_dir)
        raise
    copied_script = os.path.join(run_dir, os.path.basename(source_script))
    try:
        fs.write_atomic(copied_script, content)
        os.chmod(copied_script, 0o700)
    except (OSError, RuntimeError):
        shutil.rmtree(run_dir)
        raise
    run_effect = replace(
        effect,
        target=copied_script,
        argv=(copied_script,),
    )
    before = set(os.listdir(run_dir))
    planned = _custom_phase(
        run_effect,
        runtime,
        phase="plan",
        plan_hash=plan.plan_hash,
        run_dir=run_dir,
    )
    after_plan = set(os.listdir(run_dir))
    allowed_plan_files = before | {"plan-result.json"}
    if after_plan != allowed_plan_files:
        shutil.rmtree(run_dir)
        raise RuntimeError("custom plan mutated the controlled run directory")
    try:
        applied = _custom_phase(
            run_effect,
            runtime,
            phase="apply",
            plan_hash=plan.plan_hash,
            run_dir=run_dir,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        receipt_path = os.path.join(run_dir, "custom-receipt.json")
        partial_receipt = _custom_receipt(
            run_effect, plan, run_dir, {}, script_source=source_script
        )
        fs.write_atomic(
            receipt_path,
            json.dumps({"plan_hash": plan.plan_hash, "apply": {}}).encode("utf-8"),
        )
        try:
            _custom_phase(
                run_effect,
                runtime,
                phase="rollback",
                plan_hash=plan.plan_hash,
                run_dir=run_dir,
                receipt_path=receipt_path,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_exc:
            raise RollbackIncompleteError(
                "custom apply failed and rollback was incomplete",
                receipt=partial_receipt,
            ) from rollback_exc
        raise exc
    if set(os.listdir(run_dir)) != after_plan | {"apply-result.json"}:
        receipt_path = os.path.join(run_dir, "custom-receipt.json")
        partial_receipt = _custom_receipt(
            run_effect, plan, run_dir, applied, script_source=source_script
        )
        fs.write_atomic(
            receipt_path,
            json.dumps({"plan_hash": plan.plan_hash, "apply": applied}).encode("utf-8"),
        )
        try:
            _custom_phase(
                run_effect,
                runtime,
                phase="rollback",
                plan_hash=plan.plan_hash,
                run_dir=run_dir,
                receipt_path=receipt_path,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_exc:
            raise RollbackIncompleteError(
                "custom apply violated its run directory and rollback was incomplete",
                receipt=partial_receipt,
            ) from rollback_exc
        shutil.rmtree(run_dir)
        raise RuntimeError("custom apply mutated the controlled run directory")
    try:
        verified = _custom_phase(
            run_effect,
            runtime,
            phase="verify",
            plan_hash=plan.plan_hash,
            run_dir=run_dir,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        receipt_path = os.path.join(run_dir, "custom-receipt.json")
        partial_receipt = _custom_receipt(
            run_effect, plan, run_dir, applied, script_source=source_script
        )
        fs.write_atomic(
            receipt_path,
            json.dumps({"plan_hash": plan.plan_hash, "apply": applied}).encode("utf-8"),
        )
        try:
            _custom_phase(
                run_effect,
                runtime,
                phase="rollback",
                plan_hash=plan.plan_hash,
                run_dir=run_dir,
                receipt_path=receipt_path,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_exc:
            raise RollbackIncompleteError(
                "custom verification failed and rollback was incomplete",
                receipt=partial_receipt,
            ) from rollback_exc
        raise exc
    expected_files = after_plan | {"apply-result.json", "verify-result.json"}
    if set(os.listdir(run_dir)) != expected_files:
        receipt_path = os.path.join(run_dir, "custom-receipt.json")
        partial_receipt = _custom_receipt(
            run_effect, plan, run_dir, applied, script_source=source_script
        )
        fs.write_atomic(
            receipt_path,
            json.dumps({"plan_hash": plan.plan_hash, "apply": applied}).encode("utf-8"),
        )
        try:
            _custom_phase(
                run_effect,
                runtime,
                phase="rollback",
                plan_hash=plan.plan_hash,
                run_dir=run_dir,
                receipt_path=receipt_path,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_exc:
            raise RollbackIncompleteError(
                "custom verification violated its run directory and rollback was incomplete",
                receipt=partial_receipt,
            ) from rollback_exc
        shutil.rmtree(run_dir)
        raise RuntimeError("custom verify mutated the controlled run directory")
    return _custom_receipt(
        run_effect,
        plan,
        run_dir,
        applied,
        script_source=source_script,
    ) | {
        "planned": planned,
        "verified": verified,
    }, True


def _apply_effect(effect: SetupEffect, runtime: SetupRuntime, plan: SetupPlan) -> tuple[dict, bool]:
    if effect.module == "macos-keychain.store@1":
        return _keychain_apply(effect, runtime)
    if effect.module in ("shell.env-from-keychain@1", "file.managed-block@1"):
        return _managed_block_apply(effect)
    if effect.module == "json.managed-merge@1":
        return _json_apply(effect)
    if effect.module == "directory.create@1":
        return _directory_apply(effect)
    if effect.module == "docker.pull@1":
        return _docker_apply(effect, runtime)
    if effect.module == "command.verify@1":
        return _command_verify(effect, runtime)
    if effect.module == "restart.notice@1":
        return {"module": effect.module, "message": effect.summary}, False
    if effect.module == "custom.install@1":
        return _custom_apply(effect, runtime, plan)
    raise RuntimeError(f"unsupported runtime module: {effect.module}")


def _rollback_receipt(receipt: Mapping[str, object], runtime: SetupRuntime) -> bool:
    module = receipt.get("module")
    if module == "macos-keychain.store@1" and receipt.get("replaced") is True:
        return False
    if module == "macos-keychain.store@1" and receipt.get("created") is True:
        result = runtime.process(
            (
                "/usr/bin/security",
                "delete-generic-password",
                "-a",
                str(receipt["account"]),
                "-s",
                str(receipt["service"]),
            ),
            env=_minimal_env(runtime),
            cwd=None,
            timeout=30,
            capture=True,
        )
        return result.returncode == 0
    if module in ("shell.env-from-keychain@1", "file.managed-block@1") and receipt.get("changed"):
        path = str(receipt["path"])
        try:
            current, _existed, _mode = _read_regular_text(path)
            rolled = rollback_managed_block(
                current,
                str(receipt["marker"]),
                str(receipt["installed_block"]),
                str(receipt["prior_block"]) if receipt.get("prior_block") is not None else None,
            )
            if rolled is None:
                return False
            if not rolled and receipt.get("file_existed") is False:
                os.unlink(path)
            else:
                _write_preserving_mode(path, rolled, receipt.get("mode"))  # type: ignore[arg-type]
            return True
        except (OSError, RuntimeError):
            return False
    if module == "directory.create@1" and receipt.get("created") is True:
        try:
            os.rmdir(str(receipt["path"]))
            return True
        except OSError:
            return False
    if module == "json.managed-merge@1" and receipt.get("changed") is True:
        if receipt.get("replaced") is True:
            return False
        path = str(receipt["path"])
        try:
            current, _existed, _mode = _read_regular_text(path)
            root = json.loads(current)
            if not isinstance(root, dict):
                return False
            json_path = receipt.get("json_path")
            if not isinstance(json_path, (list, tuple)) or not json_path:
                return False
            cursor = root
            for part in json_path[:-1]:
                child = cursor.get(str(part))
                if not isinstance(child, dict):
                    return False
                cursor = child
            leaf = str(json_path[-1])
            if cursor.get(leaf) != receipt.get("installed"):
                return False
            cursor.pop(leaf, None)
            rendered = json.dumps(root, indent=2, sort_keys=False) + "\n"
            if not root and receipt.get("file_existed") is False:
                os.unlink(path)
            else:
                _write_preserving_mode(path, rendered, receipt.get("mode"))  # type: ignore[arg-type]
            return True
        except (OSError, RuntimeError, json.JSONDecodeError):
            return False
    if module == "custom.install@1" and receipt.get("reversible") is True:
        script = str(receipt["script"])
        run_dir = str(receipt["run_dir"])
        receipt_path = os.path.join(run_dir, "custom-receipt.json")
        try:
            fs.write_atomic(
                receipt_path,
                json.dumps(
                    {
                        "plan_hash": receipt["plan_hash"],
                        "apply": _json_value(receipt.get("applied", {})),
                    }
                ).encode("utf-8"),
            )
            effect = SetupEffect(
                step_id="custom",
                module="custom.install@1",
                capability="custom-code",
                summary="custom rollback",
                target=script,
                config={"script_hash": receipt["script_hash"]},
            )
            _custom_phase(
                effect,
                runtime,
                phase="rollback",
                plan_hash=str(receipt["plan_hash"]),
                run_dir=run_dir,
                receipt_path=receipt_path,
            )
            return True
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return False
    if module == "custom.install@1":
        return False
    if module == "docker.pull@1":
        return receipt.get("preexisting") is True
    # Docker images may be shared and are never removed automatically; verify/notices mutate
    # nothing. Other changed modules are handled above with ownership-aware compensation.
    return module in ("restart.notice@1", "command.verify@1") or not bool(
        receipt.get("changed", False)
    )


def _record(
    plan: SetupPlan,
    status: str,
    detail: str,
    *,
    started: str,
    finished: str,
    receipts: Sequence[Mapping[str, object]] = (),
    exit_status: Optional[int] = None,
) -> SetupStateRecord:
    item = plan.item
    retry = "" if status in ("configured", "already_configured") else retry_command(item)
    rollback = rollback_command(item) if receipts else ""
    frozen_receipts = []
    for receipt in receipts:
        frozen = _freeze(receipt)
        assert isinstance(frozen, Mapping)
        frozen_receipts.append(frozen)
    return SetupStateRecord(
        artifact_type=item.artifact_type,
        artifact_name=item.artifact_name,
        profile=item.profile,
        scope=item.scope,
        status=status,  # type: ignore[arg-type]
        detail=redact_text(detail),
        source_label=item.source_label,
        installer_path=item.installer.descriptor_path,
        installer_hash=item.installer.descriptor_hash,
        custom_hash=item.installer.custom_hash or "",
        schema_version=item.installer.schema_version,
        protocol_version=item.installer.protocol_version,
        plan_hash=plan.plan_hash,
        started_at=started,
        finished_at=finished,
        exit_status=exit_status,
        retry_command=retry,
        rollback_command=rollback,
        receipt=tuple(frozen_receipts),
    )


def _rollback_all(receipts: Sequence[Mapping[str, object]], runtime: SetupRuntime) -> bool:
    """Attempt every compensation in reverse order, even after one rollback fails."""

    complete = True
    for receipt in reversed(receipts):
        try:
            rolled_back = _rollback_receipt(receipt, runtime)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            rolled_back = False
        if not rolled_back:
            complete = False
    return complete


def apply_setup_plan(
    plan: SetupPlan, runtime: SetupRuntime, *, consent: Consent
) -> SetupStateRecord:
    """Review-bound sequential transaction for one queue item."""

    started = runtime.clock()
    if runtime.enforce_source_hash:
        descriptor = os.path.join(
            plan.item.source_root,
            plan.item.installer.descriptor_path,
        )
        try:
            descriptor_matches = (
                not os.path.islink(descriptor)
                and os.path.isfile(descriptor)
                and _file_hash(descriptor) == plan.item.installer.descriptor_hash
            )
        except OSError:
            descriptor_matches = False
        if not descriptor_matches:
            return _record(
                plan,
                "apply_failed_rolled_back",
                "setup installer hash changed after review",
                started=started,
                finished=runtime.clock(),
                exit_status=1,
            )
    if plan.preflight_status is not None:
        return _record(
            plan,
            plan.preflight_status,
            plan.preflight_detail,
            started=started,
            finished=runtime.clock(),
        )
    if runtime.platform not in plan.item.installer.platforms:
        return _record(
            plan,
            "unsupported",
            f"current platform {runtime.platform} is unsupported",
            started=started,
            finished=runtime.clock(),
        )
    missing = tuple(
        tool for tool in plan.item.installer.required_tools if not runtime.tool_exists(tool)
    )
    if missing:
        return _record(
            plan,
            "prerequisite_missing",
            f"missing required tool(s): {', '.join(missing)}",
            started=started,
            finished=runtime.clock(),
        )
    receipts: list[Mapping[str, object]] = []
    changed = False
    for effect in plan.effects:
        try:
            approved = consent(effect)
        except (EOFError, KeyboardInterrupt):
            approved = False
        if not approved:
            rolled_back = _rollback_all(receipts, runtime)
            status = "cancelled" if rolled_back else "rollback_incomplete"
            return _record(
                plan,
                status,
                "Setup cancelled before applying the next reviewed effect",
                started=started,
                finished=runtime.clock(),
                receipts=() if rolled_back else receipts,
            )
        try:
            receipt, effect_changed = _apply_effect(effect, runtime, plan)
            receipt = {"step_id": effect.step_id, **receipt}
            receipts.append(receipt)
            changed = changed or effect_changed
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            if isinstance(exc, RollbackIncompleteError) and exc.receipt is not None:
                receipts.append({"step_id": effect.step_id, **exc.receipt})
            rolled_back = _rollback_all(receipts, runtime)
            uncompensated = isinstance(exc, RollbackIncompleteError) and exc.receipt is None
            status = (
                "apply_failed_rolled_back"
                if rolled_back and not uncompensated
                else "rollback_incomplete"
            )
            if effect.module == "command.verify@1" and rolled_back:
                status = "verification_failed"
            detail = redact_text(str(exc))
            if (
                rolled_back
                and effect.module == "custom.install@1"
                and isinstance(exc, RollbackIncompleteError)
                and exc.receipt is not None
            ):
                detail = "custom setup failed; rollback completed after retry"
            return _record(
                plan,
                status,
                detail,
                started=started,
                finished=runtime.clock(),
                receipts=() if rolled_back else receipts,
                exit_status=1,
            )
    status = "configured" if changed else "already_configured"
    return _record(
        plan,
        status,
        "Setup configured" if changed else "Setup was already configured",
        started=started,
        finished=runtime.clock(),
        receipts=receipts if changed else (),
        exit_status=0,
    )


def rollback_record(record: SetupStateRecord, runtime: SetupRuntime) -> SetupStateRecord:
    """Rollback one persisted receipt in reverse order, respecting ownership checks."""

    ok = _rollback_all(record.receipt, runtime)
    return SetupStateRecord(
        artifact_type=record.artifact_type,
        artifact_name=record.artifact_name,
        profile=record.profile,
        scope=record.scope,
        status="skipped" if ok else "rollback_incomplete",
        detail="Setup rollback completed" if ok else "Setup rollback was incomplete",
        source_label=record.source_label,
        installer_path=record.installer_path,
        installer_hash=record.installer_hash,
        custom_hash=record.custom_hash,
        schema_version=record.schema_version,
        protocol_version=record.protocol_version,
        plan_hash=record.plan_hash,
        started_at=record.started_at,
        finished_at=runtime.clock(),
        exit_status=0 if ok else 1,
        retry_command=record.retry_command,
        rollback_command="" if ok else record.rollback_command,
        receipt_path=record.receipt_path,
        receipt=() if ok else record.receipt,
        object_digest=record.object_digest,
        recipe_digest=record.recipe_digest,
        trust=record.trust,
        trust_evidence_digest=record.trust_evidence_digest,
        policy_digest=record.policy_digest,
        capability_plan_digest=record.capability_plan_digest,
        canonical_review_digest=record.canonical_review_digest,
        setup_state_ref=record.setup_state_ref,
    )
