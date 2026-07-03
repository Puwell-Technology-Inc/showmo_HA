"""Exceptions raised by pyshowmo."""

from __future__ import annotations


class ShowMoError(Exception):
    """Base exception for pyshowmo."""


class DiscoveryError(ShowMoError):
    """Raised when a discovery operation fails."""


class AuthenticationError(ShowMoError):
    """Raised when a request fails due to invalid credentials."""
