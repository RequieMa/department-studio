# Project rooms, records, hierarchy and default addressing

Status: implemented and covered by deterministic backend, browser and packaging
tests. No live model call or persistent-data migration was performed during
implementation.

## Project isolation and lifecycle

A project is a complete room: its own `room.sqlite`, departments, messages, tasks,
records and native session directory. Projects are not filtered rows in one
database.

Data-directory layout:

```text
<data-dir>/
  studio.lock
  active_project.json
  project.json                 # only when an existing root room is adopted
  room.sqlite, sessions/, records/   # adopted legacy project
  projects/
    <project-id>/
      project.json
      room.sqlite
      sessions/
      records/
```

- On first open, an existing root room is adopted as **My first project** without
  moving its database or sessions. Otherwise a new project is created under
  `projects/<id>/`.
- `Projects` in the header opens history. New project creates and switches; switch
  closes the current `RoomService` after confirmed stop, then opens the target;
  delete is owner-only, requires the project name, and is refused for the active or
  only project.
- Deleting a project removes only its Studio data (database, WAL files, sessions,
  records, metadata). Workspace paths and their files are never deleted.
- The active project is persisted in `active_project.json` and restored on restart.

Owner API:

```text
GET    /api/projects
POST   /api/projects                  {name}
POST   /api/projects/{id}/activate
DELETE /api/projects/{id}?confirm_name=<name>
```

While a switch is in progress, non-project API calls return `503`; project routes
remain available so the switch can finish.

## Records

Each project has a private `records/` folder (mode 0700, files 0600). It is the
durable audit trail shared by the human and every runtime. The initial `README.md`
explains the convention. Record names are flat `*.md` filenames; content is limited
to 512 KiB and writes are atomic.

Owner API and UI:

```text
GET  /api/records
GET  /api/records/{name}
POST /api/records                     {name, content}       # create only
PUT  /api/records/{name}              {name, content, mode} # append/replace
```

Every runtime receives `list_records`, `read_record` and `write_record` through the
room bridge. The Pi extension and the MCP server for Claude Code/DeepSeek Harness
share the same bounded HTTP boundary. Runtime credentials are valid only for an
active delivery generation; the browser owner credential cannot use bridge routes.

The common operating instructions tell departments to keep room messages brief,
write durable findings/decisions/evidence to records, and name the exact record path
when asking another department to read it. The human composer shows the same
guidance. Records are removed with their project's Studio data.

## Department hierarchy

`department_edges` is an undirected graph stored in the project database. Defaults:

- a new project starts complete;
- creating a department links it to every existing non-deleted department;
- deleting a department removes its edges;
- schema v4 migration backfills a complete graph for existing departments.

Owner API:

```text
GET  /api/hierarchy
PUT  /api/hierarchy/edges             {a, b, connected}
POST /api/hierarchy/connect-all
```

The UI draws the graph on an SVG circle. Clicking a line disconnects it; clicking
two vertices connects them; **Connect all** restores missing edges.

Enforcement is server-side in `post_bridge_message`: an agent-to-agent post whose
recipient is not connected fails with `409` and stores no message. Human addressing
is not restricted by the hierarchy, and task instructions remain human authority.

## Default addressing

`room.active_recipient_ids` stores the last explicit human addressee set.

- Explicit mentions (`@handle`, `@all`) resolve and replace the set.
- A message with no mention and no public-note opt-out inherits the stored set
  (enabled, non-deleted departments only).
- The composer previews **Continuing with @…**; the **Don’t continue the previous
  addressees** checkbox sends a public note and leaves the set unchanged.
- Disabled/deleted recipients are filtered; if none remain, the message is a public
  note with a notice.
- The set survives service and database restarts and is exposed in `/api/state` as
  `active_recipient_ids`.

## Dark mode

`frontend/theme.js` runs before the stylesheet, applying `data-theme` from local
storage or `prefers-color-scheme`. The header button toggles explicit light/dark and
persists only in that browser. All primary surfaces use CSS variables; no theme
choice is stored in SQLite or sent to an agent.

## Migration and verification boundary

Schema v4 is additive: v1 deletion, v2 context maintenance, v3 tasks, v4 hierarchy
and `active_recipient_ids`. Migrations run in one transaction and roll back fully on
failure. A short-lived task-only v2 shape is repaired before v3/v4. Back up the
complete data directory and native sessions with Studio stopped before upgrading;
there is no downgrade procedure.

Automated coverage includes project catalog/lifecycle, project API, record storage
and bridge, hierarchy store/API and denial, addressing continuity/public notes,
schema v0-v4 migration, 350 ordinary tests, 21 Chromium UI tests (projects, records, hierarchy toggle,
peer-message folding, addressing, theme) and the packaged wheel.
