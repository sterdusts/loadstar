"""API-key storage backed by a protected local credential vault."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Protocol


class CredentialStoreError(RuntimeError):
    """A safe error raised when the local credential vault is unavailable."""


class CredentialStore(Protocol):
    def get(self, *, user_id: str, profile_id: str) -> str | None: ...

    def set(self, *, user_id: str, profile_id: str, secret: str) -> None: ...

    def delete(self, *, user_id: str, profile_id: str) -> None: ...


class KeyringCredentialStore:
    """Store provider keys in Windows Credential Manager or the host keyring."""

    def __init__(self, service_name: str = "learning-navigator.ai") -> None:
        self.service_name = service_name

    @staticmethod
    def _account(user_id: str, profile_id: str) -> str:
        return f"{user_id}:{profile_id}"

    def get(self, *, user_id: str, profile_id: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(self.service_name, self._account(user_id, profile_id))
        except Exception as exc:
            raise CredentialStoreError(
                "The operating-system credential vault is unavailable."
            ) from exc

    def set(self, *, user_id: str, profile_id: str, secret: str) -> None:
        try:
            import keyring

            keyring.set_password(self.service_name, self._account(user_id, profile_id), secret)
        except Exception as exc:
            raise CredentialStoreError(
                "The API key could not be saved to the operating-system credential vault."
            ) from exc

    def delete(self, *, user_id: str, profile_id: str) -> None:
        try:
            import keyring
            from keyring.errors import PasswordDeleteError

            try:
                keyring.delete_password(
                    self.service_name,
                    self._account(user_id, profile_id),
                )
            except PasswordDeleteError:
                return
        except Exception as exc:
            raise CredentialStoreError(
                "The API key could not be removed from the operating-system credential vault."
            ) from exc


class FileCredentialStore:
    """Persist provider keys in a process-local JSON file with owner-only access.

    This adapter exists for headless Linux deployments where no desktop keyring
    session is available. The desktop product continues to use the operating
    system credential vault by default.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = threading.RLock()

    @staticmethod
    def _account(user_id: str, profile_id: str) -> str:
        return f"{user_id}:{profile_id}"

    def _read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CredentialStoreError("The server credential file could not be read.") from exc
        entries = payload.get("credentials") if isinstance(payload, dict) else None
        if not isinstance(entries, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in entries.items()
        ):
            raise CredentialStoreError("The server credential file has an invalid format.")
        return dict(entries)

    def _write(self, entries: dict[str, str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"version": 1, "credentials": dict(sorted(entries.items()))},
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                os.chmod(self.path, 0o600)
            finally:
                if temporary.exists():
                    temporary.unlink()
        except OSError as exc:
            raise CredentialStoreError("The server credential file could not be updated.") from exc

    def get(self, *, user_id: str, profile_id: str) -> str | None:
        with self._lock:
            return self._read().get(self._account(user_id, profile_id))

    def set(self, *, user_id: str, profile_id: str, secret: str) -> None:
        with self._lock:
            entries = self._read()
            entries[self._account(user_id, profile_id)] = secret
            self._write(entries)

    def delete(self, *, user_id: str, profile_id: str) -> None:
        with self._lock:
            entries = self._read()
            if entries.pop(self._account(user_id, profile_id), None) is not None:
                self._write(entries)


class MemoryCredentialStore:
    """Deterministic in-memory vault for tests and embedded deployments."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], str] = {}

    def get(self, *, user_id: str, profile_id: str) -> str | None:
        return self._secrets.get((user_id, profile_id))

    def set(self, *, user_id: str, profile_id: str, secret: str) -> None:
        self._secrets[(user_id, profile_id)] = secret

    def delete(self, *, user_id: str, profile_id: str) -> None:
        self._secrets.pop((user_id, profile_id), None)
