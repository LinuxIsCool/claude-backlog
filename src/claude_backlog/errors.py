"""Custom errors for claude-backlog operations.

Mirrors MrLesk/Backlog.md's `BacklogToolError` pattern: every failure carries
a typed code so MCP clients can branch on `error.code` rather than parsing
prose error messages.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Typed error codes for claude-backlog operations."""

    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
    ID_COLLISION = "ID_COLLISION"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    DOD_INVALID = "DOD_INVALID"
    AC_INVALID = "AC_INVALID"
    INVALID_STAGE = "INVALID_STAGE"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    FILE_IO_ERROR = "FILE_IO_ERROR"


class BacklogToolError(Exception):
    """Operation failed in claude-backlog file or schema layer.

    Attributes:
        code: A `ErrorCode` enum value identifying the failure class.
        message: Human-readable detail.
        context: Optional dict of structured context (e.g., {"task_id": 42}).
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        context: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.context = context or {}
        super().__init__(f"[{code.value}] {message}")

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for MCP error responses."""
        return {
            "code": self.code.value,
            "message": self.message,
            "context": self.context,
        }
