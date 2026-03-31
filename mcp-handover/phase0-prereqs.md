# Phase 0: Prerequisites & Configuration

## Step 1: Install MCP dependency

Add to `workspace/requirements.txt` (after the Qdrant section):

```
# --- MCP (Model Context Protocol) ---
mcp>=1.0.0                       # Anthropic MCP SDK (Python)
```

Uncomment the Google API lines (lines 67-69):

```
google-auth>=2.23.0
google-auth-oauthlib>=1.1.0
google-api-python-client>=2.100.0
```

Run: `pip install -r requirements.txt`

## Step 2: Create MCP Config Model

**Create file**: `workspace/sci_fi_dashboard/mcp_config.py`

```python
"""MCP configuration models — Pydantic validation for synapse.json mcp section."""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator


class ProactiveSourceConfig(BaseModel):
    proactive: bool = True
    lookahead_minutes: int = 30
    max_unread: int = 5
    mentions_only: bool = True


class ProactiveConfig(BaseModel):
    enabled: bool = True
    poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    sources: dict[str, ProactiveSourceConfig] = Field(default_factory=dict)


class BuiltinServerConfig(BaseModel):
    enabled: bool = True
    credentials_path: str = ""
    token_path: str = ""
    bot_token: str = ""
    user_token: str = ""


class CustomServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("command must be a non-empty string")
        return v


class MCPConfig(BaseModel):
    enabled: bool = True
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    builtin_servers: dict[str, BuiltinServerConfig] = Field(default_factory=dict)
    custom_servers: dict[str, CustomServerConfig] = Field(default_factory=dict)

    def is_server_enabled(self, name: str) -> bool:
        if name in self.builtin_servers:
            return self.builtin_servers[name].enabled
        return name in self.custom_servers


def load_mcp_config(raw_mcp: dict | None) -> MCPConfig:
    """Parse the 'mcp' section of synapse.json into validated MCPConfig."""
    if not raw_mcp:
        return MCPConfig(enabled=False)
    return MCPConfig(**raw_mcp)
```

## Step 3: Update SynapseConfig

**Modify**: `workspace/synapse_config.py`

At line 49 (after `session: dict = field(default_factory=dict)`), add:
```python
    mcp: dict = field(default_factory=dict)
```

At line 85 (inside `load()`, after `session = raw.get("session", {})`), add:
```python
            mcp = raw.get("mcp", {})
```

At line 96 (in the `return cls(...)` call, after `session=session,`), add:
```python
            mcp=mcp,
```

## Step 4: Add MCP section to synapse.json

Add to `~/.synapse/synapse.json` (top level, alongside providers/channels/etc):

```json
"mcp": {
    "enabled": true,
    "proactive": {
        "enabled": true,
        "poll_interval_seconds": 60,
        "sources": {
            "calendar": { "proactive": true, "lookahead_minutes": 30 },
            "gmail": { "proactive": true, "max_unread": 5 },
            "slack": { "proactive": true, "mentions_only": true }
        }
    },
    "builtin_servers": {
        "memory": { "enabled": true },
        "conversation": { "enabled": true },
        "tools": { "enabled": true },
        "gmail": {
            "enabled": false,
            "credentials_path": "~/.synapse/google_credentials.json",
            "token_path": "~/.synapse/google_token.json"
        },
        "calendar": {
            "enabled": false,
            "credentials_path": "~/.synapse/google_credentials.json",
            "token_path": "~/.synapse/google_token.json"
        },
        "slack": {
            "enabled": false,
            "bot_token": "",
            "user_token": ""
        }
    },
    "custom_servers": {}
}
```

## Verify Phase 0

```bash
cd workspace
python -c "from synapse_config import SynapseConfig; c = SynapseConfig.load(); print('mcp' in dir(c))"
# Should print: True

python -c "from sci_fi_dashboard.mcp_config import load_mcp_config; print(load_mcp_config({'enabled': True}))"
# Should print: MCPConfig(enabled=True, ...)
```
