"""Synapse Integrations Hub.

Unified plumbing for connecting third-party services (Google Calendar, Gmail,
Notion, Slack, etc.) so the user never has to leave Synapse to configure one.

Public surface:
    from sci_fi_dashboard.integrations import (
        ConnectionResult,
        IntegrationDefinition,
        IntegrationError,
        connect,
        disconnect,
        list_integrations,
        registry,
        status,
        verify,
    )
"""

from __future__ import annotations

from .errors import IntegrationError
from .manager import (
    ConnectionResult,
    connect,
    disconnect,
    list_integrations,
    status,
    verify,
)
from .registry import IntegrationDefinition, get_integration, list_definitions, registry

__all__ = [
    "ConnectionResult",
    "IntegrationDefinition",
    "IntegrationError",
    "connect",
    "disconnect",
    "get_integration",
    "list_definitions",
    "list_integrations",
    "registry",
    "status",
    "verify",
]
