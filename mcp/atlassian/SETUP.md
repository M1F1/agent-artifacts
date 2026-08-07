# Atlassian Rovo MCP setup

Prefer Atlassian's OAuth 2.1 flow for interactive use. The official current endpoint is:

```text
https://mcp.atlassian.com/v1/mcp/authv2
```

The declarative installer is an optional non-interactive service-account path. It asks macOS
Keychain to prompt for the service-account API key, stores no credential in `aart` state or
arguments, and adds a managed `.zshrc` lookup for `ATLASSIAN_API_KEY`. Start a new shell and
restart the harness afterward. Your organization administrator must enable API-token
authentication.

References:

- https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/
- https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-authentication-via-api-token/
- https://id.atlassian.com/manage-profile/security/api-tokens

`SETUP.md` is reference material only. `setup/installer.json` is the reviewed executable
contract.
