"""Typed exception classes for MemoryWiki user-facing failures."""

from __future__ import annotations


class MemoryWikiError(Exception):
    """Base class for MemoryWiki domain errors."""


class MemoryRootError(ValueError, MemoryWikiError):
    """Raised when a memory root is missing, unsafe, or malformed."""


class MemoryStoreRequiredError(MemoryRootError):
    """Raised when a write path unexpectedly has no usable memory store."""
