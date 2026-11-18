# MCP tool caching per session

With **Use Cached Server** enabled, two sessions using the same MCP server,
Langflow user, headers, and timeout could reuse the first session's tools. This
skipped discovery for the second session, even when the MCP server exposed a
different tool list for that session.

The cache key now includes the Langflow session ID alongside the existing server,
user, headers, and timeout. Both the shared server cache and the short-lived
component cache use this key. A new session discovers its own tools; repeated
requests within that session can reuse them. Multiple MCP components retain their
existing server and client-setting distinctions.

Invocation copies preserve the current session and user from their source
component. When no session ID is available, discovery results are not cached.
Callers must provide distinct Langflow session IDs for conversations that require
separate discovery.

MCP servers, including MCP Composer, continue to decide which tools a client can
access. This change does not add entitlement logic to Langflow. Existing cache
limits, credential-variable safeguards, and cache-toggle behavior are preserved.

Regression tests exercise the actual component and cache services with discovery
stubbed at the MCP boundary. They cover A → B → A reuse, separate servers and
users, concurrent sessions, missing session IDs, and invocation copies.
