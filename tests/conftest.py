from __future__ import annotations

from pathlib import Path

import pytest

from clitg.models import Profile
from clitg.storage import Paths, ProfileStore, StateStore


@pytest.fixture(autouse=True)
def isolate_clitg_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep developer credentials from changing test behavior."""

    for name in (
        "CLITG_API_HASH",
        "CLITG_API_ID",
        "CLITG_CODE",
        "CLITG_PASSWORD",
        "CLITG_PHONE",
        "CLITG_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data")


@pytest.fixture
def profile_store(paths: Paths) -> ProfileStore:
    return ProfileStore(paths)


@pytest.fixture
def state_store(paths: Paths) -> StateStore:
    return StateStore(paths)


@pytest.fixture
def profile() -> Profile:
    return Profile(name="personal", api_id=12345, api_hash="secret", phone="+15551234567")
