# Live Pi collaboration demo

This guide prepares a real, user-directed conversation about Department Studio.
It does not run inference or create departments automatically. Choose the two
department names, handles, roles, models and workspaces in the UI. Keep both in
**Discuss** for this demonstration.

## Preparation status — November 19, 2026

The production application was checked from `.worktrees/bootstrap` using a
separate, private `.department-studio/live-demo` data directory. Its authenticated
state endpoint returned an empty, paused room. Browser verification confirmed
launch-token setup, Discuss as the default, and model loading without sending any
messages or creating departments. The temporary server was then stopped, freeing
port 8765 for the user's terminal.

**QGenie is already configured.** Both inspected Pi settings files select
`qgenie / azure::gpt-6-luna` as their saved default. The richer model catalog is in
`/home/zengma/.pi/agent`; the QGenie launcher otherwise defaults to its separate
installation-local agent directory.

The empty RPC model list inside this coding session was traced to a configuration
failure: Pi reported `EROFS` while creating its `settings.json` lock. Both agent
directories are mounted read-only here, and Pi returned a placeholder model. This
does not show that QGenie is missing or that its credentials need replacing. Start
the demo in your normal terminal, where Pi can use its existing configuration.
No model prompt was sent, and provider credentials were not displayed or changed.

The implementation's automated results and missing independent reviews are
recorded in `verification.md`. Preparing this demo does not complete those reviews
or establish that provider inference works.

## Start or reopen the demo

Run the following in your normal terminal. The explicit agent directory selects
the existing QGenie configuration inspected during preparation:

```bash
cd /home/zengma/department-studio/.worktrees/bootstrap
uv sync --locked
PI_CODING_AGENT_DIR=/home/zengma/.pi/agent \
  uv run --locked department-studio --data-dir .department-studio/live-demo
```

Open the printed URL, including its fragment. Each server restart generates a new
launch credential. The room starts paused and restores existing configuration and
messages; it never replays interrupted work. The demo data is git-ignored. Keep
launch credentials and native sessions out of this document and source control.

## Load the existing QGenie models

In Studio, click **Add department**, select a workspace with **Browse folders**,
choose **Use this folder**, and click
**Load models**. Listing is a metadata request, not a model prompt. Choose the
exact provider/model you want; the saved TUI default is useful context, not an
automatic choice for either department. A live request still needs your model
selections and authorization.

If the list remains empty in your terminal, first confirm that Pi and Studio use
the same `PI_CODING_AGENT_DIR` and that Pi can create its configuration locks there.
Do not replace credentials based only on an empty model list. If authentication
uses environment variables, start Studio from the terminal with those variables
set so its child processes inherit them.

Only models available under the bootstrap's resource policy can appear.
Auto-loaded provider extensions are disabled. Do not enable arbitrary extensions
to make this check pass. A listed model can still fail during inference; the room
must show that failure without substituting a different model.

## Configure the two departments

For each department, enter your own name, unique handle, role and exact model.
Choose the workspace with **Browse folders**, select **Discuss**, and save. Both leads may use
`/home/zengma/department-studio/.worktrees/bootstrap` to discuss the implemented
project, or another existing workspace you explicitly choose. Select separate
workspaces before any later concurrent editing.

Keep the room paused while configuring. No department has been pre-created and
no model is selected automatically. Roles are independent of names. There is no
need to enable Develop for this demonstration.

## Send one explicit collaboration request

For a fuller example with an opening note, a peer handoff, illustrative replies
and a summary back to the human, see the [sample conversation](sample-conversation.md).

Sending the following request starts live inference with the models you selected.
If an assistant is operating the demo for you, explicitly authorize that bounded
live request after confirming the selected departments and models.

1. Click **Resume room**.
2. Send an ordinary note such as `We are checking the Department Studio bootstrap.`
   It should appear in the transcript with no new delivery.
3. Replace `FIRST_HANDLE` and `SECOND_HANDLE` below with your chosen handles. Use
   the second handle **without an @ prefix** inside the recipient array. Confirm
   that the composer preview names only the first department before sending.

```text
@FIRST_HANDLE We are demonstrating real department-to-department communication
about Department Studio. Use send_room_message exactly once with recipients
["SECOND_HANDLE"]. Ask that department for one observable acceptance check proving
that renaming a department preserves its identity and historical attribution.
Ask it to answer in its public final response, under 120 words, without forwarding
the request to anyone else. Your own final response should briefly state what you
asked; do not wait synchronously for the other department. Use only the room
message tool for this request. Do not edit files or run shell commands.
```

The intended result is two deliveries: the initial human-to-lead request, then
the tool-addressed peer request. The application's enforced allowance remains
eight deliveries per human chain, with at most two active leads and a five-minute
deadline per run. The instruction to send once is not a separate hard spending
limit. Use **Pause & stop** if the conversation diverges.

## Observe and record the result

- The first human message is addressed only to the first department.
- A public message from that lead addresses the second department. Its sender
  label must be the authenticated lead, not a claimed human identity.
- The second lead produces a real final response. Final text does not start
  further work, even if it mentions handles.
- The two delivery records share a human-request chain and have different lead
  IDs and native conversations. Check the local authenticated state/session
  records if collecting technical evidence; keep raw native transcripts private.
- Both deliveries complete successfully. An error, timeout or empty answer is
  evidence to investigate, not a successful live demonstration.
- Reloading the tab retains the attributed transcript and configuration.

After both deliveries finish, pause the room. A full acceptance run also needs an
explicitly authorized pause during active work, confirmed stop, and service
restart/recovery check; follow `verification.md`. Do not claim those checks from
an idle pause. Keep Develop disabled until the independent reviews and the
separate, user-directed self-development preparation are complete.

Record only what was observed:

| Evidence | Result |
|---|---|
| Authenticated empty, paused production room | Passed during preparation |
| Existing QGenie configuration | Present; saved default `qgenie / azure::gpt-6-luna` |
| Pi metadata listing in this coding session | HTTP 200 with an empty list; Pi configuration lock failed with `EROFS` |
| Pi metadata listing from the user's normal terminal | Pending |
| User-selected departments and exact models | Pending |
| Explicit live request authorization | Pending |
| Real addressed peer post and public response | Pending |
| Distinct native conversations and shared chain | Pending live verification |
| Pause during active work and confirmed stop | Pending live verification |
| Service restart and no replay | Pending live verification |
| Independent spec and code-quality reviews | Still outstanding |
