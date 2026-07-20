"""Domain exceptions and error translation."""

from __future__ import annotations

from typing import Any

from clitg.models import ErrorCode, ErrorInfo

EXIT_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 2,
    ErrorCode.AUTH_REQUIRED: 3,
    ErrorCode.PROFILE_ERROR: 3,
    ErrorCode.NOT_FOUND: 4,
    ErrorCode.AMBIGUOUS_PEER: 4,
    ErrorCode.CONFLICT: 5,
    ErrorCode.CONFIRMATION_REQUIRED: 5,
    ErrorCode.PERMISSION_DENIED: 6,
    ErrorCode.RATE_LIMITED: 7,
    ErrorCode.TELEGRAM_RPC: 8,
    ErrorCode.NETWORK: 8,
    ErrorCode.INTERNAL: 1,
}


class ClitgError(Exception):
    """A failure that is safe to serialize for an agent."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.info = ErrorInfo(
            code=code,
            message=message,
            details=details or {},
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )

    @property
    def exit_code(self) -> int:
        """Return the documented process exit code."""

        return EXIT_BY_CODE[self.info.code]
