# Ralph iteration prompt

You are one iteration of the Ralph Loop for the Tralala project. Each iteration starts
with fresh context; repository files, git history and `.ralph/` are your only memory.

## Procedure

1. Read `AGENTS.md` completely.
2. Read `.ralph/prd.json` and select the highest-priority story whose `status` is `pending` and
   whose `depends_on` stories are all `done`.
3. Read the last 20 entries of `.ralph/progress.txt`.
4. Inspect `git log --oneline -20` and `git status` to understand current state.
5. Implement **only** that story. Do not refactor unrelated code.
6. Add or update tests that prove the acceptance criteria.
7. Run the validation commands from `prd.json` that apply to the story. If validation fails:
   - fix the current story, or
   - record the failure in `.ralph/progress.txt` and leave the story `pending`.
   Never mark a story `done` on a failing validation.
8. Review `git diff` for unintended changes and secrets.
9. Commit with a message referencing the story id.
10. Append a progress entry describing changes, validation output summary and follow-ups.
11. Exit. The next iteration starts with fresh context.

## Hard rules

- One story per iteration. Never batch unrelated stories.
- Never bypass the service layer, never write to SQLite files from API code.
- Never weaken authentication, scopes, CSRF or path validation.
- Never edit released migrations; add a new migration.
- If a requirement is ambiguous, choose the simplest implementation consistent with the spec and
  record the decision in `docs/decisions/`.

## Current focus

All stories through KAN-082 are `done`; KAN-083..KAN-089 are `pending`. Pick the lowest pending id
whose dependencies are `done`. Next up is KAN-083 (escalate a comment into a discussion), then the
attachment UI (KAN-084) and clipboard screenshots (KAN-085).
