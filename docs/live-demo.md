# Live collaboration demo

This guide prepares a real, user-directed conversation through Department Studio.
It does not create departments, select models or run inference automatically.
Choose two departments, their runtimes, exact models and workspaces in the UI.

The current code has a Studio-owned model catalog and Pi/Claude Code/DeepSeek
Harness adapters. The new Claude Code and DeepSeek Harness adapters have only been
tested against fixture processes; this guide is the acceptance path for a live run.
No live inference or restart of a persistent room was performed while implementing
the adapters. A bounded attempt on 2026-11-21 did **not** pass: Pi's default config
directory was read-only, the configured DeepSeek key returned HTTP 401, and the
Claude smoke run did not finish. See [runtime abstraction](runtime-abstraction.md)
for the contract and [verification](verification.md) for the automated evidence and
blockers.

## Before you start

1. Install at least one runtime executable: `pi`, `claude` or `dsh`.
2. Export the API key named by the catalog. The bundled catalog uses
   `DEEPSEEK_API_KEY` for DeepSeek V4 Flash and V4 Pro.
3. Stop any previously running Studio process that uses the same data directory.
4. Back up the entire private data directory and native sessions. Schema v3 is
   additive, but there is no downgrade procedure.

Example:

```bash
cd /path/to/department-studio
export DEEPSEEK_API_KEY=...   # never commit or paste this into the room
uv sync --locked
uv run department-studio \
  --data-dir "$PWD/live-demo" \
  --models-config /path/to/models.toml   # optional; omit for the bundled catalog
```

Open the printed URL, including its `#token=...` fragment. Each restart generates
a new launch credential. The room starts paused and restores the selected project,
configuration and messages; it never replays interrupted work.

The first launch adopts an existing root room as **My first project** and migrates
it to schema v4. Open **Project history** to create a separate verification project
if you do not want to edit the existing departments. Switching projects stops the
current room before opening the target. Deleting a project removes only Studio data,
never the workspace.

The bundled catalog is `backend/src/department_studio/default_models.toml`. A custom
catalog must use `api = "openai-completions"`; see the
[schema](runtime-abstraction.md#model-catalog). Keys belong in the environment, not
in the file. The browser never receives them.

## Configure the two departments

For each department:

1. Click **Add department** and enter your own name, handle and role.
2. Choose an existing workspace with **Browse folders** and **Use this folder**.
3. Choose the **Agent runtime**. The dialog reports a runtime that is not installed;
   it does not silently substitute another one.
4. Click **Load models** and choose an exact model. Listing reads the catalog only;
   it does not contact a provider or start a runtime.
5. Keep **Discuss** for this demonstration. Do not enable Develop.
6. Save both departments while the room is paused.

There is no default department, runtime or model. A saved model that is no longer
in the catalog is shown as missing and must be replaced before saving or running.
This is the fail-closed behavior that replaced the former external provider
selection.

## Verify the new room surfaces

Before starting inference, verify the non-model surfaces:

1. **Project history:** create a named project and confirm it opens empty and paused;
   switch back to the original project and confirm its departments/history remain.
2. **Records:** open **Records** for each project. The folder is separate per project.
   Create one Markdown note as the human. Agents can list/read/append records through
   the bridge; a successful agent record should appear in this panel and be referenced
   by exact path in the room, not pasted in full.
3. **Hierarchy:** open **Department hierarchy**. The default is a complete graph.
   Click a line to disconnect it; click two departments to reconnect them. This only
   restricts agent-to-agent addresses, not the human.
4. **Default addressing:** after an explicit `@FIRST_HANDLE` message, a message with
   no mention should preview **Continuing with @FIRST_HANDLE**. Tick **Don’t continue
   the previous addressees** to send a public note instead.
5. **Theme:** toggle light/dark. With no explicit choice the page follows the system
   preference; an explicit choice persists in this browser.

None of these checks requires a model turn.

## Send one explicit collaboration request

Sending the following request starts live inference with the selected runtimes and
models. If an assistant is operating the demo for you, explicitly authorize that
bounded live request after confirming the departments and models.

1. Click **Resume room** and wait for **Room running**. For Pi, Resume may compact
   large history; Claude Code and DeepSeek Harness own their native compaction.
2. Send an ordinary note such as `We are checking the Department Studio room.`
   It should appear with no new delivery.
3. Replace `FIRST_HANDLE` and `SECOND_HANDLE` below with your handles. Use the
   second handle without `@` inside the recipient array.

```text
@FIRST_HANDLE We are demonstrating real department-to-department communication
about Department Studio. Use the room message tool exactly once with recipients
["SECOND_HANDLE"]. Ask that department for one observable acceptance check proving
that renaming a department preserves its identity and historical attribution.
Ask it to answer in its public final response, under 120 words, without forwarding
the request to anyone else. Your own final response should briefly state what you
asked; do not wait synchronously for the other department. Use only the room
message tool for this request. Do not edit files or run shell commands.
```

The room message tool is `send_room_message` for Pi and
`mcp__room__send_room_message` for Claude Code and DeepSeek Harness. The operating
instructions name the correct tool for the selected runtime. Runtime read/write
record tools are also exposed through the same bridge. The enforced allowance
remains eight deliveries per human chain, at most two active leads and a five-minute
deadline per run. The "exactly once" instruction is not a separate hard spending
limit. Use **Pause & stop** if the conversation diverges.

## Observe and record

- The first human message is addressed only to the first department.
- A public message from that lead addresses the second department. Its sender label
  is the authenticated lead, not a claimed human identity.
- The second lead produces a real final response. Final text does not route work.
- The two deliveries share a human-request chain and have different lead IDs and
  native conversations.
- Both deliveries complete successfully. An error, timeout or empty answer is
  evidence to investigate, not a successful demonstration.
- Reloading the tab retains the transcript and configuration.

After both deliveries finish, pause the room. A full acceptance run also needs an
explicitly authorized pause during active work, confirmed stop, and a
service-restart/recovery check. Do not claim those from an idle pause.

| Evidence | Result |
|---|---|
| Catalog contains DeepSeek V4 Flash and V4 Pro | Automated test passed |
| Claude Code / DeepSeek Harness adapter behavior | Fixture tests passed |
| Project history/records/hierarchy/addressing/theme | Automated browser tests passed |
| Runtime executable and credential readiness on this machine | **Blocked on 2026-11-21** |
| User-selected departments, runtimes and exact models | Pending |
| Explicit live request authorization | Authorized as bounded self-verification, but no successful call |
| Pi bounded smoke | Failed before inference: read-only default Pi config (`EACCES`) |
| DeepSeek Harness bounded smoke | Failed: configured key returned HTTP 401 |
| Claude Code bounded smoke | Did not finish within the verification window; stopped |
| Real addressed peer post and public response | Pending live verification |
| Distinct native conversations and shared chain | Pending live verification |
| Pause during active work and confirmed stop | Pending live verification |
| Service restart and no replay | Pending live verification |
| Independent spec and code-quality reviews | Still outstanding |

The live-attempt backup is `artifacts/live-demo-pre-live-2026-11-21-232350/`
(git-ignored, SHA256SUMS, SQLite integrity `ok`). The live data directory was not
migrated, restarted or modified. See [verification](verification.md) for details.

## Historical rooms

For the November 20 room and its context/recovery evidence, see the
[runtime audit](2026-11-20-runtime-audit.md). That room selected a provider through
an external Pi configuration; the current build no longer reads that provider list.
A department still referencing it remains readable but fails closed with a
"not configured" delivery error until the user chooses a catalog model.
