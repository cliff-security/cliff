"""GitHub App + Device Flow onboarding (ADR-0035, IMPL-0010).

Lives alongside the rest of the integration framework. The credential
vault (vault.py) and MCP gateway (gateway.py) are intentionally untouched
- the user access token issued by the device flow is stored in the vault
under the same ``github_personal_access_token`` key the gateway already
substitutes, so workspaces keep working without any agent-side change.
"""
