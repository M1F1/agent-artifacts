# Tutorial: AART 1.0.0 with direct sources only

This path uses no registry, reporting destination, optional analyzer, real Keychain credential, or
package index.

1. Install AART from a reviewed local checkout or `aart_cli-1.0.0-py3-none-any.whl`.
2. In your project, run `aart` and read the controls screen.
3. Choose **User**, then **Sources** and add a compatible local or Git repository. A native source
   contains `aart-source.json` and canonical packages.
4. Sync it. AART validates an immutable candidate and advances the last-known-good pointer only on
   success. Git credentials remain owned by Git/SSH helpers.
5. Choose harness profiles, action, project/user scope, and Copy or Symlink. Select rows with Space,
   move forward with Enter, and use Backspace without losing the basket.
6. Review qualified source, version, digests, trust, actual effects, and destinations; Finalize once.
7. Use `aart status`, fetch-free `aart check`, reviewed `aart update`, and `aart uninstall` for the
   recorded subscription.

Copy writes independent bytes. Managed Symlink points to an immutable object in AART's durable
store, not to the executable checkout; replacing the Python environment does not break it. Sync
alone never retargets installed content.
