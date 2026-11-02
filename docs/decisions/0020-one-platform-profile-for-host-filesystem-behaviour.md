# 0020 — One platform profile for host filesystem behaviour

- **Status:** accepted
- **Date:** 2026-11-02
- **Context:** `core/platform.py`, `TRALALA_PLATFORM_PROFILE`, `storage/board_db.py`,
  `services/{boards,attachments,backups}.py`, `core/security.py`, `app/dev_reset.py`

## Problem

Deleting a file means two different things. Windows refuses to remove a file another process holds
open (`WinError 32`), so an antivirus scanner, the search indexer or a backup agent could make a board
deletion fail halfway and leave a registry row pointing at a half-removed directory. POSIX removes the
name and keeps the open file alive as an anonymous inode, so the same call succeeds and a concurrent
writer silently writes into nothing. A network share adds a third behaviour: `EBUSY`/`ENOTEMPTY` that
clear on their own.

The code had three separate answers to this: `os.name == "nt"` in `process_lock.py`, a comment in
`security.write_private_file`, and a bare `shutil.rmtree(..., ignore_errors=False)` in three places.
Nothing named the decision, so a fourth place could pick a fourth answer.

## Decision

**One profile, one module, one setting.** `core/platform.py` exposes `resolve_profile`,
`transient_error` and four operations (`remove_tree`, `remove_file`, `replace_file`, `copy_file`,
plus `retry_io` for a caller with its own operation). `Settings.platform_profile` reads
`TRALALA_PLATFORM_PROFILE` with `auto` (the default), `windows`, `posix` or `network`; an unknown
value fails at startup rather than silently falling back.

1. **The profile selects policy, never mechanism.** The lock primitive (`msvcrt` vs `fcntl`) and
   `chmod` still follow the real operating system, because a wrong guess there breaks locking
   outright. The profile answers one question: *which errors can clear on their own?*
   - `windows`: `WinError` 5, 32, 145 — a held file, a denied handle, a directory not yet empty.
   - `posix`: `ENOTEMPTY`, `EBUSY`, `EAGAIN` — a network mount can be briefly busy; a local open file
     never is, because POSIX does not object.
   - `network`: POSIX policy; use it when the data directory is on NFS/SMB.
2. **Permanent errors are never retried.** `EACCES`, `EPERM`, `EROFS` and a missing owner fail on
   the first attempt. A retry would only delay an error the operator must fix.
3. **A removal that still fails names what is left.** `BoardService.delete` answers
   `409 board_files_busy` with `details.leftover` (`boards/{id}`, relative — never an absolute path),
   `errno`, `winerror` and `platform_profile`. The registry row survives on purpose: the board still
   has its data, and a retry works once the file is released.
4. **Everything that reads or removes a board file goes through the module**: board deletion, the
   backup directory, duplicate, export and backup archiving, attachment upload (atomic replace),
   attachment delete, backup pruning, the development reset, and the secret file's permissions.

## Consequences

- Adding a fourth host behaviour is an edit in one file plus one enum value, not a search for
  `os.name`. `process_lock.py` now asks `platform.lock_primitive()` instead of testing `os.name`
  itself, so the module is the only place that knows the host.
- A busy file produces an actionable, portable error instead of an unhandled 500, and it cannot cost
  the board its data.
- `network` is a claim the operator makes. On a local disk it changes nothing (the retries simply
  never trigger); on a share it turns a spurious failure into a wait. It does *not* make SQLite's WAL
  mode safe on a share — a live board belongs on local disk.
- The retry masks nothing: after the attempts are spent the original error is raised, with its
  `errno`/`winerror` intact.
- Deployment configuration now includes one value that describes the host. It is read from the
  environment, not from the registry, because it must be known before any database is opened — and
  `app/dev_reset.py` deletes the registry.
- Archive member names are now validated by one helper (`services/common.archive_file_name`) that
  rejects dot entries and any backslash: Windows treats `\` as a path separator and POSIX does not, so
  a name that is harmless on one host is a traversal on the other.

## Alternatives considered

- **A flag in `registry.sqlite`.** Rejected: the profile is needed before the registry is open (dev
  reset, startup recovery) and it describes the *host*, not the tenant's data. Registry values are
  also copied with a data directory, which would carry a Windows profile to a Linux host.
- **Detect only, with no override.** Rejected: the container image, a bind-mounted share and a CI
  runner cannot be described by `os.name` alone.
- **Retry everything a few times.** Rejected: it would turn an unfixable permission error into a
  10-second pause before the same failure, and hide a misconfigured data directory.
- **`ignore_errors=True` on removal.** Rejected outright: it is what made a partly deleted board look
  deleted.

## Verification

`backend/tests/test_platform_profile.py`: auto-detection, explicit and invalid profiles, the
transient/permanent split per profile, a transient lock that clears on the third attempt, a permanent
error that is attempted exactly once, idempotent removal of what is already gone, and a busy board
directory that keeps the board, returns `409 board_files_busy` with the relative leftover, and
succeeds on retry.
