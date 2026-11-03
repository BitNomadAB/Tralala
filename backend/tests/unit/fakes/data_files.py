"""The data directory's own files in memory, for the services that read or remove them."""

from __future__ import annotations

from dataclasses import dataclass

from app.repositories.data_files import BootstrapPasswordFile


@dataclass(slots=True)
class FakeBootstrapPasswordFile:
    """Whether the generated password file is there, and how often removing it was asked for.

    ``refusal`` is what the host raises on removal (a file another program holds open), as the
    real file would; the file then stays.
    """

    exists: bool = False
    refusal: OSError | None = None
    removals: int = 0

    def present(self) -> bool:
        return self.exists

    def remove(self) -> bool:
        self.removals += 1
        if self.refusal is not None:
            raise self.refusal
        removed, self.exists = self.exists, False
        return removed


def fake_is_a_bootstrap_password_file(fake: FakeBootstrapPasswordFile) -> BootstrapPasswordFile:
    """Never called: pyright proves the fake fits the Protocol ``AuthService`` takes."""
    return fake
