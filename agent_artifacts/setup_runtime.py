"""Imperative adapters and one-item setup transaction runtime (issue #20)."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
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
    shell_reload_suffix,
)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


ProcessRunner = Callable[..., ProcessResult]
Consent = Callable[[SetupEffect], bool]
ToolLookup = Callable[[str], bool]
PromptWriter = Callable[[str], None]
TextInputReader = Callable[[str], str]
SecretLengthProbe = Callable[[str, str], Optional[int]]


class RollbackIncompleteError(RuntimeError):
    """An effect may have mutated state and could not prove compensation."""

    def __init__(self, message: str, *, receipt: Optional[Mapping[str, object]] = None):
        super().__init__(message)
        self.receipt = receipt


_DETAIL_LIMIT = 512
_DETAIL_HEAD = 128


def failure_detail(raw: str, *, limit: int = _DETAIL_LIMIT) -> str:
    """Redact, then keep the end of a failure transcript rather than its beginning.

    `docker build` prints progress first and the failing instruction last, so a head-truncated
    detail is exactly the half that cannot explain the failure — a consumer was shown
    `transferring dockerfile: 117B done` and never `did not complete successfully: exit code: 3`
    (`LAF-59`).  Both ends can carry meaning, so the head is kept too and the middle is elided.

    Redaction happens here rather than at the call site so the two steps cannot be ordered the
    wrong way round by a caller: truncating first could cut a secret in half and leave the half
    that the redaction pattern no longer matches.
    """

    text = redact_text(raw)
    if len(text) <= limit:
        return text
    head = text[:_DETAIL_HEAD]
    marker = f"\n… {len(text) - limit} characters elided …\n"
    tail_budget = limit - len(head) - len(marker)
    if tail_budget <= 0:
        return text[-limit:]
    return f"{head}{marker}{text[-tail_budget:]}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_process(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Optional[str],
    timeout: int,
    capture: bool,
    stdout_path: Optional[str] = None,
) -> ProcessResult:
    """Run a fixed argv without a shell or broad inherited environment.

    Captured output is truncated because it exists to be shown to a person.  A tool whose output is
    *data* — a certificate bundle is the only one today — writes to `stdout_path` instead, so the
    bytes go to the file they were asked for and never through a field sized for a message.
    """

    if stdout_path is not None:
        with open(stdout_path, "wb") as sink:
            completed = subprocess.run(
                tuple(argv),
                shell=False,
                check=False,
                env=dict(env),
                cwd=cwd,
                timeout=timeout,
                text=True,
                stdout=sink,
                stderr=subprocess.PIPE,
            )
        return ProcessResult(completed.returncode, "", (completed.stderr or "")[:4096])
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


# `security` reads its prompt through `getpass(3)`, whose static buffer is `_PASSWORD_LEN` in
# `pwd.h` — 128 bytes, "max length, not counting NULL".  A longer secret is discarded past that
# point with no error and no exit status, and because the tool prompts twice and compares, two
# identically truncated pastes agree with each other.  An Atlassian API token is 193 bytes, so this
# path cannot carry one at all (`AD-34`).
_PROMPT_CEILING = 128


_PROBE_TIMEOUT = 30


def _piped_count(
    producer: tuple[str, ...],
    counter: tuple[str, ...],
    *,
    from_stderr: bool = False,
    counter_ok: tuple[int, ...] = (0,),
) -> Optional[int]:
    """Run ``producer | counter`` and read only the number the counter prints.

    What the producer writes reaches the counting child and never this process.  Reading it here
    to measure it would put the secret into AART's own memory, which is the single property the
    Keychain step exists to preserve.
    """

    streams = {
        "stdout": subprocess.DEVNULL if from_stderr else subprocess.PIPE,
        "stderr": subprocess.PIPE if from_stderr else subprocess.DEVNULL,
    }
    try:
        source = subprocess.Popen(producer, **streams)  # type: ignore[call-overload]
    except OSError:
        return None
    pipe = source.stderr if from_stderr else source.stdout
    assert pipe is not None
    try:
        sink = subprocess.Popen(
            counter, stdin=pipe, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
    except OSError:
        pipe.close()
        source.kill()
        source.wait(timeout=_PROBE_TIMEOUT)
        return None
    # Only the counting child may hold the read end, or the pipe never reaches EOF.
    pipe.close()
    try:
        digits, _ignored = sink.communicate(timeout=_PROBE_TIMEOUT)
        source.wait(timeout=_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        sink.kill()
        source.kill()
        return None
    if source.returncode != 0 or sink.returncode not in counter_ok:
        return None
    try:
        return int(digits.strip())
    except ValueError:
        return None


def _stored_secret_length(service: str, account: str) -> Optional[int]:
    """Measure what was stored, in bytes, without ever holding it.

    Two questions, two counts, and the secret in neither answer.

    `security -w` prints the value, so `wc -c` counts the *printed* form — which is not the stored
    length whenever `security` chooses hex.  It prints hex for any value that is not printable
    ASCII, with no marker saying so, and a password made only of hex digits prints literally, so
    the printed form alone cannot be read: halving whatever looks like hex would silently report
    a 128-character hex token as 64 bytes and lose exactly the warning this exists to raise.

    `-g` is the discriminator.  It writes `password: 0x<hex>` for the hex form and a quoted string
    otherwise, so `grep -c` answers the shape with a number and nothing else.

    Bytes, not characters: the ceiling is a buffer size, so a multi-byte secret is cut by bytes.
    """

    find = ("/usr/bin/security", "find-generic-password", "-a", account, "-s", service)
    printed = _piped_count(find + ("-w",), ("/usr/bin/wc", "-c"))
    if printed is None:
        return None
    # grep exits 1 when it matches nothing, and nothing is the plain-text answer, not a failure.
    hex_form = _piped_count(
        find + ("-g",),
        ("/usr/bin/grep", "-c", "^password: 0x"),
        from_stderr=True,
        counter_ok=(0, 1),
    )
    if hex_form is None:
        return None
    # `-w` prints the value followed by a newline, which is not part of what is stored.
    counted = max(printed - 1, 0)
    if not hex_form:
        return counted
    # Two hex digits per stored byte.  An odd count is not a hex dump, so refuse to guess.
    return counted // 2 if counted % 2 == 0 else None


def _manual_keychain_commands(service: str, account: str, shell_file: str = "") -> tuple[str, ...]:
    """One line that stores the secret whole and puts it in the environment.

    One, not three.  A remedy split across lines is one the operator half-applies, and a long
    line is one they repair by hand after their terminal folds it.

    `-w` with a value takes it from argv, where no ceiling exists.  Bare `-w` would hand the
    terminal to `getpass(3)` and its 128-byte buffer, which is the defect being worked around.
    """

    store = (
        f"/usr/bin/security add-generic-password -U -a {shlex.quote(account)} "
        f'-s {shlex.quote(service)} -w "$(pbpaste)"'
    )
    return (store + shell_reload_suffix(shell_file),)


def _actual_tool_exists(tool: str) -> bool:
    if os.path.isabs(tool):
        return os.path.isfile(tool) and os.access(tool, os.X_OK)
    return shutil.which(tool) is not None


def _write_prompt(message: str) -> None:
    # Keep structured command output on stdout while placing context immediately above the
    # human-gated tool's own terminal prompt.
    print(message, file=sys.stderr, flush=True)


def _read_text_input(prompt: str) -> str:
    # stdin remains attached to the terminal, so the terminal echoes this deliberately
    # non-secret value. The prompt goes to stderr to preserve one-document JSON on stdout.
    print(f"Setup input: {prompt}: ", file=sys.stderr, end="", flush=True)
    value = sys.stdin.readline()
    if value == "":
        raise EOFError("text input stream ended")
    return value.rstrip("\n")


@dataclass(frozen=True, slots=True)
class SetupRuntime:
    process: ProcessRunner = run_process
    platform: str = sys.platform
    environ: Mapping[str, str] = None  # type: ignore[assignment]
    tool_exists: ToolLookup = lambda _tool: True
    clock: Callable[[], str] = _now
    enforce_source_hash: bool = False
    write_prompt: PromptWriter = _write_prompt
    read_text_input: TextInputReader = _read_text_input
    # Inert by default so a test runtime never reaches a real Keychain; production wires it.
    secret_length: SecretLengthProbe = lambda _service, _account: None

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
        secret_length=_stored_secret_length,
    )


def _minimal_env(runtime: SetupRuntime) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM")
    env = {name: runtime.environ[name] for name in allowed if name in runtime.environ}
    env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    return env


def _docker_env(runtime: SetupRuntime) -> dict[str, str]:
    """`_minimal_env`, plus the two names the docker CLI needs to know who the user is.

    `RS-12`: without `HOME` and without `DOCKER_CONFIG` the CLI finds no `config.json`, so it has
    no credential store and no context, and every pull is anonymous.  Public images still arrive,
    which is why this survived several runs; a private base image cannot.

    Widened here and not in `_minimal_env` because only docker needs it.  `curl`, `security` and a
    recipe's own verification command gain nothing from `HOME` and would gain the user's dotfiles
    with it — `~/.curlrc` alone can change what a fetch does.
    """

    env = _minimal_env(runtime)
    home = runtime.environ.get("HOME", "")
    config = runtime.environ.get("DOCKER_CONFIG", "") or (
        os.path.join(home, ".docker") if home else ""
    )
    if home:
        env["HOME"] = home
    if config:
        env["DOCKER_CONFIG"] = config
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


_MANAGED_FILE_MODULES = frozenset(
    {
        "shell.env-from-keychain@1",
        "shell.env-from-input@1",
        "file.managed-block@1",
        "json.managed-merge@1",
    }
)


def _managed_file_preflight(plan: SetupPlan) -> str:
    """Stat every reviewed managed-file target before the first effect."""

    for effect in plan.effects:
        if effect.module not in _MANAGED_FILE_MODULES:
            continue
        try:
            if os.path.islink(effect.target):
                return f"refusing to edit symlink: {effect.target}"
            if os.path.lexists(effect.target) and not stat.S_ISREG(os.lstat(effect.target).st_mode):
                return f"managed target is not a regular file: {effect.target}"
        except OSError as error:
            return f"managed target cannot be inspected: {effect.target}: {error}"
    return ""


def _text_input_values(plan: SetupPlan, runtime: SetupRuntime) -> tuple[dict[str, str], str]:
    required: set[str] = set()
    for effect in plan.effects:
        variables = effect.config.get("variables")
        if effect.module == "shell.env-from-input@1" and isinstance(variables, Mapping):
            required.update(str(input_id) for input_id in variables.values())
    values: dict[str, str] = {}
    for declared in plan.item.installer.inputs:
        if declared.type != "text" or declared.id not in required:
            continue
        try:
            value = runtime.read_text_input(declared.prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return {}, f"text input {declared.id!r} was not provided"
        if not value or "\r" in value or "\n" in value:
            return {}, f"text input {declared.id!r} must be a non-empty single-line value"
        values[declared.id] = value
    missing = tuple(sorted(required - set(values)))
    if missing:
        return {}, "text input declaration is unavailable: " + ", ".join(missing)
    return values, ""


def _materialize_text_input_effect(effect: SetupEffect, values: Mapping[str, str]) -> SetupEffect:
    if effect.module != "shell.env-from-input@1":
        return effect
    variables = effect.config.get("variables")
    assert isinstance(variables, Mapping)
    content = "\n".join(
        f"export {name}={shlex.quote(values[str(input_id)])}"
        for name, input_id in variables.items()
    )
    config = dict(effect.config)
    config["content"] = content
    frozen = _freeze(config)
    assert isinstance(frozen, Mapping)
    return replace(effect, config=frozen)


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
        # Two things the old note did not say: that the account already had a value, and where
        # the command ends.  It read as advice to type something, when it is the undo for
        # something already done, and it was folded across three lines by the prose wrapper
        # (`AD-36`).  The command is on its own line, printed whole.
        #
        # `-w` with no value hands the terminal to `getpass(3)` and its 128-byte buffer, so the
        # older advice sent the operator into the very ceiling this step warns about (`AD-34`).
        # `-w "$(pbpaste)"` is the same tool taking the value from argv, where no ceiling exists.
        "recovery": (
            "This account already had a value in the Keychain and this run replaced it. To put "
            "the prior value back, copy it to the clipboard and run:\n"
            f"/usr/bin/security add-generic-password -U -a {shlex.quote(account)} "
            f'-s {shlex.quote(service)} -w "$(pbpaste)"'
            if replaced
            else ""
        ),
    }


def _advise(
    receipt: dict,
    service: str,
    account: str,
    runtime: SetupRuntime,
    *,
    kept_existing: bool,
) -> dict:
    """Say what the Keychain actually holds now, and how to change it by hand.

    Two findings, one voice.  Both end in the same place — the stored secret is not the one the
    server needs — and both are fixed by the same command, so they are reported together instead
    of as two mechanisms the operator has to learn.

    *Kept existing* is the common case and used to be silent.  A run that finds an item already
    there leaves it alone and says "configured"; if the credential was rotated since, nothing
    updated it and nothing said so (`AD-35`).

    *Truncated* is the ceiling case.  The value is never read back into this process:
    `secret_length` counts it in a pipe between two children.  A stored length of exactly the
    ceiling is the signature of a truncated paste — it can also be a secret that is genuinely that
    long, so this warns and never fails.
    """

    notes: list[str] = []
    if kept_existing:
        receipt["existing_secret_kept"] = True
        notes.append(
            "the Keychain already had a value for this account, so this run kept it and never "
            "asked for a new one; if the credential was rotated since, nothing here changed it"
        )
    stored = runtime.secret_length(service, account)
    if stored is not None:
        receipt["stored_length"] = stored
        if stored == _PROMPT_CEILING:
            receipt["truncation_suspected"] = True
            notes.append(
                f"what is stored is exactly {_PROMPT_CEILING} bytes, the point where the Keychain "
                f"prompt cuts a paste; if what was pasted there was longer, only its first "
                f"{_PROMPT_CEILING} bytes were kept"
            )
    if not notes:
        return receipt
    receipt["advisory"] = " — and ".join(notes)
    receipt["remediation_commands"] = _manual_keychain_commands(service, account)
    return receipt


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
        receipt = _keychain_receipt(effect.module, service, account, created=False, replaced=False)
        return _advise(receipt, service, account, runtime, kept_existing=True), False
    runtime.write_prompt(
        f"Setup input: {effect.summary}\n"
        f"  The tool asks twice and keeps at most {_PROMPT_CEILING} bytes; anything longer is cut "
        f"here with no error. This run measures what was stored and says so if it hit that mark."
    )
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
    receipt = _keychain_receipt(
        effect.module,
        service,
        account,
        created=not exists,
        replaced=exists,
    )
    return _advise(receipt, service, account, runtime, kept_existing=False), True


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
    env = _docker_env(runtime)
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
        raise RuntimeError(failure_detail(pulled.stderr or pulled.stdout or "docker pull failed"))
    return {
        "module": effect.module,
        "image": effect.target,
        "preexisting": False,
        # Names Docker and the image for the same reason the build note does: `tag` and
        # `image` on their own read as anything (`AD-38`).  Unlike the build path, rollback
        # genuinely leaves this one — a pulled image can back other containers — so the note
        # says who removes it and when, rather than implying the run will.
        "recovery": (
            f"Docker image {effect.target} was pulled by this run and was not on this "
            "machine before. Rollback leaves it, because an image can be shared by other "
            "containers and nothing removes one automatically. Remove it by hand with "
            "`docker image rm` only after checking that nothing else uses it."
        ),
    }, True


@dataclass(slots=True)
class _RunWorkspace:
    """The one working copy a run may build in, opened on demand and removed with the run."""

    run_dir: Optional[str] = None
    context: Optional[str] = None

    def open(self, plan: SetupPlan, source: str) -> str:
        if self.context is None:
            self.run_dir = new_run_directory(plan)
            try:
                self.context = materialize_build_context(source, self.run_dir)
            except (OSError, RuntimeError):
                self.close()
                raise
        return self.context

    def close(self) -> None:
        if self.run_dir is not None:
            shutil.rmtree(self.run_dir, ignore_errors=True)
        self.run_dir = None
        self.context = None


def _docker_build_apply(
    effect: SetupEffect,
    runtime: SetupRuntime,
    plan: SetupPlan,
    workspace: _RunWorkspace,
) -> tuple[dict, bool]:
    """Build one local image from a working copy of the package, and own only what it created."""

    tag = effect.target
    env = _docker_env(runtime)
    inspect = runtime.process(
        ("docker", "image", "inspect", tag),
        env=env,
        cwd=None,
        timeout=30,
        capture=True,
    )
    preexisting = inspect.returncode == 0
    context = workspace.open(plan, str(effect.config["context_source"]))
    digest = context_digest(context)
    built = runtime.process(effect.argv, env=env, cwd=context, timeout=1800, capture=True)
    if built.returncode != 0:
        raise RuntimeError(failure_detail(built.stderr or built.stdout or "docker build failed"))
    identified = runtime.process(
        ("docker", "image", "inspect", "--format", "{{.Id}}", tag),
        env=env,
        cwd=None,
        timeout=30,
        capture=True,
    )
    return {
        "module": effect.module,
        "tag": tag,
        "context_digest": f"sha256:{digest}",
        "image_id": identified.stdout.strip() if identified.returncode == 0 else "",
        "preexisting": preexisting,
        # The old note said the tag was "left alone", which is false: `docker build --tag` moves
        # it to the image just built.  What is left alone is the *undo*.  It also invited
        # `docker image rm <tag>` — measured `2026-08-19` to delete the image itself when the tag
        # is its last reference, which is the image the server runs from (`AD-37`).
        "recovery": (
            f"Docker image tag {tag} pointed at another image before this run and now points at "
            "the image this run built. The earlier image was not recorded and no longer exists, "
            "so nothing can restore that binding. There is nothing to do unless you are undoing "
            "this setup, and do not remove this tag: the server runs from it."
            if preexisting
            else (
                f"Docker image tag {tag} did not exist before this run and this run "
                "created it. Rollback removes it with `docker image rm`, which also "
                "deletes the image itself when no other tag refers to it. There is "
                "nothing to do unless you are undoing this setup, and do not remove this "
                "tag by hand: the server runs from it."
            )
        ),
    }, True


_PEM_BEGIN = "-----BEGIN CERTIFICATE-----"
_PEM_MAX_BYTES = 4 * 1024 * 1024


def _trust_store_apply(
    effect: SetupEffect,
    runtime: SetupRuntime,
    plan: SetupPlan,
    workspace: _RunWorkspace,
) -> tuple[dict, bool]:
    """Write the matching public certificates into the build context, and only there.

    A corporate root CA is public by nature — it is what the interception proxy presents to every
    machine on the network — so this is not the secret machinery and does not prompt anyone for
    anything.  `security find-certificate` exports certificates and never private keys.
    """

    context = workspace.open(plan, str(effect.config["context_source"]))
    output = str(effect.config["output"])
    destination = os.path.abspath(os.path.join(context, output))
    if os.path.commonpath((context, destination)) != context:
        raise RuntimeError(f"certificate output escapes the build context: {output}")
    if os.path.lexists(destination):
        # The package already ships a file by this name. Overwriting it would silently replace
        # something a maintainer chose to include, and the assessment already read.
        raise RuntimeError(f"certificate output would overwrite a package file: {output}")
    os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
    result = runtime.process(
        effect.argv,
        env=_minimal_env(runtime),
        cwd=None,
        timeout=120,
        capture=True,
        stdout_path=destination,
    )
    subject = str(effect.config["subject_contains"])
    try:
        if result.returncode != 0:
            raise RuntimeError(failure_detail(result.stderr or "certificate export failed"))
        size = os.path.getsize(destination)
        if size > _PEM_MAX_BYTES:
            raise RuntimeError("exported certificate bundle is implausibly large")
        bundle = fs.read_text(destination)
        certificates = bundle.count(_PEM_BEGIN)
        if certificates == 0:
            # An empty bundle builds an image without the CA, which fails much later inside `pip`
            # with a TLS error nobody can trace back to here.
            raise RuntimeError(f"no certificate name contains {subject!r}")
    except (OSError, RuntimeError, UnicodeDecodeError):
        try:
            os.unlink(destination)
        except OSError:
            pass
        raise
    os.chmod(destination, 0o600)
    return {
        "module": effect.module,
        "output": output,
        "subject_contains": subject,
        "certificates": certificates,
        "recovery": "",
    }, False


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
        raise RuntimeError(
            failure_detail(result.stderr or result.stdout or "verification command failed")
        )
    return {"module": effect.module, "verified": True}, False


def _file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


CONTEXT_DIRECTORY = "context"
_CONTEXT_MAX_FILES = 4096
_CONTEXT_MAX_BYTES = 64 * 1024 * 1024


def new_run_directory(plan: SetupPlan) -> str:
    """Create the one private directory this run may write in, outside the object store."""

    runs_root = os.path.join(
        plan.run_root,
        ".agent-artifacts",
        "setup-runs",
    )
    os.makedirs(runs_root, mode=0o700, exist_ok=True)
    os.chmod(runs_root, 0o700)
    run_dir = tempfile.mkdtemp(prefix=f"{plan.plan_hash[:16]}-", dir=runs_root)
    os.chmod(run_dir, 0o700)
    return run_dir


@dataclass(slots=True)
class _CopyBudget:
    files: int = 0
    total_bytes: int = 0

    def take(self, size: int, relative: str) -> None:
        self.files += 1
        self.total_bytes += size
        if self.files > _CONTEXT_MAX_FILES:
            raise RuntimeError(f"build context exceeds {_CONTEXT_MAX_FILES} files at {relative}")
        if self.total_bytes > _CONTEXT_MAX_BYTES:
            raise RuntimeError(f"build context exceeds {_CONTEXT_MAX_BYTES} bytes at {relative}")


def _regular_files(root: str, prefix: str = "") -> list[tuple[str, str]]:
    """Every regular file below one directory, ordered, refusing anything that is not one."""

    found: list[tuple[str, str]] = []
    with os.scandir(root) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            relative = f"{prefix}{entry.name}"
            if entry.is_symlink():
                raise RuntimeError(f"refusing a symlink in a build context: {relative}")
            if entry.is_dir(follow_symlinks=False):
                found.extend(_regular_files(entry.path, f"{relative}/"))
            elif entry.is_file(follow_symlinks=False):
                found.append((relative, entry.path))
            else:
                raise RuntimeError(
                    f"build context may hold only regular files and directories: {relative}"
                )
    return found


def _copy_regular(source: str, destination: str, relative: str, budget: _CopyBudget) -> None:
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"build context entry is not a regular file: {relative}")
        budget.take(info.st_size, relative)
        with open(destination, "wb") as stream:
            for chunk in iter(lambda: os.read(descriptor, 65536), b""):
                stream.write(chunk)
    finally:
        os.close(descriptor)
    os.chmod(destination, 0o700 if info.st_mode & 0o111 else 0o600)


def _copy_context(source: str, destination: str, prefix: str, budget: _CopyBudget) -> None:
    os.makedirs(destination, mode=0o700)
    with os.scandir(source) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            relative = f"{prefix}{entry.name}"
            if entry.is_symlink():
                raise RuntimeError(f"refusing a symlink in a build context: {relative}")
            target = os.path.join(destination, entry.name)
            if entry.is_dir(follow_symlinks=False):
                _copy_context(entry.path, target, f"{relative}/", budget)
            elif entry.is_file(follow_symlinks=False):
                _copy_regular(entry.path, target, relative, budget)
            else:
                raise RuntimeError(
                    f"build context may hold only regular files and directories: {relative}"
                )


def materialize_build_context(source: str, run_dir: str) -> str:
    """Copy one declared package subtree into the run directory, so a step may write beside it.

    The package a recipe ships in is read-only by construction: the object store recomputes an
    object's digest on every read, and a vendored payload is compared with the upstream subtree it
    was taken from.  A build that needs a file next to its `Dockerfile` therefore cannot get one by
    writing into the package.  It gets a working copy instead, which AART owns, which lives beside
    the run's other scratch, and which is removed with the run.

    The copy carries file modes and nothing else: no symlink, no device, no socket, so nothing in
    the copy can reach back out of it.
    """

    if os.path.islink(source) or not os.path.isdir(source):
        raise RuntimeError(f"build context source is not a directory: {source}")
    destination = os.path.join(run_dir, CONTEXT_DIRECTORY)
    if os.path.exists(destination):
        raise RuntimeError("build context already materialized for this run")
    try:
        _copy_context(source, destination, "", _CopyBudget())
    except (OSError, RuntimeError):
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def context_digest(root: str) -> str:
    """Name the bytes a build ran on: every regular file's path, executable bit, and content.

    A local build has no output digest to pin — two machines building one context get two image
    ids — so the receipt pins the input instead.  Empty directories are deliberately invisible
    here: nothing is built from a directory's existence, and including it would make the digest
    depend on how the copy was walked.
    """

    digest = hashlib.sha256()
    for relative, path in _regular_files(root):
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(b"x" if os.stat(path, follow_symlinks=False).st_mode & 0o111 else b"-")
        digest.update(_file_hash(path).encode("ascii") + b"\0")
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
        # No command reverses a completed setup; `aart setup rollback` never shipped.  Running the
        # recipe again is what re-applies the compensation this receipt describes.
        "recovery": "Re-run `aart marketplace setup` for this artifact to retry the compensation.",
    }


def _custom_apply(effect: SetupEffect, runtime: SetupRuntime, plan: SetupPlan) -> tuple[dict, bool]:
    run_dir = new_run_directory(plan)
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


def _apply_effect(
    effect: SetupEffect,
    runtime: SetupRuntime,
    plan: SetupPlan,
    workspace: _RunWorkspace,
) -> tuple[dict, bool]:
    if effect.module == "macos-keychain.store@1":
        return _keychain_apply(effect, runtime)
    if effect.module in (
        "shell.env-from-keychain@1",
        "shell.env-from-input@1",
        "file.managed-block@1",
    ):
        return _managed_block_apply(effect)
    if effect.module == "json.managed-merge@1":
        return _json_apply(effect)
    if effect.module == "directory.create@1":
        return _directory_apply(effect)
    if effect.module == "docker.pull@1":
        return _docker_apply(effect, runtime)
    if effect.module == "docker.build@1":
        return _docker_build_apply(effect, runtime, plan, workspace)
    if effect.module == "trust-store.export-certificates@1":
        return _trust_store_apply(effect, runtime, plan, workspace)
    if effect.module == "command.verify@1":
        return _command_verify(effect, runtime)
    if effect.module == "restart.notice@1":
        return {"module": effect.module, "message": effect.summary}, False
    if effect.module == "custom.install@1":
        return _custom_apply(effect, runtime, plan)
    raise RuntimeError(f"unsupported runtime module: {effect.module}")


def _rollback_receipt(receipt: Mapping[str, object], runtime: SetupRuntime) -> bool:
    # Failure receipts retain already-compensated steps as audit evidence for `receipt show`.
    # Replaying one would undo someone else's later change, so it is already terminal here.
    if receipt.get("setup_disposition") == "compensated":
        return True
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
    if module in (
        "shell.env-from-keychain@1",
        "shell.env-from-input@1",
        "file.managed-block@1",
    ) and receipt.get("changed"):
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
    if module == "docker.build@1":
        if receipt.get("preexisting") is True:
            # The tag named an image before this run; removing it would take away something the
            # run never gave, which is the same care `docker.pull@1` takes with a shared image.
            return True
        result = runtime.process(
            ("docker", "image", "rm", str(receipt["tag"])),
            # The same environment the build ran in, or rollback asks a different daemon than the
            # one that holds the tag: `DOCKER_CONFIG` carries the context, not just the login.
            env=_docker_env(runtime),
            cwd=None,
            timeout=120,
            capture=True,
        )
        return result.returncode == 0
    # Docker images may be shared and are never removed automatically; verify/notices mutate
    # nothing. Other changed modules are handled above with ownership-aware compensation.
    return module in (
        "restart.notice@1",
        "command.verify@1",
        # The bundle was written into a working copy that the run already deleted.
        "trust-store.export-certificates@1",
    ) or not bool(receipt.get("changed", False))


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
    preflight_failure = _managed_file_preflight(plan)
    if preflight_failure:
        return _record(
            plan,
            "prerequisite_missing",
            preflight_failure,
            started=started,
            finished=runtime.clock(),
            exit_status=1,
        )
    text_inputs, input_failure = _text_input_values(plan, runtime)
    if input_failure:
        return _record(
            plan,
            "cancelled",
            input_failure,
            started=started,
            finished=runtime.clock(),
            exit_status=1,
        )
    receipts: list[Mapping[str, object]] = []
    workspace = _RunWorkspace()
    try:
        return _apply_effects(
            plan,
            runtime,
            consent,
            receipts,
            workspace,
            started,
            text_inputs,
        )
    finally:
        # The working copy belongs to the run, not to the recipe: it goes whether the run
        # configured, declined, or failed, and it leaves the package it was copied from alone.
        workspace.close()


def _apply_effects(
    plan: SetupPlan,
    runtime: SetupRuntime,
    consent: Consent,
    receipts: list[Mapping[str, object]],
    workspace: _RunWorkspace,
    started: str,
    text_inputs: Mapping[str, str],
) -> SetupStateRecord:
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
            run_effect = _materialize_text_input_effect(effect, text_inputs)
            receipt, effect_changed = _apply_effect(run_effect, runtime, plan, workspace)
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
