# Manual setup: Atlassian MCP

The reviewed installer can do this for you. You may decline it and follow these steps yourself;
the artifact itself is already installed either way, and declining never removes it.

## What the automation would do

1. Store an Atlassian API token in the macOS Keychain under service `aart/mcp/atlassian`,
   account `default`.
2. Add an owned block to `~/.zshrc` that reads that Keychain entry into `ATLASSIAN_API_TOKEN`
   when a shell starts.

Both steps are reversible. Nothing else on your machine is touched.

## Doing it by hand

1. Create an API token in your Atlassian account settings. Keep it in your password manager;
   do not paste it into a file, a shell history entry, or this document.
2. Add the token to the Keychain under the service and account names above. The `security`
   command that ships with macOS can do this interactively, so the value never appears in your
   shell history.
3. Export `ATLASSIAN_API_TOKEN` in your shell startup file by reading it back from the Keychain
   rather than writing the value into the file.
4. Open a new terminal and confirm the harness can reach the server.

## If you change your mind

Run the reviewed installer later with `aart setup run mcp/atlassian`. It shows the same review
first and asks for each effect separately, so following this document now costs you nothing.
