# Sample conversation

Use this short discussion to demonstrate a real lead-to-lead handoff in
Department Studio. The replies below are **illustrative examples, not a recorded
live conversation**. Your configured models will produce their own responses.

Create two departments with your own names, handles, roles and models. Choose
each workspace with **Browse folders**, keep both leads in **Discuss**, then
resume the room. Replace `FIRST_HANDLE` and `SECOND_HANDLE` with their actual
handles before sending the prompts below. No departments are built into the app.

## 1. Share context without starting work

Send this ordinary note:

```text
Demo goal: agree on one small improvement to Department Studio's first-run setup.
Discuss the idea only; make no file changes.
```

This stays visible in the room and starts no model turn.

## 2. Ask one department to consult the other

Send this addressed request. The composer should preview **only the first
department**; use the second handle without an `@` inside the recipient list.

```text
@FIRST_HANDLE Propose one small improvement to Department Studio's first-run
setup, drawing on your department's role. Use send_room_message exactly once
with recipients ["SECOND_HANDLE"] to ask for one concern and one practical
acceptance check. Tell that department to reply publicly, without forwarding
the request or changing files. Then briefly state your proposal in your final
response; do not wait synchronously for its reply. Keep each message under
100 words. This is discussion only; do not edit files or run shell commands.
```

An illustrative exchange about folder selection:

> **First department → second department:** I propose choosing a workspace by
> browsing folders. What is one usability concern, and how would you verify the
> experience? Reply publicly; no further delegation or file changes.

> **First department, public reply:** Let the user open folders and choose the
> current one, then show the selected path in department settings. I have asked
> the other department for a concern and an acceptance check.

> **Second department, public reply:** Canceling the picker should preserve the
> previous workspace and model. Check that choosing an empty folder works, and
> that canceling a later selection leaves the saved configuration untouched.

The two final replies may appear in either order. The meaningful evidence is the
first lead's addressed tool post followed by an actual second-lead delivery.
An ordinary final-response mention does not forward work.

## 3. Bring the discussion back to you

After both leads finish, send:

```text
@FIRST_HANDLE Summarize the proposal and the other department's concern in three
bullets: the user benefit, the acceptance check, and the decision you need from
me. Use the public room history. Do not send another peer request or change files.
```

A possible answer is:

> - Benefit: select a workspace without typing its path.
> - Check: an empty folder can be chosen, and Cancel preserves the prior selection.
> - Decision: confirm whether this behavior meets your setup needs.

You remain the project lead. Finish with an unaddressed note such as
`Thanks. I will review this before choosing the next task.`, then pause the room.

The first addressed request intends two deliveries; the summary is a separate
human request. The application's eight-delivery allowance still applies to each
chain. Sending these addressed prompts starts real inference with your selected
models. See `live-demo.md` for QGenie setup and `verification.md` for the remaining
live acceptance checks.
