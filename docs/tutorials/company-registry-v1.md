# Tutorial: AART 1.0.0 with a company registry

A company registry adds reviewed discovery and policy while direct team/private sources remain
possible when organization policy permits them.

1. Install AART locally and open `aart`.
2. Add the approved company registry URL in **Sources**. Mark it as the optional default registry if
   your organization recommends that ranking; default never resolves an identity collision.
3. Add any permitted team source separately. The marketplace keeps coordinates such as
   `company/skill/review` and `team/skill/review`; select the qualified row when names collide.
4. Review the locally derived trust class, registry review/provenance, digest-bound security
   evidence, compatibility, setup capabilities, scope, mode, and destinations before Finalize.
5. Preview any default-No redacted report offered separately to the registries that supplied the
   selected artifacts. User or organization configuration may disable prompts or select one
   central destination. Reporting failure never changes installation success.

Maintainers work in an explicit writable registry checkout. Before a PR they run:

```shell
aart registry format --source . --check
aart registry validate --source . --strict --frozen
aart registry lock --source . --check
aart registry build --source . --check
aart registry audit --source .
aart registry test --source . --compatibility all --latest-version 1.0.0
```

Native references pin upstream commit/digests without copying payload. Foreign content is converted
by a reviewed built-in importer before consumer installation. AART never commits or pushes a
maintainer checkout automatically.
