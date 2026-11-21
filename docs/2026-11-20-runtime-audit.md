# Local cleanup audit and frontend Pi recovery — November 20, 2026

This audit inspected local Git state, both existing room databases through read-only
SQLite connections, selected native-session metadata, and the installed Pi references.
It sent no model prompts. Both rooms were paused, had no queued/running/stopping
deliveries, and had unheld Studio locks during inspection.

## What should be kept

| Item | Finding | Decision |
|---|---|---|
| Stash `31b315e4f0a05f1cc73173530e9800c23d709abd` | Four-file frontend draft; 297 additions and 43 deletions. Its named functions and browser test remain represented in the integrated frontend, which also includes later repairs. It is not byte-identical to main. | Functionally superseded, but small and explicitly protected. Retain until the human explicitly discards it; do not apply it over current fixes. |
| `.worktrees/bootstrap/` | Separate repository at `b99a206`; its source commits are ancestors of root main. Its v0 room contains 104 messages and four native conversations. None of those message IDs occurs in the newer room. | Subsequently archived and removed after a fresh dependency check; preserve the private archive described below. |
| `integration/bootstrap` | Historical import label; no branch with this name remains. The imported commits remain in root main. | No branch cleanup is needed. Deleting a ref would never substitute for auditing the separate repository. |
| `/home/zengma/.codex/worktrees/9201/department-studio` | Listed in root's Git metadata as an external linked worktree. | Contents not inspected or modified, as requested. |
| `.worktrees/backend-tasks/` | Two commits beyond main: `2dcf7fd`, `54cf1a6`. | Keep unfinished/unintegrated task implementation. |
| `.worktrees/frontend-ongoing-tasks/` | Three modified frontend files and untracked `frontend/tasks.js`. | Keep unfinished work; these are real edits, including work retained after interrupted runs. |
| `live-demo/` | At the initial audit, v1 room: 121 messages and four native conversations, including the reported failures. | Keep as the actual current data directory. It is distinct from the bootstrap room. |

## Bootstrap cleanup follow-up

On November 20, the bootstrap checkout was retired after a fresh inspection. Its
source was clean, every Git ref was already integrated into root `main`, and Git
reported no unreachable objects. Root Git configuration and object storage did not
depend on that repository. The current v2 demo had no configured workspace or saved
native session under the bootstrap path. The old room was paused with no pending or
active deliveries; its Studio lock was held during backup and removal.

The private, git-ignored archive is
`artifacts/bootstrap-retirement-2026-11-20-bn0s_ut6/` (about 5.3 MiB, directory mode
0700). It contains the repository, all 104 old messages, four native session files,
build outputs and verification artifacts. An additional standalone SQLite backup,
file-hash manifest, checksums and `README.md` restore instructions are included.
Only the regenerable uv environment and Python/test/lint caches were excluded.

A complete temporary restore verified all 181 preserved files and their permissions,
the clean Git checkout and original HEAD, `git fsck --full`, every database table,
SQLite integrity, and all four saved native session files. Restore with
`tar --same-permissions` as documented so private directory and Git object modes
are preserved. The original directory was removed only after this verification and
a second unchanged-source/dependency check. Restoring to the original path preserves
native-session references; recreate its environment with `uv sync --locked` if needed.

The current demo was not restarted or reconfigured. The protected stash, external
linked worktree and unfinished department worktrees were outside this cleanup.

## Redundant checkouts and the cleanup limit

These six checkouts had clean source, no private runtime data, and no commits missing
from root main:

| Checkout under `.worktrees/` | Archived HEAD |
|---|---|
| `backend-deletion` | `988f71c` |
| `backend-rpc-robustness` | `816a9f9` |
| `frontend-activity-notifications` | `4f2dd68` |
| `frontend-delete-ui` | `9ad8e50` |
| `frontend-enter-send` | `bb36ec8` |
| `relaunch-integration` | `5a8690b` |

Verified source and verification artifacts for all six are archived in the private,
git-ignored directory `artifacts/audit-2026-11-20-loar0184/` (about 3 MB). The archives
exclude Git administrative files and regenerable uv/test caches. Their manifest records
heads, branches, archive hashes and individual file hashes. Existing feature branches
are retained.

Cleanup was attempted for `backend-deletion`. Git deleted the checkout files, then
failed to remove `.git/worktrees/backend-deletion` with **Read-only file system**.
All 55 archived source files were restored and verified, the linked checkout was
confirmed clean, and its environment was recreated with `uv sync --locked`. No other
checkout removal was attempted. All six registrations and checkouts remain.

The archive contains a guarded `cleanup.py`: it checks unchanged source/artifacts,
archive hashes, merged heads, stopped servers, and writable Git metadata before any
removal. Run from the root project in the normal terminal after stopping Studio:

```bash
uv run --locked python artifacts/audit-2026-11-20-loar0184/cleanup.py
# After inspecting the eligible list:
uv run --locked python artifacts/audit-2026-11-20-loar0184/cleanup.py --apply
```

The helper refuses changed or moved checkouts; re-audit them instead of forcing past
that check. It does not remove branches, drop the stash, prune all worktrees, or touch
the protected external worktree. To recreate an archived checkout later, use its saved
branch or commit with `git worktree add`, restore its archived source/artifacts, and
run `uv sync --locked` in that checkout.

