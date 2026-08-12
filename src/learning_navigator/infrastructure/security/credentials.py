"""API-key storage backed by the operating system credential vault."""

from __future__ import annotations

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
