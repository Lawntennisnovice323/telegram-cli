from __future__ import annotations

import json
from pathlib import Path

import pytest
from keyring.errors import KeyringError

import clitg.credentials as credential_module
from clitg.credentials import CredentialStore
from clitg.errors import ClitgError
from clitg.operations import OPERATION_BY_COMMAND, OPERATIONS, normalize_params, operation_catalog
from clitg.policy import evaluate_policy, load_policy, require_policy
from clitg.storage import Paths


class AvailableBackend:
    priority = 1


def test_credential_keyring_and_file_fallback(
    paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = CredentialStore(paths)
    saved: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(credential_module.keyring, "get_keyring", lambda: AvailableBackend())
    monkeypatch.setattr(
        credential_module.keyring,
        "set_password",
        lambda service, profile, value: saved.__setitem__((service, profile), value),
    )
    monkeypatch.setattr(
        credential_module.keyring,
        "get_password",
        lambda service, profile: saved.get((service, profile)),
    )
    reference = store.save("personal", "hash")
    assert reference == "keyring:personal"
    assert store.load(reference) == "hash"

    monkeypatch.setattr(credential_module.keyring, "get_password", lambda *_: "different")
    mismatched = store.save("mismatch", "expected")
    assert mismatched.startswith("file:")

    def fail(*_: object) -> None:
        raise KeyringError("unavailable")

    monkeypatch.setattr(credential_module.keyring, "set_password", fail)
    reference = store.save("fallback", "file-hash")
    assert reference.startswith("file:")
    assert store.load(reference) == "file-hash"
    assert Path(reference.removeprefix("file:")).stat().st_mode & 0o777 == 0o600


def test_credential_errors_and_kinds(paths: Paths, monkeypatch: pytest.MonkeyPatch) -> None:
    store = CredentialStore(paths)
    monkeypatch.setattr(credential_module.keyring, "get_password", lambda *_: None)
    with pytest.raises(ClitgError, match="unavailable"):
        store.load("keyring:missing")

    def fail(*_: object) -> None:
        raise KeyringError("unavailable")

    monkeypatch.setattr(credential_module.keyring, "get_password", fail)
    with pytest.raises(ClitgError, match="system keyring"):
        store.load("keyring:missing")
    with pytest.raises(ClitgError, match="read"):
        store.load(f"file:{paths.data_dir / 'missing'}")
    empty = paths.data_dir / "empty"
    empty.parent.mkdir(parents=True)
    empty.write_text("")
    with pytest.raises(ClitgError, match="unavailable"):
        store.load(f"file:{empty}")
    with pytest.raises(ClitgError, match="unavailable"):
        store.load("unknown:value")

    monkeypatch.setenv("CLITG_API_HASH", "env")
    assert store.kind("keyring:p", None) == "environment"
    monkeypatch.delenv("CLITG_API_HASH")
    assert store.kind("keyring:p", None) == "keyring"
    assert store.kind("file:/x", None) == "file"
    assert store.kind(None, "legacy") == "legacy"
    assert store.kind(None, None) == "missing"


def test_policy_loading_and_decisions(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "allow_commands": ["messages.*", "raw.invoke"],
                "deny_commands": ["messages.delete"],
                "allow_peers": ["@allowed", "123"],
                "deny_peers": ["@blocked"],
                "allow_mutation_risks": ["write"],
                "allow_raw_methods": ["help.*"],
                "deny_raw_methods": ["help.bad"],
                "allow_raw_risks": ["read"],
            }
        )
    )
    policy = load_policy(path)
    assert evaluate_policy(None, "anything") == {"allowed": True, "reason": "no_policy"}
    cases = (
        ("messages.delete", "read", "@allowed", None, "command_denied"),
        ("contacts.list", "read", None, None, "command_not_allowed"),
        ("messages.list", "read", "@blocked", None, "peer_denied"),
        ("messages.list", "read", "@other", None, "peer_not_allowed"),
        ("messages.send", "critical", "@allowed", None, "mutation_risk_not_allowed"),
        ("raw.invoke", "read", None, "help.bad", "raw_method_denied"),
        ("raw.invoke", "read", None, "account.get", "raw_method_not_allowed"),
        ("raw.invoke", "write", None, "help.write", "raw_risk_not_allowed"),
    )
    for command, risk, peer, method, reason in cases:
        decision = evaluate_policy(policy, command, risk=risk, peer=peer, raw_method=method)
        assert decision == {"allowed": False, "reason": reason}
        with pytest.raises(ClitgError, match="denied"):
            require_policy(decision)
    allowed = evaluate_policy(policy, "messages.send", risk="write", peer="@allowed")
    assert allowed == {"allowed": True, "reason": "allowed"}
    require_policy(allowed)
    assert evaluate_policy(
        policy,
        "raw.invoke",
        risk="read",
        raw_method="help.good",
    )["allowed"]


def test_invalid_policy_documents(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ClitgError, match="invalid"):
        load_policy(missing)
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{")
    with pytest.raises(ClitgError, match="invalid"):
        load_policy(invalid_json)
    invalid_model = tmp_path / "model.json"
    invalid_model.write_text('{"unknown": true}')
    with pytest.raises(ClitgError, match="invalid"):
        load_policy(invalid_model)


def test_operation_registry_and_parameter_normalization() -> None:
    assert OPERATION_BY_COMMAND["stories.publish"].mutation
    assert OPERATION_BY_COMMAND["chats.delete-channel"].critical
    assert not OPERATION_BY_COMMAND["account.get"].mutation
    catalog = operation_catalog()
    assert set(catalog) == {operation.command for operation in OPERATIONS}
    assert "privacy_rules" in catalog["stories.publish"]["parameters"]
    value = normalize_params(
        {
            "peer": "me",
            "channel": "@group",
            "user_id": "@user",
            "users": ["@a", "@b"],
            "nested": {"value": 1},
            "count": 2,
        }
    )
    assert value["peer"] == {"$peer": "me"}
    assert value["channel"] == {"$channel": "@group"}
    assert value["user_id"] == {"$user": "@user"}
    assert value["users"] == [{"$user": "@a"}, {"$user": "@b"}]
    assert value["nested"] == {"value": 1}
    assert normalize_params("plain") == "plain"
