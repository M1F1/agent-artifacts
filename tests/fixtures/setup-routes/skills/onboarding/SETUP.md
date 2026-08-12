# Manual setup: onboarding skill

This package uses a custom entrypoint, which is reviewed, hash-bound trusted code — not a
sandbox. Reading this document is the way to see exactly what it intends to do before you
approve it, and it is a complete alternative if you decline.

## What the automation would do

Show a notice asking you to open a new terminal, then create the directory
`~/.aart-onboarding`, which the skill uses for local notes. Nothing is downloaded, no credential
is read, and no configuration file is edited.

The notice is a declared module step; only the directory needs the custom script. Prefer a
reviewed module wherever one exists and keep the entrypoint for what modules cannot express.

## Doing it by hand

Create that directory yourself with your usual file manager or shell. That is the whole setup.

To undo it, remove the directory; it holds only files you put there.

## Why the script starts with a comment

Every version-2 custom entrypoint begins with `# AART manual setup: see ../SETUP.md`, so anyone
reading the script directly is pointed back here. The comment is checked when the catalog is
validated; the runtime preamble applies regardless of what the script says.
