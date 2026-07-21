from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from clitg.errors import ClitgError
from clitg.models import ErrorCode, Profile
from clitg.storage import Paths, ProfileStore, StateStore, _secure_write


def test_paths(paths: Paths) -> None:
    assert paths.profiles_file.name == "profiles.json"
    assert paths.state_file.name == "state.sqlite3"
    assert paths.session_file("personal").parent.exists()
    assert paths.profile_lock("personal").lock_file.endswith(".lock")
    assert paths.export_dir("personal").name == "exports"


def test_secure_write(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "secret"
    _secure_write(path, "first")
    _secure_write(path, "second")
    assert path.read_text() == "second"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_non_posix_storage_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "secret"
    paths = Paths(tmp_path / "config", tmp_path / "data")
    monkeypatch.setattr(os, "name", "nt")
    _secure_write(path, "value")
    StateStore(paths)
    assert path.read_text() == "value"
    assert paths.state_file.exists()


def test_profile_lifecycle(profile_store: ProfileStore, profile: Profile) -> None:
    created = profile_store.create(profile)
    assert created.is_default is True
    assert profile_store.resolve().name == "personal"
    assert profile_store.resolve("personal").api_hash == "secret"
    assert profile_store.get("personal").api_id == 12345
    assert profile_store.list() == [created]
    assert profile_store.set_default("personal").is_default is True
    removed = profile_store.remove("personal")
    assert removed.is_default is False
    with pytest.raises(ClitgError, match="No profile"):
        profile_store.resolve()


def test_multiple_profiles_and_environment(
    profile_store: ProfileStore,
    profile: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_store.create(profile)
    second = Profile(name="second", api_id=2, api_hash="b")
    profile_store.create(second, make_default=True)
    profile_store.remove("personal")
    profile_store.create(profile)
    monkeypatch.setenv("CLITG_PROFILE", "personal")
    assert profile_store.resolve().name == "personal"
    assert [item.name for item in profile_store.list()] == ["personal", "second"]


@pytest.mark.parametrize("name", ["Upper", "-bad", "bad_underscore", "x" * 64])
def test_invalid_profile_names(profile_store: ProfileStore, profile: Profile, name: str) -> None:
    profile.name = name
    if name == "Upper":
        assert profile_store.create(profile).name == "upper"
    else:
        with pytest.raises(ClitgError) as error:
            profile_store.create(profile)
        assert error.value.info.code == ErrorCode.INVALID_INPUT


def test_profile_conflicts_and_missing(profile_store: ProfileStore, profile: Profile) -> None:
    profile_store.create(profile)
    with pytest.raises(ClitgError, match="already exists"):
        profile_store.create(profile)
    for operation in (profile_store.get, profile_store.set_default, profile_store.remove):
        with pytest.raises(ClitgError, match="does not exist"):
            operation("missing")
    with pytest.raises(ClitgError, match="does not exist"):
        profile_store.resolve("missing")
    with pytest.raises(ClitgError, match="does not exist"):
        profile_store.set_secret_reference("missing", "file:/x")
    with pytest.raises(ClitgError, match="does not exist"):
        profile_store.set_policy_file("missing", None)


def test_profile_secret_and_policy_updates(
    profile_store: ProfileStore, profile: Profile, tmp_path: Path
) -> None:
    profile_store.create(profile)
    updated = profile_store.set_secret_reference("personal", "file:/secret")
    assert updated.api_hash is None and updated.api_hash_ref == "file:/secret"
    view = profile_store.set_policy_file("personal", str(tmp_path / "policy.json"))
    assert view.policy_file and view.secret_storage == "file"


def test_invalid_profile_files(paths: Paths) -> None:
    store = ProfileStore(paths)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.profiles_file.write_text("not json")
    with pytest.raises(ClitgError, match="invalid"):
        store.list()
    paths.profiles_file.write_text(json.dumps({"profiles": []}))
    with pytest.raises(ClitgError, match="invalid"):
        store.list()


def test_login_lifecycle(state_store: StateStore) -> None:
    login = state_store.save_login("personal", "+1", "hash")
    loaded = state_store.get_login(login.login_id)
    assert loaded.phone_code_hash == "hash"
    state_store.delete_login(login.login_id)
    with pytest.raises(ClitgError, match="not found"):
        state_store.get_login(login.login_id)


def test_expired_login(state_store: StateStore) -> None:
    login = state_store.save_login("personal", "+1", "hash", ttl_seconds=-1)
    with pytest.raises(ClitgError, match="expired"):
        state_store.get_login(login.login_id)
    with pytest.raises(ClitgError, match="not found"):
        state_store.get_login(login.login_id)


def test_idempotency(state_store: StateStore) -> None:
    assert state_store.get_idempotent("p", "send", "key", {"x": 1}) is None
    state_store.save_idempotent("p", "send", "key", {"x": 1}, {"id": 2})
    assert state_store.get_idempotent("p", "send", "key", {"x": 1}) == {"id": "2"}
    with pytest.raises(ClitgError, match="different payload"):
        state_store.get_idempotent("p", "send", "key", {"x": 2})


def test_confirmation_lifecycle(state_store: StateStore) -> None:
    confirmation = state_store.issue_confirmation("p", "method", {"x": 1})
    state_store.consume_confirmation(confirmation.token, "p", "method", {"x": 1})
    with pytest.raises(ClitgError, match="expired"):
        state_store.consume_confirmation(confirmation.token, "p", "method", {"x": 1})
    with pytest.raises(ClitgError, match="invalid"):
        state_store.consume_confirmation("missing", "p", "method", {})


def test_confirmation_mismatch_and_expiry(state_store: StateStore) -> None:
    confirmation = state_store.issue_confirmation("p", "method", {"x": 1})
    with pytest.raises(ClitgError, match="does not match"):
        state_store.consume_confirmation(confirmation.token, "other", "method", {"x": 1})
    with closing(sqlite3.connect(state_store.path)) as connection, connection:
        connection.execute(
            "UPDATE confirmations SET expires_at=? WHERE token=?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), confirmation.token),
        )
    with pytest.raises(ClitgError, match="expired"):
        state_store.consume_confirmation(confirmation.token, "p", "method", {"x": 1})


def test_counts_and_prune(state_store: StateStore) -> None:
    state_store.save_login("p", "+1", "h")
    state_store.save_idempotent("p", "a", "k", {}, {})
    state_store.issue_confirmation("p", "m", {})
    assert state_store.counts() == {
        "logins": 1,
        "idempotency": 1,
        "confirmations": 1,
        "checkpoints": 0,
        "audit": 0,
    }
    future = datetime.now(UTC) + timedelta(days=1)
    assert state_store.prune("login", future) == {"logins": 1}
    deleted = state_store.prune("all")
    assert deleted == {
        "logins": 0,
        "idempotency": 1,
        "confirmations": 1,
        "checkpoints": 0,
        "audit": 0,
    }


def test_checkpoints_and_audit(state_store: StateStore) -> None:
    assert state_store.get_checkpoint("p", "agent") is None
    state_store.save_checkpoint("p", "agent", "cursor-1")
    assert state_store.get_checkpoint("p", "agent") == "cursor-1"
    state_store.save_checkpoint("p", "agent", "cursor-2")
    assert state_store.get_checkpoint("p", "agent") == "cursor-2"
    state_store.record_audit(
        "p",
        "messages.list",
        "request",
        target="1",
        ok=False,
        error_code="network",
    )
    rows = state_store.list_audit(1)
    assert rows[0]["target"] == "1" and rows[0]["error_code"] == "network"
    assert state_store.list_audit(None) == rows
    assert state_store.prune("checkpoint") == {"checkpoints": 1}
    assert state_store.prune("audit") == {"audit": 1}
