# Release notes

What changed for someone running Tralala, newest first. Architecture and API detail lives in
[Architecture.md](Architecture.md) and [API.md](API.md); this page is the short version a person needs
before upgrading.

## Unreleased

First release on the Loop schema. Read these three lines before importing anything from an older
installation.

- **Data from before the Loop schema is not migrated.** A board database that still holds the old
  lists and cards refuses to upgrade and names the development reset command instead. There is no
  preservation path and none is planned. Export what you need from the old installation before you
  upgrade.
- **Board archives are format 2 only.** An archive exported by a pre-Loop build is rejected with
  `422 validation_failed` ("Unsupported board archive format") rather than half-imported.
- **One Python version.** 3.13 is the version of record — container image, CI's primary job and the
  documented setup. 3.14 is tested too; newer interpreters are refused by `install` rather than
  silently accepted.

Worth knowing when you look at the dashboard:

- **Board counters are cached**, because they live in each board's own database. A write through the
  app refreshes them immediately; a board file changed behind the app's back can show a number up to
  `TRALALA_BOARD_COUNTS_CACHE_SECONDS` (default 60) old. `GET /boards?with_counts=false` skips the
  counters entirely.
- **The web tier is Caddy**, not nginx: TLS, HTTP/2 and the body limit come from
  `frontend/Caddyfile`, and `TRALALA_SITE_ADDRESS` decides whether Caddy serves plain HTTP on `:80`
  or gets a certificate.
- **An open tab reloads itself once after an upgrade.** Each page is downloaded when it is first
  opened, so a tab left open across an upgrade asks for files the new version no longer has. It
  reloads once to pick up the new version instead of failing; if the page still cannot be loaded, it
  shows an error with a Reload page button rather than reloading again.
- **A bad board archive is refused, not half-imported.** An archive whose `board.sqlite` is not a
  sound board database answers `422 board_import_invalid` and leaves nothing behind; before, it left
  a board in `error` that broke the board list and the next start. A board whose file cannot be read
  is now skipped by the list and at startup (`board_database_unreadable`).
- **A backup that fails SQLite's checks is not restored.** A restore now also runs
  `foreign_key_check` on the snapshot, and any refusal answers `422 board_backup_invalid` (was
  `422 validation_failed`) with `details.reason` and `details.detail`; the board keeps its database.
  Before, a snapshot with a broken key replaced the board and was only reported afterwards.
- **A held file no longer half-deletes a board.** Host filesystem behaviour follows
  `TRALALA_PLATFORM_PROFILE`, and a board delete that cannot remove its files answers
  `409 board_files_busy` with the leftover directory.
- **A search for nothing but spaces no longer fails.** In a Loop's search a blank `q` is no text
  filter, as an empty one always was, whether or not the board has its full-text index; the
  App-wide search answers it with `422 validation_failed`. Both answered 500 on a board with the
  index. Spaces around the words are ignored by both search engines.
- **A taken label name answers 409.** Renaming a label to a name another label has answered 500;
  it now answers `409 label_name_taken` with `details.name`, and so does creating one, which
  answered `422 validation_failed` — the same answer every other taken name gets.
- **A board whose file cannot be read can be archived, and then deleted.** Archiving it answered
  `503 board_database_unreadable` (or `503 board_schema_outdated`) although the board was already
  archived; it now answers 200. Only the board's own activity entry for the archive is missing, and
  the backend log records that (`skipped: board_archived_activity`).
- **A mistyped current password no longer signs you out.** Changing your password with the wrong
  current one answered `401 invalid_credentials`, which the web client takes as the end of the
  session, so the tab went to the sign-in page although the session was fine. It now answers
  `422 invalid_credentials`: the form says the current password is incorrect and you stay signed
  in. An API token calling `POST /auth/password` gets `403 forbidden` (was 401).
- **The agent form follows the provider you pick.** A preset now fixes the endpoint for hosted
  providers, asks for the key only where one is needed, and says which providers need a model name at
  all — so a local Ollama install is not asked for a key and OpenAI cannot be saved without one.
  **Test connection works before saving**: nothing is written until the test passes, and the raw JSON
  answer is shown as it came back. A model on your own network can be marked **no key**, and then no
  `Authorization` header is sent — an explicitly ticked box beats a key stored earlier on the agent.
- **The connection test also calls the model.** It used to check only that the endpoint answered;
  a wrong model name passed the test and failed the first generation. It now sends one real
  completion, reports the provider's sentence when that is refused, and offers the model names
  it found as suggestions.
