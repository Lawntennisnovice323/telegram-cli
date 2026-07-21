"""Versioned local authorization policies for agent operations."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from clitg.errors import ClitgError
from clitg.models import ErrorCode, PolicyDocument


def load_policy(path: str | Path) -> PolicyDocument:
    """Load and validate one policy document."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return PolicyDocument.model_validate(value)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ClitgError(ErrorCode.INVALID_INPUT, "Policy document is invalid") from exc


def evaluate_policy(
    policy: PolicyDocument | None,
    command: str,
    *,
    risk: str = "read",
    peer: str | None = None,
    raw_method: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic policy decision where deny rules take precedence."""

    if policy is None:
        return {"allowed": True, "reason": "no_policy"}
    if _matches(command, policy.deny_commands):
        return {"allowed": False, "reason": "command_denied"}
    if policy.allow_commands and not _matches(command, policy.allow_commands):
        return {"allowed": False, "reason": "command_not_allowed"}
    if peer and _matches(peer, policy.deny_peers):
        return {"allowed": False, "reason": "peer_denied"}
    if peer and policy.allow_peers and not _matches(peer, policy.allow_peers):
        return {"allowed": False, "reason": "peer_not_allowed"}
    if (
        risk in {"write", "destructive", "critical"}
        and policy.allow_mutation_risks
        and risk not in policy.allow_mutation_risks
    ):
        return {"allowed": False, "reason": "mutation_risk_not_allowed"}
    if raw_method:
        if _matches(raw_method, policy.deny_raw_methods):
            return {"allowed": False, "reason": "raw_method_denied"}
        if policy.allow_raw_methods and not _matches(raw_method, policy.allow_raw_methods):
            return {"allowed": False, "reason": "raw_method_not_allowed"}
        if policy.allow_raw_risks and risk not in policy.allow_raw_risks:
            return {"allowed": False, "reason": "raw_risk_not_allowed"}
    return {"allowed": True, "reason": "allowed"}


def require_policy(decision: dict[str, Any]) -> None:
    """Raise a structured permission error for a denied decision."""

    if not decision["allowed"]:
        raise ClitgError(
            ErrorCode.PERMISSION_DENIED,
            "Local policy denied the operation",
            details={"policy_reason": decision["reason"]},
        )


def _matches(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)
