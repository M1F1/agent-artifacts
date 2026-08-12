#!/bin/sh
# AART manual setup: see ../SETUP.md
#
# Reviewed custom entrypoint. AART calls it with one of plan|apply|verify|rollback, from a
# private run directory, with a minimal environment and shell=False. It writes its structured
# result to the path AART provides and never prompts, never reads a credential from the
# environment, and never prints command output that could carry one.

set -eu

action="${1:-}"
workspace="${HOME}/.aart-onboarding"

case "${action}" in
  plan)
    printf 'create %s\n' "${workspace}"
    ;;
  apply)
    mkdir -p "${workspace}"
    ;;
  verify)
    test -d "${workspace}"
    ;;
  rollback)
    rmdir "${workspace}" 2>/dev/null || true
    ;;
  *)
    echo "unsupported action" >&2
    exit 2
    ;;
esac