- **A provider that can hold an answer to a schema is asked to.** The connection test's completion
  asks for the answer in a fixed JSON shape and records whether the model managed it
  (`supports_json_schema`). Analysis, RoadMap and QA runs on such an agent then send their schema
  the same way, so fewer answers need a repair round; a provider that refuses is asked again
  without it. Existing agents start without the flag: test the connection once to set it.
- **The connection test also finds out whether the model calls tools.** After the completion it
  makes one more small call that offers a dummy tool and records whether the model called it
  (`supports_tools`); Settings lists such an agent as "reads repositories with tools" and a tested
  agent without it as "no tool calling". A model that answers in text or a provider that refuses
  tools never fails the test. Existing agents start without the flag: test the connection once, and
  again after changing an agent's model. The flag decides how a run reads the code (next entry).
- **A model that calls tools reads the code itself.** An analysis or RoadMap run on an agent with
  the flag no longer gets a fixed selection of files: the model gets the list of files at the run's
  commit and lists, reads and searches the board's repositories through three read-only tools, as
  often as it needs; the run ends when it answers, and the answer gets the same schema check and
  repair rounds. The limits are settings: `TRALALA_GENERATION_TOOL_STEPS` (60 tool calls per run),
  `TRALALA_GENERATION_TOOL_RESULT_CHARS` (60 000 characters per answer, a longer file in parts) and
  `TRALALA_GENERATION_CONTEXT_CHARS` for the whole conversation, within which the oldest answers
  are set aside first. Nothing from a repository is run or written. Such a run makes several provider
  calls instead of one, so it takes longer and costs more on a hosted provider. An A2A agent, an
  agent without the flag and a provider that refuses the tools at run time still get the fixed
  snapshot. See [Repositories.md](Repositories.md#how-a-run-reads-the-code).
- **A run shows how it was made.** Every analysis, RoadMap and QA run records its steps in plain
  words as they happen: the documents it read, each repository it opened or sent, every tool call
  with a one-sentence summary, the model's answer, each repair round and every limit it reached. The
  run panel shows them as a growing list grouped by stage, during the run and afterwards, and the
  API answers them as `trace` on the run. No step holds a file's content.
- **An analysis can read the code, within stated limits.** When a board links repositories, analysis
  and RoadMap runs read the branch head's commit. A model without tools gets a snapshot — at most
  200 files and 200 KB of text per repository, filtered for what informs a decision. A file that does
  not fit is skipped and the next one read, where one large file early in the order used to end the
  selection, and a manifest of every file, marked sent or not, keeps the model from reporting an
  unsent file as missing. The prompt names the caps and the commit, and the Loop's document dialog
  line says which commit the last run used and how many files it read. A repository that cannot be
  read is reported next to it, not hidden. A commit's archive may be up to
  `TRALALA_REPOSITORY_ARCHIVE_MAX_BYTES` (default 128 MiB) from GitHub as from a mirror; the GitHub
  download used to stop at 2 MB.
- **A failed generation now says why.** A provider rejection used to read only "HTTP 400", and the
  message lived in a toast that disappeared; the Loop's document dialog shows the last run for the
  purpose, with the provider's own sentence, until it is retried.
- **Generation shows where it is, and where it failed.** A second panel beside the documents dialog
  lists the run's stages — *Reading the Loop's documents*, *Reading the repository*, *Writing the
  analysis* (or *RoadMap*), *Checking the answer* and *Saving* — with its steps under each (see "A run
  shows how it was made"). A stage is only ticked when it produced what its name says: the repository
  stage is *skipped* when the board links no enabled repository, instead of claiming the model read
  code it never received. A failure marks the stage it died on and keeps the provider's answer there
  as JSON until it is dismissed. *Generate* is locked and glows while a run is in flight.
- **A scope can be reset.** The red *Reset* button at the bottom-left of the Analysis and RoadMap tabs
  clears the document and any approval behind it — a draft as well as an approved one — so the work
  has to be generated again; it asks first, because the text is retired rather than edited. This is a
  person's action and rejects agent tokens like any other approval decision.
- **A discussion is capped at four rounds** per run, with default token and time budgets
  (`TRALALA_DISCUSSION_TOKEN_BUDGET`, `TRALALA_DISCUSSION_TIME_BUDGET_SECONDS`). There is no
  per-token rate limit. See
  [Security_defaults.md](Security_defaults.md#accepted-risks-on-purpose).
- **A discussion lives in its Ticket.** **Ask the agents** in a Ticket's Activity (or its More
  actions) asks the question and runs one round, and the Ticket's new **Discussions** tab lists its
  discussions. A discussion opens in the Ticket's dialog or as a page of the Ticket and leads with
  its sign: Tralala's verdict in one word and one sentence, then one row per agent with its
  position and one recommendation. The reasoning, the transcript and the runs are **Raw text**.
  **Ask again**, **Let them talk it out** and **Stop** replace the old run controls. See
  [Ask the agents](Loops.md#ask-the-agents).
- **An agent's answer is held to a person's limits.** A recommendation is one sentence of at most
  20 words, each list at most three points of at most 140 characters, with no file name, code or
  id; an answer that breaks them is sent back once and otherwise kept as prose with the position
  `unclear`. Answers stored earlier are read as they are. The server logs a repair as
  `discussion_answer_repair` and a give-up as `discussion_answer_prose`.
- **Regenerate RoadMap.** A RoadMap can be written again from its review with the feedback field as
  the run's instructions, also after it was approved. A new revision after an approval waits for a
  new review (it used to count as stale, and nothing could approve it without a reset first). When
  the new plan is published, the earlier plan's Tickets that nobody touched are removed from the
  Kanban; those somebody worked on stay, and the Loop's activity lists both.
- **A Loop's plan is the one in force.** A RoadMap written again from scratch left the Phases and
  Tickets of the earlier draft in the Loop, so the dashboard's **Waits for you**, the Loop's Phases and
  a worker's `loop_summaries` and `read_loop` counted both (39 Tickets where the Kanban held 20, two
  Phases numbered 1). They now read the active plan alone. The earlier rows stay stored and a Ticket
  key is never used twice, so the new plan's keys go on from the old ones.
- **Archived boards say so.** The dashboard's heading and a board's chip read **Archived** instead
  of Read only.
- **Reset RoadMap is a button again.** It sits beside the RoadMap's review as **Reset analysis**
  does beside the analysis's, instead of in a menu next to the approve button that nobody found.
- **The RoadMap for people is its goal and the number of Tickets.** The brief above the Phases no
  longer retells the order of work, the person's part and what could block the plan, which the
  Phases and their Tickets under it already show. The board agent or a worker writes one line of at
  most 20 words, what is true when the plan is done, and the review counts the Tickets beside it. A
  RoadMap brief written earlier shows only its summary.
- **The analysis brief is asked for more plainly.** The schema the writer is shown, a board agent's
  and a worker's `write_brief` alike, now requires the size and the verdict line, which the sign
  always demanded, and the board agent's request ends with the findings its items must name. A model
  that followed the schema left the size out and the brief failed with `brief_invalid`. Briefs stored
  earlier are read as they are.
- **New Loop asks for a name only.** The goal is written into the Loop's **Info**, which the
  analysis reads and which its plain-language brief explains, so the dialog no longer asks for it a
  first time. **Edit Loop** still edits a goal, and a worker's `create_loop` still sets one.
- **Archived boards sit apart.** The dashboard lists an archived board under **Archived**, below
  **Your boards**, and the status filter no longer offers Archived.
- **An archived board's discussions wait for nobody.** The Discussions inbox and the dashboard's
  **Waits for you** leave them out: a decision on an archived board is refused, so they are read
  on the board's Tickets.
- **The Discussions page is an inbox.** It lists every board's discussions under **Waits for your
  decision**, **Agents are talking** and **Decided**, and the dashboard's **Waits for you** lists
  the discussions that wait for a decision. A discussion starts from a Ticket only, so the page no
  longer opens one. `GET /discussions/overview` is gone; a client reads `GET /discussions/inbox`
  instead, and `GET /boards/{board_id}/discussions` takes `card_id`. See
  [API.md](API.md#discussions).
- **Every backend log line has the same frame.** Each line is a JSON object with `ts`, `level`,
  `event`, `logger` and `request_id`, then the event's fields, and every line written while a request
  is served carries that request's id — not only the `http_request` line. A logged exception keeps
  its traceback in `exc_info`, `TRALALA_LOG_LEVEL` sets the lowest level written, and
  `backup_created` names the snapshot file `backup_name` (was `name`). See
  [Troubleshooting.md](Troubleshooting.md#reading-the-backend-log).

Known limitations are listed in [Security_defaults.md](Security_defaults.md) and in the operational
notes of [Architecture.md](Architecture.md#operational-notes).