## What happened to the frontend

The reported failures are in `live-demo/room.sqlite`, not the bootstrap database.
Frontend has **15 failed deliveries: ten acknowledgement timeouts and five generic
Pi failures**. It also has six earlier completed deliveries, so this is not evidence
that the provider never worked.

At inspection, frontend selected an external Pi provider/model, with workspace
`/home/zengma/department-studio/frontend`. Its retained conversation has used four
model IDs over time. Model changes preserve native history in this application, so
changing the selected model alone did not clear the accumulated conversation.

Concrete evidence on November 20, 2026 (timestamps below are UTC; add eight hours for
Shanghai):

- The native session has **23 user messages, 87 assistant messages, 98 tool results,
  five recovery context edits, and no successful compaction entries**.
- Studio appends a snapshot of the most recent 50 public room messages on each
  delivery, in addition to Pi's retained conversation. Recent prompt texts ranged
  from about 58,000 to 95,000 characters, including repeated room context.
- The last substantial working turn reported roughly 255,000 tokens at 08:13:44.
  The frontend run then reached the existing five-minute run deadline at 08:15:04.
- The five later generic failures correspond to native `stopReason: "length"`,
  each with only 16 output/reasoning tokens and no completed public reply.
  At **08:49:36**, provider-reported input plus cache tokens were **571,755**, and
  total tokens were **571,771**. The inspected local catalog declares a
  **272,000-token context window** for the selected model. This is reported native
  usage, not an independent tokenizer measurement or proof of the provider's true limit.
- For the **08:48:12–08:48:23** timeout, the native user message was appended at
  08:48:23.214, followed by an aborted assistant message at 08:48:23.235. The room
  delivery finished at 08:48:23.549 with unknown prompt acceptance. Similar earlier
  attempts also appended input immediately before interruption.

Installed Pi is `@earendil-works/pi-coding-agent` **1.5.2**. Its matching source calls
`_checkCompaction` inside `_prepareRun`, before `_startRun` reports prompt acceptance;
the RPC response is emitted from that acceptance callback. Compaction can perform a
model request before the host receives the prompt acknowledgement. The installed
`docs/compaction.md`, `docs/rpc-commands.md`, and `docs/json.md` describe this lifecycle.
The version-matched `agent-session.ts` and `rpc-mode.ts` were also inspected.

The evidence strongly supports this sequence: accumulated context needs compaction;
the ten-second acknowledgement timer can interrupt that pre-prompt work; an attempted
request can still be appended during shutdown; further requests add more history;
eventually the model produces token-limit endings and recovery does not persist a
successful compaction. Historical raw RPC compaction events were not retained, so the
precise compaction failure for each old timeout cannot be reconstructed. No missing-key
or authentication error was found in these frontend endings. The generic error text
previously hid the actual `length` stop reason.

## Initial diagnostic source fix

- A real `compaction_start` event can extend the pending prompt response wait once,
  using the remaining existing run budget. Ordinary command acknowledgements and
  blocked input writes keep their ten-second limit; the five-minute supervisor remains.
- Compaction progress, failure, and interruption have fixed public diagnostics.
  Native summaries, provider errors, thinking, credentials and raw tool output are
  not copied to the room.
- A settled `length` ending reports a token-limit failure and conversation recovery
  guidance. Failed compaction is distinguished when its event is available. A Pi
  recovery that ultimately produces a valid final reply can still complete normally.
- Missing acknowledgement remains acceptance-unknown. There is no new automatic
  prompt retry, session reset, permission change, or change to clear-queue/abort and
  confirmed-stop behavior.

New subprocess regressions initially produced **five failures and three passes**.
After implementation, **203 ordinary tests passed**, with 12 browser tests deselected;
Ruff lint/format checks, JavaScript syntax, six Node bridge tests, and diff checks
passed. Tests use synthetic runtimes and temporary data. Browser tests were not rerun
for this backend-only change. No live model call or service restart was performed.

## Recover the existing demo with Resume

The initial diagnostic patch above did not repair already oversized native history.
The user's subsequent request is implemented in
[context maintenance on Resume](resume-context.md): each enabled department is checked
before the room unpauses. Healthy context is retained, large context is compacted,
and unrecoverable context gets a fresh conversation with a bounded room handoff.
Old session references and workspace files remain. Changing the workspace or deleting
SQLite/native sessions is not required.

Every delivery now includes bounded incremental public context instead of another
full 50-message snapshot. The current input and originating human request remain
complete. Compaction and fresh-context fallback never replay a previous request.

Back up the actual persistent data directory with Studio stopped, then relaunch the
root source with the same current data path and the configured model catalog/runtime setup.
The updated server migrates the database to schema v3; keep the backup if you need
to revert to older source.

```bash
cd /home/zengma/department-studio
uv sync --locked
PI_CODING_AGENT_DIR=/home/zengma/.pi/agent \
  uv run --locked department-studio \
  --data-dir /home/zengma/department-studio/live-demo
```

Open the newly printed private launch URL. Click **Resume room** and wait for
**Room running**. Each department card reports compaction or fresh context as needed.
Then explicitly send one small status request, inspecting retained work before asking
it to continue. The running backend must be restarted; refreshing the browser cannot
load these backend changes. No live model call or production restart was performed
during implementation and deterministic verification.
