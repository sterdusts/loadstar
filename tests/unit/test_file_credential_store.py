from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from learning_navigator.infrastructure.security.credentials import (
    CredentialStoreError,
    FileCredentialStore,
)


def test_file_credential_store_persists_and_deletes_owner_scoped_secrets(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vault" / "credentials.json"
    store = FileCredentialStore(path)

    store.set(user_id="user-a", profile_id="profile-1", secret="secret-a")
    store.set(user_id="user-b", profile_id="profile-1", secret="secret-b")

    reopened = FileCredentialStore(path)
    assert reopened.get(user_id="user-a", profile_id="profile-1") == "secret-a"
    assert reopened.get(user_id="user-b", profile_id="profile-1") == "secret-b"
    reopened.delete(user_id="user-a", profile_id="profile-1")
    assert reopened.get(user_id="user-a", profile_id="profile-1") is None
    assert reopened.get(user_id="user-b", profile_id="profile-1") == "secret-b"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_file_credential_store_rejects_malformed_content(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"credentials": ["not-a-map"]}), encoding="utf-8")

    with pytest.raises(CredentialStoreError, match="invalid format"):
        FileCredentialStore(path).get(user_id="user", profile_id="profile")
