"""Errors for the Integrations Hub."""

from __future__ import annotations


class IntegrationError(RuntimeError):
    """Raised when an integration cannot be connected, verified, or used."""
