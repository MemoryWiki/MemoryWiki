"""Typed exception classes for MemoryWiki user-facing failures."""

from __future__ import annotations


class MemoryWikiError(Exception):
    """Base class for MemoryWiki domain errors."""

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        fix: str | None = None,
    ) -> None:
        self.message = message
        self.reason = reason
        self.fix = fix
        super().__init__(self._render())

    def _render(self) -> str:
        parts = [self.message]
        if self.reason:
            parts.append("Reason: %s" % self.reason)
        if self.fix:
            parts.append("Fix: %s" % self.fix)
        return " ".join(parts)


class MemoryRootError(MemoryWikiError, ValueError):
    """Raised when a memory root is missing, unsafe, or malformed."""


class MemoryPathError(MemoryRootError):
    """Raised when a filesystem path is unsafe or outside the allowed root."""


class MemoryConfigError(MemoryWikiError, ValueError):
    """Raised when MemoryWiki configuration is missing, invalid, or unsafe."""


class MemoryWriteDisabledError(MemoryWikiError, PermissionError):
    """Raised when an explicit write gate has not been enabled."""


class MemoryValidationError(MemoryWikiError, ValueError):
    """Raised when memory data or command arguments fail validation."""


class MemoryCliUsageError(MemoryWikiError, ValueError):
    """Raised when a CLI command is missing required user input."""


class MemorySecurityError(MemoryWikiError, PermissionError):
    """Raised when a security gate blocks an operation."""


class MemoryStoreRequiredError(MemoryRootError):
    """Raised when a write path unexpectedly has no usable memory store."""


def format_cli_error(exc: BaseException) -> str:
    """Render an exception as concise actionable CLI text."""
    text = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, MemoryWikiError):
        return text
    lowered = text.lower()
    if "permission" in lowered:
        return "%s Fix: check local file permissions or rerun with the required explicit gate." % text
    if "not found" in lowered or "no such file" in lowered:
        return "%s Fix: verify the path or initialize the memory root first." % text
    return "%s Fix: rerun with --help for usage or inspect the configured memory root." % text
