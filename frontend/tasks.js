// Durable task navigation. All execution decisions remain server-authoritative.
export function createTaskUI({ request, refreshRoom, viewMessage }) {
  const $ = (selector) => document.querySelector(selector);
  const setText = (node, value) => { const next = String(value ?? ""); if (node.textContent !== next) node.textContent = next; };
  const make = (tag, className, value) => {
    const node = document.createElement(tag);
    node.className = className || "";
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const showError = (selector, message = "") => { setText($(selector), message); $(selector).hidden = !message; };
  const panel = $("#tasks-panel");
  const drawer = $("#tasks-drawer");
  const wide = matchMedia("(min-width: 1280px)");
  const taskNodes = new Map();
  const collapsed = new Set();
  const drafts = new Map();
  const submissions = new Map();
  const receipts = new Map();
  let room = { leads: [], paused: true };
  let tasks = [];
  let selected = null;
  let detail = null;
  let opened = false;
  let pending = false;
  let detailGeneration = 0;
  let pages = 1;
  let nextCursor = null;
  let historyCursor = null;
  let detailPages = 1;
  let childRequest = null;
  let mutationPending = false;
  let composed = false;
  let connected = false;
  let actions = [];
  let actionPages = 1;
  let actionsCursor = null;
  let actionsConnected = false;
  const actionNodes = new Map();
  const actionRequests = new Map();

  function relocate() {
    const focused = document.activeElement;
    const inside = panel.contains(focused);
    if (wide.matches) {
      if (drawer.open) drawer.close();
      $("#tasks-dock").append(panel);
    } else {
      drawer.append(panel);
      if (opened && !drawer.open) drawer.showModal();
    }
    panel.hidden = !opened;
    $(".workbench").classList.toggle("tasks-open", opened && wide.matches);
    $("#tasks-toggle").setAttribute("aria-expanded", String(opened));
    if (inside && opened) focused.focus({ preventScroll: true });
  }

  function setOpen(value, focus = true) {
    opened = value;
    if (!opened && drawer.open) drawer.close();
    relocate();
    if (focus) (opened ? $("#tasks-close") : $("#tasks-toggle")).focus({ preventScroll: true });
    if (opened && connected) refresh(room);
  }
  $("#tasks-toggle").addEventListener("click", () => setOpen(!opened));
  $("#tasks-close").addEventListener("click", () => setOpen(false));
  drawer.addEventListener("cancel", (event) => { event.preventDefault(); setOpen(false); });
  wide.addEventListener("change", relocate);
  $("#task-back").addEventListener("click", () => {
    panel.classList.remove("task-detail-mode");
    taskNodes.get(selected)?.select.focus({ preventScroll: true });
  });
  $("#tasks-filter").addEventListener("change", renderMap);
  $("#tasks-more").addEventListener("click", () => { pages += 1; refresh(room); });

  function ownerFor(task) {
    return task.owner || room.leads.find((lead) => lead.id === task.owner_lead_id) || {
      name: task.owner_name || task.historical_owner_name || "Unavailable department",
      handle: task.owner_handle || task.historical_owner_handle || "",
      enabled: false,
    };
  }
  function ownerLabel(task) {
    const owner = ownerFor(task);
    return `${owner.name}${owner.handle ? ` · @${owner.handle}` : ""}`;
  }
  function executionLabel(task) {
    const summary = task.delivery_summary || {};
    const states = ["running", "queued", "stopping", "failed", "interrupted", "canceled", "completed"];
    const counts = states.filter((key) => summary[key]).map((key) => `${summary[key]} ${key}`);
    return counts.join(" · ") || "No linked runs";
  }
  function renderMap() {
    const all = new Map(tasks.map((task) => [task.id, task]));
    const shown = new Set(tasks.filter((task) => $("#tasks-filter").value === "all" || task.lifecycle === "open" || task.id === selected).map((task) => task.id));
    for (const id of [...shown]) {
      let parent = all.get(id)?.parent_id;
      const seen = new Set([id]);
      while (parent && !seen.has(parent)) {
        seen.add(parent); shown.add(parent); parent = all.get(parent)?.parent_id;
      }
    }
    const children = new Map();
    for (const task of tasks) {
      if (!shown.has(task.id)) continue;
      const parent = all.has(task.parent_id) ? task.parent_id : null;
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(task);
    }
    const focused = document.activeElement;
    const focusId = focused?.id;
    const inMap = $("#task-map").contains(focused);
    for (const [id, nodes] of taskNodes) {
      if (!shown.has(id) || !all.has(id)) { nodes.row.remove(); taskNodes.delete(id); }
    }
    const seen = new Set();
    function reconcile(parent, list, depth = 0) {
      let position = list.firstElementChild;
      for (const task of children.get(parent) || []) {
        if (seen.has(task.id) || depth > 100) continue;
        seen.add(task.id);
        let nodes = taskNodes.get(task.id);
        if (!nodes) {
          const row = make("li", "task-branch");
          const line = make("div", "task-node-line");
          const toggle = make("button", "task-disclosure", "−");
          toggle.type = "button"; toggle.id = `task-disclose-${task.id}`;
          const select = make("button", "task-node");
          select.type = "button"; select.id = `task-select-${task.id}`;
          const title = make("strong", "task-node-title");
          const owner = make("span", "task-node-owner");
          const status = make("span", "task-node-status");
          select.append(title, owner, status);
          const nested = make("ol", "task-children"); nested.id = `task-children-${task.id}`;
          toggle.setAttribute("aria-controls", nested.id);
          toggle.addEventListener("click", () => {
            if (collapsed.has(task.id)) collapsed.delete(task.id); else collapsed.add(task.id);
            renderMap();
          });
          select.addEventListener("click", () => selectTask(task.id));
          line.append(toggle, select); row.append(line, nested);
          nodes = { row, toggle, select, title, owner, status, nested }; taskNodes.set(task.id, nodes);
        }
        const hasChildren = Boolean(children.get(task.id)?.length);
        nodes.toggle.hidden = !hasChildren;
        setText(nodes.toggle, collapsed.has(task.id) ? "+" : "−");
        nodes.toggle.setAttribute("aria-label", `${collapsed.has(task.id) ? "Expand" : "Collapse"} ${task.title} subtasks`);
        nodes.toggle.setAttribute("aria-expanded", String(!collapsed.has(task.id)));
        nodes.nested.hidden = collapsed.has(task.id);
        setText(nodes.title, task.title);
        setText(nodes.owner, ownerLabel(task));
        setText(nodes.status, `${task.lifecycle === "closed" ? "Closed" : "Open"} · ${executionLabel(task)}${task.parent_id && !all.has(task.parent_id) ? " · Parent outside loaded page" : ""}`);
        nodes.select.setAttribute("aria-pressed", String(selected === task.id));
        if (nodes.row !== position) list.insertBefore(nodes.row, position);
        position = nodes.row.nextElementSibling;
        reconcile(task.id, nodes.nested, depth + 1);
      }
    }
    reconcile(null, $("#task-map"));
    $("#tasks-empty").hidden = seen.size > 0;
    setText($("#tasks-empty"), tasks.length ? "No open tasks in this page. Choose All tasks or load more." : "Address a department in the room to create a task. Child tasks are created explicitly.");
    if (inMap && focusId && document.activeElement !== focused) document.getElementById(focusId)?.focus({ preventScroll: true });
  }

  async function selectTask(id) {
    if (mutationPending) return;
    if (selected) drafts.set(selected, $("#task-instruction").value);
    selected = id; detail = null; detailPages = 1; historyCursor = null;
    $("#task-child-form").hidden = true; childRequest = null;
    $("#task-instruction").value = drafts.get(id) || "";
    $("#task-detail").hidden = false; panel.classList.add("task-detail-mode");
    showError("#task-action-error"); showError("#task-instruction-error");
    renderMap(); renderDetail();
    await loadDetail(true);
  }
  async function loadDetail(focus = false) {
    if (!selected) return;
    const id = selected;
    const generation = ++detailGeneration;
    try {
      let cursor = null;
      const combined = {
        messages: [], deliveries: [], instructions: [], action_requests: [],
        deliveries_truncated: false, action_requests_truncated: false,
      };
      for (let page = 0; page < detailPages; page += 1) {
        const data = await request(`/api/tasks/${encodeURIComponent(id)}?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
        if (id !== selected || generation !== detailGeneration) return;
        combined.task = data.task;
        combined.messages.push(...data.messages);
        combined.deliveries.push(...data.deliveries);
        combined.instructions.push(...data.instructions);
        combined.action_requests.push(...(data.action_requests || []));
        combined.deliveries_truncated ||= data.deliveries_truncated;
        combined.action_requests_truncated ||= data.action_requests_truncated;
        cursor = data.next_cursor;
        if (!cursor) break;
      }
      detail = combined;
      historyCursor = cursor;
      renderDetail();
      if (focus) $("#task-detail-title").focus({ preventScroll: true });
    } catch (error) {
      if (id !== selected || generation !== detailGeneration) return;
      detail = null; renderDetail(); showError("#task-action-error", error.message);
    }
  }
  function currentTask() { return detail?.task || tasks.find((task) => task.id === selected); }
  function instructionAction(task) {
    return task?.instruction_action?.mode || "blocked";
  }
  function renderDetail() {
    const task = currentTask();
    if (!task) { setText($("#task-detail-title"), "Loading task…"); $("#task-instruction-send").disabled = true; return; }
    setText($("#task-detail-title"), task.title);
    setText($("#task-parent"), task.parent_id ? `Subtask · ${tasks.find((item) => item.id === task.parent_id)?.title || "Parent task"}` : "Root task");
    setText($("#task-owner"), ownerLabel(task));
    setText($("#task-lifecycle"), `Task ${task.lifecycle || "open"}`);
    setText($("#task-execution"), executionLabel(task));
    setText($("#task-context"), task.context || "No additional task context.");
    $("#task-source").hidden = !task.source_message_id;
    const hasActiveWork = ["queued", "running", "stopping"].some((key) => task.delivery_summary?.[key]);
    $("#task-lifecycle-action").disabled = mutationPending || !detail || !connected || (task.lifecycle !== "closed" && hasActiveWork);
    setText($("#task-lifecycle-action"), task.lifecycle === "closed" ? "Reopen task" : "Close task");
    $("#task-add-child").disabled = mutationPending || !detail || !connected || task.lifecycle === "closed";
    const action = instructionAction(task);
    const busy = ["running", "queued"].includes(ownerFor(task).status);
    const submission = submissions.get(selected);
    $("#task-instruction").readOnly = Boolean(submission);
    setText($("#task-instruction-send"), submission?.pending ? "Saving…" : submission ? "Retry original instruction" : action === "record_note" ? "Record note" : busy ? "Queue instruction" : "Send instruction");
    setText($("#task-instruction-help"), submission && !submission.pending ? "Receipt uncertain. Retry the original submission unchanged; this cannot create a second request." : action === "record_note" ? "No execution. This note will not send automatically on Resume. Send a new instruction when ready." : action === "execute" ? "Follows existing queued work. Does not interrupt or alter the current run." : "This task cannot receive instructions. Its owner may be unavailable or the task closed.");
    $("#task-instruction-send").disabled = !connected || !detail || (action === "blocked" && !submission) || composed || !$("#task-instruction").value.trim() || Boolean(submission?.pending);
    setText($("#task-instruction-receipt"), receipts.get(selected) || "");
    renderHistory();
  }
  function renderHistory() {
    if (!detail) return;
    const instructions = detail.instructions || [];
    const unique = new Map(instructions.map((item) => [item.id, item]));
    const list = $("#task-instructions");
    const signature = JSON.stringify([...unique.values()]);
    if (list.dataset.signature !== signature) {
      list.dataset.signature = signature;
      const fragment = document.createDocumentFragment();
      for (const item of unique.values()) {
        const row = make("li");
        const admission = item.disposition === "recorded_no_dispatch" ? "Recorded note · no execution" : `Queued request · ${item.delivery_state || item.delivery?.state || "awaiting execution update"}`;
        row.append(make("strong", "", admission), make("p", "", item.text || detail.messages?.find((message) => message.id === item.message_id)?.text || "Instruction saved in room history."));
        fragment.append(row);
      }
      if (!unique.size) fragment.append(make("li", "field-help", "No instructions yet."));
      list.replaceChildren(fragment);
    }
    const decisions = new Map((detail.action_requests || []).map((item) => [item.id, item]));
    const decisionList = $("#task-decisions");
    const decisionSignature = JSON.stringify([...decisions.values()]);
    if (decisionList.dataset.signature !== decisionSignature) {
      decisionList.dataset.signature = decisionSignature;
      const fragment = document.createDocumentFragment();
      for (const decision of decisions.values()) {
        const selected = decision.options?.find((option) => option.id === decision.resolution?.option_id);
        const state = decision.status === "resolved"
          ? `Resolved decision${selected ? ` · ${selected.label}` : ""}`
          : "Awaiting your decision";
        const row = make("li");
        row.append(make("strong", "task-decision-status", state), make("p", "", decision.question));
        if (decision.status === "resolved" && !selected) {
          row.append(make("p", "field-help", "The selected option is unavailable in this retained record."));
        }
        fragment.append(row);
      }
      if (!decisions.size) fragment.append(make("li", "field-help", "No decisions requested for this task."));
      decisionList.replaceChildren(fragment);
    }
    $("#task-history-more").hidden = !historyCursor;
    const historyNotes = [];
    if (detail.deliveries_truncated) historyNotes.push("Some linked deliveries are omitted from this context page; task totals above include all runs.");
    if (detail.action_requests_truncated) historyNotes.push("Only the most recent 200 retained decisions are shown.");
    if (historyCursor) historyNotes.push("More public context and instructions are available.");
    setText($("#task-history-status"), historyNotes.join(" "));
    const context = $("#task-messages");
    const messages = detail.messages || [];
    const contextKey = JSON.stringify(messages);
    if (context.dataset.signature !== contextKey) {
      context.dataset.signature = contextKey;
      context.replaceChildren(...messages.map((message) => {
        const article = make("article", "task-context-message");
        article.append(make("strong", "", message.sender_name || "Room"), make("p", "", message.text));
        return article;
      }));
    }
  }
  $("#task-history-more").addEventListener("click", async () => {
    if (!historyCursor) return;
    detailPages += 1;
    $("#task-history-more").disabled = true;
    try { await loadDetail(); }
    finally { $("#task-history-more").disabled = false; }
  });
  $("#task-source").addEventListener("click", () => {
    const id = currentTask()?.source_message_id;
    if (!wide.matches) setOpen(false, false);
    if (id) viewMessage(id);
  });
  $("#task-instruction").addEventListener("input", () => { if (selected) drafts.set(selected, $("#task-instruction").value); renderDetail(); });
  $("#task-instruction").addEventListener("compositionstart", () => { composed = true; renderDetail(); });
  $("#task-instruction").addEventListener("compositionend", () => { composed = false; renderDetail(); });
  $("#task-instruction").addEventListener("keydown", (event) => {
    if (composed || event.isComposing || event.keyCode === 229 || event.repeat) return;
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $("#task-instruction-form").requestSubmit(); }
  });
  $("#task-instruction-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if ($("#task-instruction-send").disabled) return;
    const task = currentTask();
    const id = selected;
    const value = $("#task-instruction").value;
    const body = { task_revision: task.revision, text: value, mode: instructionAction(task) };
    let submission = submissions.get(id);
    if (!submission) {
      submission = { body: { ...body, idempotency_key: crypto.randomUUID() }, pending: false };
      submissions.set(id, submission);
    }
    submission.pending = true;
    showError("#task-instruction-error"); renderDetail();
    try {
      const receipt = await request(`/api/tasks/${encodeURIComponent(id)}/instructions`, { method: "POST", body: submission.body });
      receipts.set(id, receipt.disposition === "recorded_no_dispatch" ? "Recorded note. No delivery created; Resume will not send it." : "Instruction queued. This receipt does not mean it was read or applied.");
      submissions.delete(id);
      if (drafts.get(id) === value) drafts.delete(id);
      if (selected === id && $("#task-instruction").value === value) $("#task-instruction").value = "";
      await refreshRoom(); await loadDetail();
    } catch (error) {
      if (error.status && error.status < 500) submissions.delete(id);
      if (selected === id) showError("#task-instruction-error", `${error.message}${!error.status || error.status >= 500 ? " Receipt uncertain; retry unchanged to avoid duplicate execution." : " Review the current task before sending again."}`);
      if (error.status === 409 && selected === id) await loadDetail();
    } finally { submission.pending = false; renderDetail(); }
  });

  $("#task-lifecycle-action").addEventListener("click", async () => {
    const task = currentTask();
    if (!task || mutationPending) return;
    mutationPending = true; renderDetail(); showError("#task-action-error");
    try {
      await request(`/api/tasks/${encodeURIComponent(task.id)}`, { method: "PATCH", body: { task_revision: task.revision, lifecycle: task.lifecycle === "closed" ? "open" : "closed" } });
      await refresh(room); await loadDetail();
    } catch (error) { showError("#task-action-error", error.message); await loadDetail(); }
    finally { mutationPending = false; renderDetail(); }
  });
  $("#task-add-child").addEventListener("click", () => {
    $("#task-child-form").reset(); childRequest = null;
    for (const id of ["task-child-title", "task-child-owner", "task-child-context"]) $(`#${id}`).disabled = false;
    setText($("#task-child-create"), "Create task");
    setText($("#task-child-parent"), `Parent: ${currentTask()?.title}. Creating a subtask does not start work.`);
    $("#task-child-owner").replaceChildren(new Option("Choose a department", ""), ...room.leads.filter((lead) => lead.enabled && !lead.deleted_at).map((lead) => new Option(`${lead.name} · @${lead.handle}`, lead.id)));
    $("#task-child-form").hidden = false; $("#task-child-title").focus();
  });
  $("#task-child-cancel").addEventListener("click", () => { $("#task-child-form").hidden = true; $("#task-add-child").focus(); });
  $("#task-child-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (mutationPending) return;
    const body = { parent_id: selected, parent_revision: currentTask().revision, owner_lead_id: $("#task-child-owner").value, title: $("#task-child-title").value, context: $("#task-child-context").value };
    if (!childRequest) childRequest = { body: { ...body, idempotency_key: crypto.randomUUID() } };
    mutationPending = true; $("#task-child-create").disabled = true;
    for (const id of ["task-child-title", "task-child-owner", "task-child-context"]) $(`#${id}`).disabled = true;
    try {
      const data = await request("/api/tasks", { method: "POST", body: childRequest.body });
      $("#task-child-form").hidden = true; childRequest = null;
      if (!tasks.some((task) => task.id === data.id)) tasks.push(data);
      await refresh(room); mutationPending = false; await selectTask(data.id);
    } catch (error) { showError("#task-action-error", error.message); if (error.status && error.status < 500) childRequest = null; }
    finally {
      mutationPending = false; $("#task-child-create").disabled = false;
      for (const id of ["task-child-title", "task-child-owner", "task-child-context"]) $(`#${id}`).disabled = Boolean(childRequest);
      setText($("#task-child-create"), childRequest ? "Retry original creation" : "Create task");
      renderDetail();
    }
  });

  // Delivery transitions are not human-action requests. Only explicit persisted
  // unresolved actions belong in Activity; normal completions never notify.
  function renderActions() {
    const unresolved = actions.filter((action) => action.status === "open");
    setText($("#activity-count"), `${unresolved.length}${actionsCursor ? "+" : ""}`); $("#activity-count").hidden = !unresolved.length;
    setText($("#activity-summary"), unresolved.length ? `${unresolved.length}${actionsCursor ? "+" : ""} unresolved request${unresolved.length === 1 ? "" : "s"}` : "No decisions or actions requested.");
    $("#activity-more").hidden = !actionsCursor;
    const retained = new Set(unresolved.map((action) => action.id));
    for (const [id, nodes] of actionNodes) if (!retained.has(id)) { if (nodes.row.contains(document.activeElement)) $("#activity-toggle").focus(); nodes.row.remove(); actionNodes.delete(id); }
    let position = $("#activity-list").firstElementChild;
    for (const action of unresolved) {
      let nodes = actionNodes.get(action.id);
      if (!nodes) {
        const row = make("li", "human-action");
        const form = make("form");
        const fieldset = make("fieldset");
        const question = make("legend");
        const choices = make("div", "human-action-choices");
        const submit = make("button", "primary", "Submit decision"); submit.type = "submit"; submit.disabled = true;
        const error = make("p", "inline-error"); error.hidden = true; error.setAttribute("role", "alert");
        fieldset.append(question, choices); form.append(fieldset, submit, error); row.append(form);
        nodes = { row, form, fieldset, question, choices, submit, error, revision: null };
        form.addEventListener("change", renderActions);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          const current = actions.find((item) => item.id === action.id);
          const option = form.querySelector("input:checked")?.value;
          if (!current || !option || submit.disabled) return;
          const body = { revision: current.revision, task_revision: current.task.revision, option_id: option, mode: instructionAction(current.task) };
          let saved = actionRequests.get(action.id);
          if (!saved) { saved = { body: { ...body, idempotency_key: crypto.randomUUID() } }; actionRequests.set(action.id, saved); }
          saved.pending = true;
          submit.disabled = true; fieldset.disabled = true; error.hidden = true;
          try {
            const result = await request(`/api/action-requests/${encodeURIComponent(action.id)}/resolve`, { method: "POST", body: saved.body });
            actionRequests.delete(action.id);
            setText($("#activity-receipt"), result.instruction.disposition === "recorded_no_dispatch" ? "Decision recorded as a note. It will not execute on Resume." : "Decision queued for the responsible department. It has not necessarily been read or applied.");
            await refreshActions();
          } catch (failure) {
            setText(error, failure.message); error.hidden = false;
            if (failure.status && failure.status < 500) { actionRequests.delete(action.id); await refreshActions(); }
          } finally { saved.pending = false; renderActions(); }
        });
        actionNodes.set(action.id, nodes);
      }
      setText(nodes.question, action.question || action.title || "Human action requested");
      if (nodes.revision !== action.revision) {
        nodes.revision = action.revision;
        nodes.choices.replaceChildren(...(action.options || []).map((option) => {
          const label = make("label", "human-choice");
          const radio = document.createElement("input"); radio.type = "radio"; radio.name = `action-${action.id}`; radio.value = option.id; radio.required = true;
          label.append(radio, make("span", "", option.label)); return label;
        }));
        nodes.submit.disabled = true;
      }
      const saved = actionRequests.get(action.id);
      const mode = instructionAction(action.task);
      nodes.fieldset.disabled = !actionsConnected || !connected || Boolean(saved) || mode === "blocked";
      nodes.submit.disabled = !actionsConnected || !connected || Boolean(saved?.pending) || (!saved && (mode === "blocked" || !nodes.form.querySelector("input:checked")));
      setText(nodes.submit, saved?.pending ? "Saving…" : saved ? "Retry original decision" : mode === "record_note" ? "Record decision as note" : "Submit decision");
      nodes.submit.title = mode === "record_note" ? "No execution. Resume will not send this decision." : mode === "blocked" ? "Task closed or responsible department unavailable." : "Queues a new public follow-up; does not interrupt current work.";
      if (nodes.row !== position) $("#activity-list").insertBefore(nodes.row, position);
      position = nodes.row.nextElementSibling;
    }
  }
  $("#activity-more").addEventListener("click", () => { actionPages += 1; refreshActions(); });
  async function refreshActions() {
    try {
      let cursor = null;
      const loaded = [];
      for (let page = 0; page < actionPages; page += 1) {
        const data = await request(`/api/action-requests?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
        loaded.push(...data.action_requests); cursor = data.next_cursor;
        if (!cursor) break;
      }
      actions = loaded; actionsCursor = cursor; actionsConnected = true;
      showError("#activity-error"); renderActions();
    } catch {
      actionsConnected = false; renderActions();
      showError("#activity-error", "Decision requests could not be refreshed. Reconnect before submitting; current selections are preserved.");
    }
  }
  async function refresh(nextRoom, available = true) {
    room = nextRoom; connected = available;
    if (!available) { actionsConnected = false; renderDetail(); renderActions(); return; }
    if (pending) return;
    pending = true;
    try {
      let cursor = null;
      const loaded = [];
      for (let page = 0; page < pages; page += 1) {
        const data = await request(`/api/tasks?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
        loaded.push(...(data.tasks || [])); cursor = data.next_cursor || null;
        if (page === 0) setText($("#tasks-count"), data.open_count ?? loaded.filter((task) => task.lifecycle === "open").length);
        if (!cursor) break;
      }
      tasks = loaded; nextCursor = cursor; $("#tasks-more").hidden = !nextCursor;
      setText($("#tasks-status"), nextCursor ? `Showing ${tasks.length} tasks. More available.` : "");
      showError("#tasks-error"); renderMap();
      if (opened && selected) await loadDetail();
    } catch (error) {
      connected = false; renderDetail();
      showError("#tasks-error", error.status === 404 ? "Task API is unavailable in this server. Use the integrated build." : "Task updates unavailable. Your draft is preserved; reconnect before sending.");
    } finally { pending = false; }
    await refreshActions();
  }
  renderActions();
  setOpen(wide.matches, false);
  return { refresh };
}
