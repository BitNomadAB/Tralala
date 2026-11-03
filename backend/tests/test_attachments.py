"""Attachments: the display name kept for an upload, and the bytes that must match its type."""

from __future__ import annotations

import pytest

from app.services.attachments import ALLOWED_TYPES, sanitize_filename, sniff_matches


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("x/y/z.md", "z.md"),
        (".env", "env"),
        ("", "attachment"),
        ("...", "attachment"),
        (None, "attachment"),
        ("report<script>.pdf", "report_script_.pdf"),
        ("Résumé final (v2) [draft].docx", "R_sum_ final (v2) [draft].docx"),
        ("  spaced name.txt  ", "spaced name.txt"),
        ("\x00evil.txt", "_evil.txt"),
    ],
)
def test_an_upload_keeps_a_safe_display_name(raw: str | None, name: str) -> None:
    assert sanitize_filename(raw) == name  # type: ignore[arg-type]
    assert sanitize_filename(raw) == name  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw", ["..\\..\\boot.ini", "C:\\Users\\someone\\a.txt", "/abs/path/.hidden", "a/../../b"]
)
def test_a_display_name_never_carries_a_path_on_any_host(raw: str) -> None:
    name = sanitize_filename(raw)
    assert "/" not in name and "\\" not in name
    assert not name.startswith(".")
    assert name


def test_a_long_name_is_cut_to_two_hundred_characters() -> None:
    assert sanitize_filename("a" * 300 + ".txt") == "a" * 200


@pytest.mark.parametrize(
    ("extension", "data", "expected"),
    [
        (".png", b"\x89PNG\r\n\x1a\nrest", True),
        (".pdf", b"\x89PNG\r\n\x1a\nrest", False),
        (".pdf", b"%PDF-1.7", True),
        (".jpg", b"\xff\xd8\xff\xe0", True),
        (".jpeg", b"GIF89a", False),
        (".gif", b"GIF87a", True),
        (".docx", b"PK\x03\x04", True),
        (".xlsx", b"%PDF-1.7", False),
        (".ppt", b"\xd0\xcf\x11\xe0", True),
        (".txt", "plain text, åäö".encode(), True),
        (".md", b"\xef\xbb\xbf# With a BOM", True),
        (".json", b"\xff\xfe\x00broken", False),
        (".exe", b"MZ", False),
        (".svg", b"<svg/>", False),
    ],
)
def test_the_bytes_must_match_the_declared_type(
    extension: str, data: bytes, expected: bool
) -> None:
    assert sniff_matches(extension, data) is expected


def test_every_allowed_type_has_a_content_check() -> None:
    """An allowed extension without a sniffing rule would accept any bytes, or none."""
    samples = {
        ".docx": b"PK\x03\x04",
        ".pptx": b"PK\x03\x04",
        ".xlsx": b"PK\x03\x04",
        ".ppt": b"\xd0\xcf\x11\xe0",
        ".pdf": b"%PDF",
        ".txt": b"text",
        ".md": b"text",
        ".json": b"{}",
        ".jpg": b"\xff\xd8\xff",
        ".jpeg": b"\xff\xd8\xff",
        ".png": b"\x89PNG\r\n\x1a\n",
        ".gif": b"GIF89a",
    }
    assert set(samples) == set(ALLOWED_TYPES)
    for extension, sample in samples.items():
        assert sniff_matches(extension, sample) is True, extension
        assert sniff_matches(extension, b"\x00\xff\xfe nothing") is False, extension
