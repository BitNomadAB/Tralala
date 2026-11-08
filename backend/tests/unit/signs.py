"""The parts of the analysis brief's sign a brief written before it lacks, for the brief fixtures.

Every analysis brief handed in or generated keeps the sign
(``services/loop_documents_human_limits``): a fixture spreads ``SIGN`` into its brief and sets its
own fields after it.
"""

from __future__ import annotations

from pydantic import JsonValue

SIGN: dict[str, JsonValue] = {
    "verdict_line": "Yes, once the e-mails that never arrive are handled.",
    "size": {"kind": "small", "text": "One change to sign-in and one new e-mail."},
}
