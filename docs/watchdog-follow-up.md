# Deferred: department progress watchdog

Status: design direction recorded at the human's request (2026-11-20); implementation
explicitly postponed. Finish Ongoing tasks and actionable-only Activity first.

## Problem and desired behavior

The current 300-second total run deadline can interrupt productive long-running work
and cancel unrelated follow-ups queued for the same department. Elapsed wall time
alone is not evidence of blockage. The desired replacement lets each department
continue authorized work, with a watchdog observing possible blockage rather than
an arbitrary short lifetime cap. This document changes no current runtime behavior.

## Proposed direction for later review

- Observe runtime liveness separately from meaningful progress: current tool phase,
  last event/progress timestamps, explicit waiting-for-human or dependency states,
  and native idle/exit confirmation. A live process/heartbeat is not proof of progress;
  silence during a long build/model call is not proof of deadlock.
- Use phase-aware observation windows, configurable grace periods and repeated
  observations. Classify healthy, expected waiting, suspected stalled and stop-unconfirmed
  separately. Do not infer these states from model prose or expose raw tool output,
  secrets or private reasoning as watchdog evidence.
- A suspected stall should first produce one deduplicated, explicit human-action
  request with safe evidence and choices such as keep waiting, inspect, or request
  stop. No routine-completion Activity spam; resolve/retract stale observations when
  progress resumes. The watchdog is not an autonomous project manager.
- Do not automatically kill a department, cancel unrelated queued instructions,
  retry work, change permissions, or declare completion solely because time elapsed.
  Define any hard resource/emergency limits separately and explicitly with the human.
- Preserve human Pause/stop authority, per-department serialization, generation
  revocation, confirmed-stop requirements and restart non-replay. Stopping preserves
  edits and does not prove external side effects were rolled back.
- Store only bounded, sanitized observations keyed by stable department/delivery IDs.
  Define restart recovery, stale observations and Activity resolution atomically.

## Required before implementation

Human review of the replacement deadline policy and any cancellation-control changes;
exact runtime-neutral signal contract and UI/API design; synthetic tests covering long
healthy work, quiet tools, provider waits, hangs, lost heartbeats, false positives,
recovery, concurrent Pause, uncertain stop and no automatic replay. No live probes,
new monitoring service, model calls or control changes are authorized by this note.
