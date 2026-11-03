"""The data directory's own files, as the services see them.

On a first start without a chosen password, ``AuthService.bootstrap_admin`` writes the generated
administrator password to ``<data>/.bootstrap-password`` (``BOOTSTRAP_PASSWORD_FILE_NAME``). The
file is a delivery mechanism, not a credential: the bootstrap account's first password change
removes it, and an administrator is told while it is still there. The storage layer implements the
Protocol over the data directory; a unit test uses an in-memory fake, so no test touches the disk.
"""

from __future__ import annotations

from typing import Protocol


class BootstrapPasswordFile(Protocol):
    """``<data>/.bootstrap-password``, which holds the generated first administrator password."""

    def present(self) -> bool:
        """Whether the file is in the data directory."""
        ...

    def remove(self) -> bool:
        """Delete the file; ``False`` when it was already gone. ``OSError`` if the host refuses."""
        ...
