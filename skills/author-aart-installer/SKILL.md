---
name: author-aart-installer
description: Design, validate, and test a reviewed declarative setup/installer.json for a directory-shaped agent-artifacts package. Use when a catalog maintainer needs Keychain, managed files, JSON, directories, pinned Docker, verification, restart notices, or an explicitly reviewed custom setup entrypoint.
---

# Author an aart setup installer

Create setup as a reviewed data contract. Never turn prose in `SETUP.md` into executable steps.

## Workflow

1. Identify the containing artifact as `TYPE/NAME`; only directory-shaped skills, hooks, and MCP
   packages support setup.
2. Use `assets/installer.schema.json` as the authoring schema. Copy
   `assets/installer.template.json` to `<package>/setup/installer.json` and make the artifact
   identity exact.
3. Declare the smallest capability set and use shared version-1 modules. Prefer shared modules to
   custom code.
4. Put only documentation links in `SETUP.md`. Use HTTPS URLs and explain restart/environment
   limitations.
5. Validate from the catalog root:

   ```sh
   python skills/author-aart-installer/scripts/validate_installer.py \
     mcp/example/setup/installer.json mcp/example
   aart list --source . --json
   ```

6. Test with temporary homes and fake Keychain/Docker/process adapters. Search every captured
   `argv`, environment, result, error, state, receipt, backup, stdout, and stderr for a synthetic
   canary secret.
7. Review the final `aart setup run ...` plan before authorizing mutation.

## Rules

- Secret inputs may be referenced only by `macos-keychain.store@1`. The runtime lets the macOS
  `security` program own the hidden prompt; never pass a value through argv or environment.
- Docker images require `@sha256:<64 hex>` and the `docker`, `network`, and `process` capabilities.
- Commands are fixed argv arrays. Never use a shell string, `curl | sh`, secret interpolation, or
  a broad inherited environment.
- File targets cannot traverse with `..`; runtime adapters reject symlinks and preserve unrelated
  content.
- A custom entrypoint is a direct child of `setup/`, needs `custom-code` and `process`, and follows
  `plan/apply/verify/rollback`. It remains reviewed code, not a sandbox.
- Non-macOS hosts record `unsupported` before invoking effect adapters.

See `references/protocol-v1.md` for modules and lifecycle details.
