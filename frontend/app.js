const $ = (selector) => document.querySelector(selector);
const storageKey = "department-studio-owner";
const fragment = new URLSearchParams(location.hash.slice(1));
let token = fragment.get("token");
if (location.hash) history.replaceState(null, "", location.pathname + location.search);
try {
  if (token) sessionStorage.setItem(storageKey, token);
  else token = sessionStorage.getItem(storageKey);
} catch { /* This tab can still use the fragment credential until it closes. */ }

let state = { paused: true, leads: [], messages: [], deliveries: [] };
let authenticated = Boolean(token);
let polling = null;
let sending = false;
let firstSnapshot = true;
let editing = null;
let saving = false;
let modelOptions = new Map();
let modelRequest = null;
let folderRequest = null;
let folderListing = null;
let composingMessage = false;
let mentionState = { context: null, options: [], active: 0 };
let mentionDismissedKey = null;
let deleting = false;
let deliveryBaseline = false;
let activities = [];
let activityTimer = null;
let activityOverflow = { count: 0, nonSuccess: 0 };
const observedDeliveries = new Map();
const activityNodes = new Map();
const pageTitle = document.title;
const rosterNodes = new Map();
const messageNodes = new Map();
const dialog = $("#lead-dialog");
const deleteDialog = $("#delete-dialog");
const folderDialog = $("#folder-dialog");

function text(node, value) {
  const content = String(value ?? "");
  if (node.textContent !== content) node.textContent = content;
}

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function notice(selector, message = "") {
  text($(selector), message);
  $(selector).hidden = !message;
}

function requireLaunch() {
  authenticated = false;
  $("#access-notice").hidden = false;
  text($("#connection"), "Launch URL needed");
  $("#add-department").disabled = true;
  $("#resume").disabled = true;
  $("#pause").disabled = true;
  previewRecipients();
}

async function request(path, { method = "GET", body, signal } = {}) {
  const credential = token;
  const response = await fetch(path, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(12000)]) : AbortSignal.timeout(12000),
    cache: "no-store",
  });
  if (response.status === 401 && token === credential) requireLaunch();
  const data = await response.json();
  if (!response.ok) {
    const fields = data.errors?.map((item) => item.field.replace(/^body\./, "")).join(", ");
    throw new Error((data.detail || "The request could not be completed.") + (fields ? ` Check: ${fields}.` : ""));
  }
  return data;
}

function tone(id) {
  return `tone-${Array.from(id || "human").reduce((sum, char) => sum + char.charCodeAt(0), 0) % 5}`;
}

function renderRoster() {
  const leadIds = new Set(state.leads.map((lead) => lead.id));
  for (const [id, card] of rosterNodes) {
    if (!leadIds.has(id)) {
      card.remove();
      rosterNodes.delete(id);
    }
  }
  text($("#lead-count"), state.leads.length);
  $("#roster-empty").hidden = state.leads.length > 0;
  for (const lead of state.leads) {
    let card = rosterNodes.get(lead.id);
    if (!card) {
      card = element("article", `lead-card ${tone(lead.id)}`);
      card.append(element("h3", "lead-title"), element("p", "lead-handle"),
        element("p", "lead-meta model"), element("p", "lead-meta workspace"));
      const bottom = element("div", "lead-bottom");
      bottom.append(element("span", "lead-status"), element("span", "permission-badge"));
      const edit = element("button", "edit-lead", "⋯");
      edit.type = "button";
      edit.addEventListener("click", () => openDepartment(state.leads.find((item) => item.id === lead.id)));
      card.append(bottom, edit);
      rosterNodes.set(lead.id, card);
      $("#roster").append(card);
    }
    text(card.querySelector(".lead-title"), lead.name);
    text(card.querySelector(".lead-handle"), `@${lead.handle}`);
    text(card.querySelector(".model"), `${lead.provider} / ${lead.model_id}`);
    card.querySelector(".model").title = `${lead.provider} / ${lead.model_id}`;
    text(card.querySelector(".workspace"), lead.workspace);
    card.querySelector(".workspace").title = lead.workspace;
    const status = card.querySelector(".lead-status");
    text(status, { idle: "Ready", running: "Working", queued: "Queued", stopping: "Stopping", disabled: "Disabled" }[lead.status] || lead.status);
    status.classList.toggle("active", lead.status === "running");
    status.classList.toggle("warning", lead.status === "stopping");
    const permission = card.querySelector(".permission-badge");
    text(permission, lead.permission === "develop" ? "Develop" : "Discuss");
    permission.classList.toggle("develop", lead.permission === "develop");
    card.querySelector("button").setAttribute("aria-label", `Edit ${lead.name}`);
  }
}

function safeLink(value) {
  try {
    const url = new URL(value, location.origin);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

function appendMarkdownInline(parent, source) {
  const token = /(!?\[[^\]]*\]\([^\n)]*\)|`[^`]*`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g;
  let cursor = 0;
  for (const match of source.matchAll(token)) {
    if (match.index > cursor) parent.append(document.createTextNode(source.slice(cursor, match.index)));
    const value = match[0];
    const link = /^(!?)\[([^\]]*)\]\(([^\n)]*)\)$/.exec(value);
    if (link) {
      if (link[1]) {
        parent.append(element("span", "markdown-image-alt", `[Image: ${link[2]}]`));
      } else {
        const href = safeLink(link[3].trim());
        if (href) {
          const anchor = element("a", "markdown-link");
          anchor.href = href;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          appendMarkdownInline(anchor, link[2]);
          parent.append(anchor);
        } else parent.append(document.createTextNode(link[2]));
      }
    } else if (value.startsWith("`")) {
      parent.append(element("code", "markdown-inline-code", value.slice(1, -1)));
    } else if (value.startsWith("**") || value.startsWith("__")) {
      const strong = document.createElement("strong");
      appendMarkdownInline(strong, value.slice(2, -2));
      parent.append(strong);
    } else {
      const emphasis = document.createElement("em");
      appendMarkdownInline(emphasis, value.slice(1, -1));
      parent.append(emphasis);
    }
    cursor = match.index + value.length;
  }
  if (cursor < source.length) parent.append(document.createTextNode(source.slice(cursor)));
}

function markdownTableCells(line) {
  const trimmed = line.trim().replace(/^\||\|$/g, "");
  return trimmed.split(/(?<!\\)\|/).map((cell) => cell.replace(/\\\|/g, "|").trim());
}

function isMarkdownTableDivider(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function markdownBlockStart(line, next) {
  return /^ {0,3}(```|~~~)/.test(line) || /^(#{1,6})\s+/.test(line) || /^> ?/.test(line)
    || /^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line) || isMarkdownTableDivider(next || "");
}

function appendMarkdownTable(parent, headerLine, lines, start) {
  const wrapper = element("div", "markdown-table-wrap");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  markdownTableCells(headerLine).forEach((cell) => {
    const column = document.createElement("th");
    appendMarkdownInline(column, cell);
    header.append(column);
  });
  head.append(header);
  table.append(head);
  const body = document.createElement("tbody");
  let index = start + 2;
  while (index < lines.length && lines[index].includes("|")) {
    const row = document.createElement("tr");
    markdownTableCells(lines[index]).forEach((cell) => {
      const column = document.createElement("td");
      appendMarkdownInline(column, cell);
      row.append(column);
    });
    body.append(row);
    index += 1;
  }
  table.append(body);
  wrapper.append(table);
  parent.append(wrapper);
  return index;
}

function appendMarkdownBlocks(parent, source) {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    if (!lines[index].trim()) { index += 1; continue; }
    const fence = /^ {0,3}(```|~~~)/.exec(lines[index]);
    if (fence) {
      const close = new RegExp(`^ {0,3}${fence[1]}\\s*$`);
      const start = ++index;
      while (index < lines.length && !close.test(lines[index])) index += 1;
      const pre = document.createElement("pre");
      pre.className = "markdown-code-block";
      pre.append(element("code", "", lines.slice(start, index).join("\n")));
      parent.append(pre);
      if (index < lines.length) index += 1;
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(lines[index]);
    if (heading) {
      const node = document.createElement(`h${heading[1].length}`);
      appendMarkdownInline(node, heading[2]);
      parent.append(node);
      index += 1;
      continue;
    }
    if (isMarkdownTableDivider(lines[index + 1] || "")) {
      index = appendMarkdownTable(parent, lines[index], lines, index);
      continue;
    }
    if (/^> ?/.test(lines[index])) {
      const quoted = [];
      while (index < lines.length && /^> ?/.test(lines[index])) {
        quoted.push(lines[index].replace(/^> ?/, ""));
        index += 1;
      }
      const quote = document.createElement("blockquote");
      appendMarkdownBlocks(quote, quoted.join("\n"));
      parent.append(quote);
      continue;
    }
    const list = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[index]);
    if (list) {
      const ordered = /\d/.test(list[2]);
      const node = document.createElement(ordered ? "ol" : "ul");
      while (index < lines.length) {
        const item = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[index]);
        if (!item || /\d/.test(item[2]) !== ordered) break;
        const entry = document.createElement("li");
        appendMarkdownInline(entry, item[3]);
        node.append(entry);
        index += 1;
      }
      parent.append(node);
      continue;
    }
    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !markdownBlockStart(lines[index], lines[index + 1])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    if (!paragraph.length) paragraph.push(lines[index++]);
    const node = document.createElement("p");
    appendMarkdownInline(node, paragraph.join("\n"));
    parent.append(node);
  }
}

function renderMarkdownBody(node, source) {
  node.replaceChildren();
  appendMarkdownBlocks(node, source);
}

function renderMessages() {
  const conversation = $("#conversation");
  const nearBottom = conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 80;
  $("#room-empty").hidden = state.messages.length > 0;
  const deliveries = new Map();
  for (const delivery of state.deliveries) {
    if (!deliveries.has(delivery.message_id)) deliveries.set(delivery.message_id, []);
    deliveries.get(delivery.message_id).push(delivery);
  }
  for (const message of state.messages) {
    let article = messageNodes.get(message.id);
    if (!article) {
      article = element("article", "message");
      const header = element("div", "message-header");
      const avatar = element("span", `avatar ${tone(message.sender_id)}`, message.sender_name.slice(0, 1));
      avatar.setAttribute("aria-hidden", "true");
      const time = element("time", "", new Date(message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
      time.dateTime = message.timestamp;
      time.title = new Date(message.timestamp).toLocaleString();
      const identity = element("div", "message-identity");
      identity.append(
        element("span", "message-author", message.sender_name),
        element("span", "message-handle", message.sender_kind === "human" ? "You · project lead" : `Department · @${message.sender_handle}`),
      );
      header.append(avatar, identity, time);
      const body = element("div", "message-text");
      renderMarkdownBody(body, message.text);
      article.append(header, body);
      if (message.recipient_handles?.length) {
        article.append(element("div", "recipient-label", `To ${message.recipient_handles.map((handle) => `@${handle}`).join(", ")}`));
      }
      if (message.notice) article.append(element("p", "message-notice", message.notice));
      article.append(element("div", "delivery-list"));
      messageNodes.set(message.id, article);
      $("#messages").append(article);
    }
    const list = article.querySelector(".delivery-list");
    for (const delivery of deliveries.get(message.id) || []) {
      let row = list.querySelector(`[data-delivery="${delivery.id}"]`);
      if (!row) {
        row = element("div");
        row.dataset.delivery = delivery.id;
        list.append(row);
      }
      const handle = message.recipient_handles?.[message.recipient_ids?.indexOf(delivery.lead_id)] || "department";
      const diagnostic = ["Runtime started.", "Runtime is working."].includes(delivery.diagnostic) ? "" : delivery.diagnostic;
      const detail = delivery.error || diagnostic || "";
      text(row, `@${handle} · ${delivery.state}${detail ? ` — ${detail}` : ""}`);
      row.classList.toggle("warning", ["failed", "interrupted", "stopping"].includes(delivery.state));
    }
  }
  if (firstSnapshot || nearBottom) conversation.scrollTop = conversation.scrollHeight;
  firstSnapshot = false;
}

function deliveryAttribution(delivery) {
  const message = state.messages.find((item) => item.id === delivery.message_id);
  const index = message?.recipient_ids?.indexOf(delivery.lead_id) ?? -1;
  return message?.recipient_handles?.[index] || state.leads.find((lead) => lead.id === delivery.lead_id)?.handle || "department";
}

function deliveryKey(delivery) {
  return `${delivery.id}:${delivery.generation ?? 0}`;
}

function activityDetails(delivery) {
  const handle = deliveryAttribution(delivery);
  if (delivery.state === "completed") return { tone: "success", text: `@${handle} finished this run` };
  if (delivery.state === "stopping") return { tone: "stopping", text: `@${handle} is stopping this run` };
  return { tone: "failure", text: `@${handle} ${delivery.state} this run` };
}

function isNonSuccess(activity) {
  return activity.tone !== "success";
}

function renderRunActivities() {
  const unread = activities.filter((item) => !item.read).length;
  text($("#activity-count"), unread);
  $("#activity-count").hidden = unread === 0;
  text($("#activity-summary"), unread ? `${unread} unread update${unread === 1 ? "" : "s"}` : "No unread updates");
  $("#activity-mark-read").disabled = unread === 0;
  document.title = document.hidden && unread ? `(${unread}) ${pageTitle}` : pageTitle;
  const overflow = $("#activity-overflow");
  const overflowText = activityOverflow.count
    ? `${activityOverflow.count} older update${activityOverflow.count === 1 ? "" : "s"} hidden by this page's activity limit${activityOverflow.nonSuccess ? ` (${activityOverflow.nonSuccess} non-success)` : ""}. See the original delivery history in the room.`
    : "";
  text(overflow, overflowText);
  overflow.hidden = !overflowText;

  const retained = new Set(activities.map((activity) => activity.key));
  for (const [key, nodes] of activityNodes) {
    if (!retained.has(key)) {
      nodes.row.remove();
      activityNodes.delete(key);
    }
  }
  const list = $("#activity-list");
  let position = list.firstElementChild;
  for (const activity of activities) {
    let nodes = activityNodes.get(activity.key);
    if (!nodes) {
      const row = element("li");
      row.dataset.activity = activity.key;
      const label = element("p");
      const view = element("button", "", "View");
      view.type = "button";
      view.addEventListener("click", () => {
        const current = activities.find((item) => item.key === activity.key);
        const target = messageNodes.get(current?.messageId);
        target?.scrollIntoView({ block: "center", behavior: "smooth" });
        if (current) current.read = true;
        renderRunActivities();
      });
      const dismiss = element("button", "", "Dismiss");
      dismiss.type = "button";
      dismiss.addEventListener("click", () => {
        const index = activities.findIndex((item) => item.key === activity.key);
        const next = activities[index + 1] || activities[index - 1];
        activities = activities.filter((item) => item.key !== activity.key);
        renderRunActivities();
        (next ? activityNodes.get(next.key)?.dismiss : $("#activity-toggle")).focus();
      });
      row.append(label, view, dismiss);
      nodes = { row, label, dismiss };
      activityNodes.set(activity.key, nodes);
    }
    nodes.row.className = `activity-item ${activity.tone}`;
    text(nodes.label, activity.text);
    // Insert new rows in place; moving retained rows would blur focused buttons.
    if (nodes.row !== position) list.insertBefore(nodes.row, position);
    position = nodes.row.nextElementSibling;
  }
}

function showActivityToast(activity) {
  const toast = $("#activity-toast");
  text(toast, activity.text);
  toast.className = `activity-toast ${activity.tone}`;
  toast.hidden = false;
  clearTimeout(activityTimer);
  activityTimer = setTimeout(() => { toast.hidden = true; }, 7000);
}

function observeDeliveries() {
  if (!deliveryBaseline) {
    state.deliveries.forEach((delivery) => observedDeliveries.set(deliveryKey(delivery), delivery.state));
    deliveryBaseline = true;
    return;
  }
  const updates = [];
  for (const delivery of state.deliveries) {
    const key = deliveryKey(delivery);
    const previous = observedDeliveries.get(key);
    observedDeliveries.set(key, delivery.state);
    if (["completed", "failed", "interrupted", "canceled", "stopping"].includes(delivery.state) && previous !== delivery.state) {
      updates.push({ key, messageId: delivery.message_id, read: false, ...activityDetails(delivery) });
    }
  }
  if (!updates.length) return;
  for (const update of updates) {
    const existing = activities.find((activity) => activity.key === update.key);
    if (existing) Object.assign(existing, update);
    else activities.unshift(update);
  }
  const dropped = activities.splice(50);
  activityOverflow.count += dropped.length;
  activityOverflow.nonSuccess += dropped.filter(isNonSuccess).length;
  renderRunActivities();
  // Coalesce the toast only; retain updates up to the explicitly reported limit.
  showActivityToast(updates.at(-1));
}

function renderActivity() {
  const activeIds = [...new Set(state.deliveries
    .filter((delivery) => delivery.state === "running")
    .map((delivery) => delivery.lead_id))];
  const names = activeIds
    .map((id) => state.leads.find((lead) => lead.id === id))
    .filter(Boolean)
    .map((lead) => lead.name);
  const indicator = $("#typing-indicator");
  if (!names.length) {
    indicator.hidden = true;
    text($("#typing-text"), "");
    return;
  }
  const people = names.length === 1 ? names[0] : names.length === 2 ? names.join(" and ") : `${names.slice(0, -1).join(", ")}, and ${names.at(-1)}`;
  text($("#typing-text"), `${people} ${names.length === 1 ? "is" : "are"} working…`);
  indicator.hidden = false;
}

function renderControls() {
  const stopping = state.deliveries.some((delivery) => delivery.state === "stopping");
  const uncertain = state.deliveries.some((delivery) => delivery.error === "Service restarted; previous execution outcome is uncertain.");
  text($("#room-state"), stopping ? "Stopping" : state.paused ? "Room paused" : "Room running");
  $("#room-state").classList.toggle("running", !state.paused && !stopping);
  $("#room-state").classList.toggle("stopping", stopping);
  let status = "Ready for addressed requests";
  let description = "Mention a department or use @all. You can pause at any time.";
  if (stopping) {
    status = "Stopping — wait before manual takeover";
    description = "Waiting for confirmed idle or process exit. Existing edits are preserved.";
  } else if (state.paused) {
    status = uncertain ? "Paused · inspect interrupted work" : "Paused · runtimes idle";
    description = uncertain ? "A previous run ended without confirmation. Inspect its processes and edits before resuming." : "Resume, then send a new request. Stopped work stays stopped.";
  }
  text($("#control-status"), status);
  text($("#control-description"), description);
  $("#resume").hidden = !state.paused;
  $("#pause").hidden = state.paused;
  $("#resume").disabled = !authenticated || stopping;
  $("#pause").disabled = !authenticated;
  $("#add-department").disabled = !authenticated;
}

async function refresh() {
  if (!authenticated) return;
  if (polling) return polling;
  polling = (async () => {
    try {
      state = await request("/api/state");
      text($("#connection"), "Connected locally");
      $("#access-notice").hidden = true;
      renderRoster();
      renderMessages();
      observeDeliveries();
      renderControls();
      renderActivity();
      previewRecipients();
    } catch {
      if (authenticated) text($("#connection"), "Reconnecting…");
    } finally { polling = null; }
  })();
  return polling;
}

function recipientsIn(textValue) {
  const handles = Array.from(textValue.matchAll(/(?:^|[^\p{L}\p{N}_@])@([\p{L}\p{N}_-]+)/gu), (match) => match[1].toLowerCase());
  const selected = new Set();
  const unknown = [];
  for (const handle of handles) {
    if (handle === "all") state.leads.filter((lead) => lead.enabled).forEach((lead) => selected.add(lead.handle));
    else if (state.leads.some((lead) => lead.handle === handle && lead.enabled)) selected.add(handle);
    else unknown.push(handle);
  }
  return { selected: [...selected], unknown: [...new Set(unknown)] };
}

function currentMentionContext() {
  const input = $("#message-text");
  const { value, selectionStart, selectionEnd } = input;
  if (selectionStart !== selectionEnd) return null;
  const beforeCaret = value.slice(0, selectionStart);
  const match = /(?:^|[^\p{L}\p{N}_@])@([\p{L}\p{N}_-]*)$/u.exec(beforeCaret);
  if (!match) return null;
  const query = match[1];
  const start = selectionStart - query.length - 1;
  const suffix = /^[\p{L}\p{N}_-]*/u.exec(value.slice(selectionStart))?.[0] || "";
  return { start, end: selectionStart + suffix.length, query: query.toLocaleLowerCase() };
}

function mentionChoices(query) {
  const normalized = query.toLocaleLowerCase();
  const matches = state.leads
    .filter((lead) => lead.enabled && lead.deleted !== true)
    .filter((lead) => !normalized || lead.handle.toLocaleLowerCase().includes(normalized) || lead.name.toLocaleLowerCase().includes(normalized))
    .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }) || left.handle.localeCompare(right.handle));
  const all = { name: "All departments", handle: "all", all: true };
  return (!normalized || all.name.toLocaleLowerCase().includes(normalized) || all.handle.includes(normalized)) ? [all, ...matches] : matches;
}

function mentionKey(context = currentMentionContext()) {
  if (!context) return null;
  const input = $("#message-text");
  return `${input.value}\u0000${input.selectionStart}\u0000${input.selectionEnd}\u0000${context.start}\u0000${context.end}`;
}

function dismissMentions({ remember = false } = {}) {
  if (remember) mentionDismissedKey = mentionKey();
  mentionState = { context: null, options: [], active: 0 };
  $("#mention-menu").hidden = true;
  $("#message-text").setAttribute("aria-expanded", "false");
  $("#message-text").removeAttribute("aria-activedescendant");
}

function setMentionActive(index) {
  if (!mentionState.options.length) return;
  mentionState.active = (index + mentionState.options.length) % mentionState.options.length;
  document.querySelectorAll(".mention-option").forEach((option, optionIndex) => {
    option.setAttribute("aria-selected", String(optionIndex === mentionState.active));
  });
  const active = document.querySelectorAll(".mention-option")[mentionState.active];
  if (active) {
    $("#message-text").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }
}

function chooseMention(index = mentionState.active) {
  const option = mentionState.options[index];
  const context = currentMentionContext();
  if (!option || !context) { dismissMentions(); return; }
  const input = $("#message-text");
  const inserted = `@${option.handle}`;
  input.value = `${input.value.slice(0, context.start)}${inserted}${input.value.slice(context.end)}`;
  const caret = context.start + inserted.length;
  input.setSelectionRange(caret, caret);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  dismissMentions({ remember: true });
}

function renderMentions({ deliberate = false } = {}) {
  const input = $("#message-text");
  if (composingMessage || document.activeElement !== input) { dismissMentions(); return; }
  const context = currentMentionContext();
  if (!context) { dismissMentions(); return; }
  const key = mentionKey(context);
  if (mentionDismissedKey === key && !deliberate) { dismissMentions(); return; }
  if (deliberate) mentionDismissedKey = null;
  const previous = mentionState.options[mentionState.active]?.handle;
  const options = mentionChoices(context.query);
  if (!options.length) { dismissMentions(); return; }
  mentionState = { context, options, active: Math.max(0, options.findIndex((option) => option.handle === previous)) };
  const nodes = document.createDocumentFragment();
  options.forEach((option, index) => {
    const node = element("button", `mention-option${option.all ? " mention-option-all" : ""}`);
    node.type = "button";
    node.id = `mention-option-${option.handle}`;
    node.setAttribute("role", "option");
    node.setAttribute("aria-selected", String(index === mentionState.active));
    node.setAttribute("aria-label", option.all ? "All departments, @all" : `${option.name}, @${option.handle}`);
    node.append(element("span", "mention-option-name", option.all ? "departments" : option.name), element("span", "mention-option-handle", `@${option.handle}`));
    node.addEventListener("pointerdown", (event) => event.preventDefault());
    node.addEventListener("click", () => chooseMention(index));
    nodes.append(node);
  });
  $("#mention-options").replaceChildren(nodes);
  $("#mention-menu").hidden = false;
  $("#message-text").setAttribute("aria-expanded", "true");
  setMentionActive(mentionState.active);
}

function renderRecipientContext(selected) {
  const recipient = selected.length ? selected.map((handle) => `@${handle}`).join(", ") : "the room";
  text($("#room-recipient"), recipient);
  $("#recipient-context").classList.toggle("addressed", selected.length > 0);
}

function previewRecipients({ deliberate = false } = {}) {
  const input = $("#message-text").value;
  const { selected, unknown } = recipientsIn(input);
  const invalid = unknown.length > 0;
  let description = "Public note · no department will be notified";
  if (invalid) description = `Unknown or disabled: ${unknown.map((handle) => `@${handle}`).join(", ")}`;
  else if (selected.length) description = `To ${selected.map((handle) => `@${handle}`).join(", ")}${state.paused ? " · room paused; this note will not start work" : ""}`;
  text($("#recipient-preview"), description);
  renderRecipientContext(selected);
  $("#recipient-preview").classList.toggle("invalid", invalid);
  $("#send").disabled = !authenticated || sending || invalid || !input.trim();
  renderMentions({ deliberate });
}

$("#message-text").addEventListener("compositionstart", () => {
  composingMessage = true;
  dismissMentions();
});
$("#message-text").addEventListener("compositionend", () => {
  composingMessage = false;
  previewRecipients({ deliberate: true });
});
$("#message-text").addEventListener("input", () => {
  if (!composingMessage) previewRecipients({ deliberate: true });
});
$("#message-text").addEventListener("focus", () => {
  if (!composingMessage) previewRecipients({ deliberate: true });
});
$("#message-text").addEventListener("blur", () => dismissMentions());
$("#message-text").addEventListener("click", () => {
  if (!composingMessage) previewRecipients({ deliberate: true });
});
$("#message-text").addEventListener("keyup", (event) => {
  if (!composingMessage && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) previewRecipients({ deliberate: true });
});
$("#message-text").addEventListener("keydown", (event) => {
  if (composingMessage || event.isComposing) return;
  if (!$("#mention-menu").hidden) {
    if (event.key === "ArrowDown") { event.preventDefault(); setMentionActive(mentionState.active + 1); return; }
    if (event.key === "ArrowUp") { event.preventDefault(); setMentionActive(mentionState.active - 1); return; }
    if ((event.key === "Enter" && !event.ctrlKey && !event.metaKey) || event.key === "Tab") {
      event.preventDefault();
      chooseMention();
      return;
    }
    if (event.key === "Escape") { event.preventDefault(); dismissMentions({ remember: true }); return; }
  }
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !$("#send").disabled) {
    event.preventDefault();
    $("#composer").requestSubmit();
  }
});
$("#composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("#send").disabled) return;
  const draft = $("#message-text").value;
  sending = true;
  previewRecipients();
  notice("#composer-error");
  try {
    await request("/api/messages", { method: "POST", body: { text: draft } });
    if ($("#message-text").value === draft) $("#message-text").value = "";
    await refresh();
  } catch (error) { notice("#composer-error", error.message); }
  finally { sending = false; previewRecipients(); }
});

for (const action of ["pause", "resume"]) {
  $(`#${action}`).addEventListener("click", async () => {
    $(`#${action}`).disabled = true;
    notice("#control-error");
    try {
      state = await request(`/api/room/${action}`, { method: "POST" });
      renderControls();
      await refresh();
    } catch (error) { notice("#control-error", error.message); }
    finally { renderControls(); }
  });
}

function resetModels(message) {
  modelOptions = new Map();
  $("#lead-model").replaceChildren(new Option(message, ""));
  $("#lead-model").disabled = true;
}

function openDepartment(lead = null) {
  editing = lead;
  saving = false;
  modelRequest?.abort();
  $("#lead-form").reset();
  text($("#dialog-title"), lead ? "Edit department" : "New department");
  for (const key of ["name", "handle", "role", "workspace"]) $(`#lead-${key}`).value = lead?.[key] || "";
  $("#lead-enabled").checked = lead?.enabled ?? true;
  document.querySelector(`input[name="permission"][value="${lead?.permission || "discuss"}"]`).checked = true;
  resetModels("Choose a workspace, then load models");
  if (lead) {
    modelOptions.set("saved", { provider: lead.provider, id: lead.model_id });
    $("#lead-model").append(new Option(`${lead.provider} / ${lead.model_id} (saved)`, "saved"));
    $("#lead-model").disabled = false;
    $("#lead-model").value = "saved";
  }
  text($("#model-help"), "Uses your existing Pi provider configuration. Listing a model does not verify its connection.");
  $("#load-models").disabled = false;
  $("#delete-department").hidden = !lead;
  notice("#form-error");
  updatePermission();
  dialog.showModal();
}

function updatePermission() {
  const develop = document.querySelector('input[name="permission"]:checked').value === "develop";
  const needsConsent = develop && editing?.permission !== "develop";
  $("#develop-warning").hidden = !develop;
  $("#consent-label").hidden = !needsConsent;
  $("#save-department").disabled = saving || (needsConsent && !$("#develop-consent").checked);
  text($("#save-department"), needsConsent ? "Enable Develop and save" : "Save department");
}

function departmentBusy(lead) {
  return ["queued", "running", "stopping"].includes(lead?.status);
}

function updateDeleteAction() {
  const busy = departmentBusy(editing);
  const expected = `@${editing?.handle || ""}`;
  const matches = $("#delete-confirmation").value.trim().toLocaleLowerCase() === expected.toLocaleLowerCase();
  $("#confirm-delete").disabled = deleting || busy || !matches;
}

function openDeleteDialog() {
  if (!editing) return;
  const busy = departmentBusy(editing);
  text($("#delete-department-name"), `${editing.name} (@${editing.handle})`);
  $("#delete-confirmation").value = "";
  $("#delete-confirmation").placeholder = `@${editing.handle}`;
  $("#delete-confirmation").disabled = busy;
  $("#delete-confirmation-field").hidden = busy;
  $("#delete-busy-note").hidden = !busy;
  if (busy) text($("#delete-busy-note"), "This department has queued, running or stopping work. Wait for it to become ready, or use Pause & stop for the room and wait for confirmed stop before deleting.");
  notice("#delete-error");
  deleting = false;
  updateDeleteAction();
  deleteDialog.showModal();
  if (busy) $("#cancel-delete").focus();
  else $("#delete-confirmation").focus();
}

$("#delete-department").addEventListener("click", openDeleteDialog);
$("#delete-confirmation").addEventListener("input", updateDeleteAction);
for (const id of ["close-delete-dialog", "cancel-delete"]) $(`#${id}`).addEventListener("click", () => deleteDialog.close());
$("#confirm-delete").addEventListener("click", async () => {
  if (!editing || $("#confirm-delete").disabled) return;
  const deleted = editing;
  deleting = true;
  updateDeleteAction();
  notice("#delete-error");
  try {
    await request(`/api/leads/${encodeURIComponent(deleted.id)}?revision=${encodeURIComponent(deleted.revision)}`, { method: "DELETE" });
    deleteDialog.close();
    dialog.close();
    await refresh();
  } catch (error) {
    notice("#delete-error", error.message);
    if (/revision|stale|changed/i.test(error.message)) {
      await refresh();
      editing = state.leads.find((lead) => lead.id === deleted.id) || null;
      $("#delete-confirmation").value = "";
    }
  } finally {
    deleting = false;
    updateDeleteAction();
  }
});

$("#add-department").addEventListener("click", () => openDepartment());
for (const id of ["close-dialog", "cancel-dialog"]) $(`#${id}`).addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => {
  modelRequest?.abort();
  if (folderDialog.open) folderDialog.close();
});
document.querySelectorAll('input[name="permission"]').forEach((input) => input.addEventListener("change", updatePermission));
$("#develop-consent").addEventListener("change", updatePermission);
$("#lead-workspace").addEventListener("input", () => {
  modelRequest?.abort();
  resetModels("Load models for this workspace");
});

function renderFolders() {
  if (!folderListing) return;
  const query = $("#folder-filter").value.trim().toLocaleLowerCase();
  const folders = folderListing.folders.filter((folder) => folder.name.toLocaleLowerCase().includes(query));
  const items = document.createDocumentFragment();
  for (const folder of folders) {
    const item = element("li");
    const open = element("button", "folder-entry");
    open.type = "button";
    open.setAttribute("aria-label", `Open ${folder.name}`);
    const icon = element("span", "folder-icon");
    icon.setAttribute("aria-hidden", "true");
    const arrow = element("span", "folder-arrow", "›");
    arrow.setAttribute("aria-hidden", "true");
    open.append(icon, element("span", "folder-name", folder.name), arrow);
    open.addEventListener("click", () => browseFolders(folder.path));
    item.append(open);
    items.append(item);
  }
  $("#folder-list").replaceChildren(items);
  text($("#folder-status"), folders.length ? `${folders.length} folder${folders.length === 1 ? "" : "s"}` :
    query ? "No matching folders." : "No subfolders. You can choose this folder.");
}

async function browseFolders(path) {
  folderRequest?.abort();
  const controller = new AbortController();
  folderRequest = controller;
  folderListing = null;
  $("#select-folder").disabled = true;
  $("#folder-up").disabled = true;
  $("#folder-filter").value = "";
  $("#folder-list").replaceChildren();
  text($("#folder-location"), path || "Project folder");
  text($("#folder-status"), "Loading folders…");
  notice("#folder-error");
  try {
    const data = await request(path === undefined ? "/api/folders" : `/api/folders?path=${encodeURIComponent(path)}`, { signal: controller.signal });
    if (!folderDialog.open || controller.signal.aborted) return;
    folderListing = data;
    text($("#folder-location"), data.path);
    $("#folder-up").disabled = data.parent === null;
    $("#select-folder").disabled = false;
    renderFolders();
    $("#folder-filter").focus();
  } catch (error) {
    if (!folderDialog.open || controller.signal.aborted) return;
    notice("#folder-error", error.message);
    text($("#folder-status"), "Choose Home or Project folder to browse again.");
  }
}

$("#browse-workspace").addEventListener("click", () => {
  folderDialog.showModal();
  browseFolders($("#lead-workspace").value || undefined);
});
$("#folder-home").addEventListener("click", () => browseFolders("~"));
$("#folder-project").addEventListener("click", () => browseFolders());
$("#folder-up").addEventListener("click", () => {
  if (folderListing?.parent) browseFolders(folderListing.parent);
});
$("#folder-filter").addEventListener("input", renderFolders);
for (const id of ["close-folder-dialog", "cancel-folder"]) $(`#${id}`).addEventListener("click", () => folderDialog.close());
folderDialog.addEventListener("close", () => {
  folderRequest?.abort();
  folderListing = null;
  if (dialog.open) $("#browse-workspace").focus();
});
$("#select-folder").addEventListener("click", () => {
  if (!folderListing || $("#select-folder").disabled) return;
  const workspace = $("#lead-workspace");
  if (workspace.value !== folderListing.path) {
    workspace.value = folderListing.path;
    workspace.dispatchEvent(new Event("input", { bubbles: true }));
  }
  folderDialog.close();
});

$("#load-models").addEventListener("click", async () => {
  const workspace = $("#lead-workspace").value.trim();
  if (!workspace) { notice("#form-error", "Choose a workspace directory first."); return; }
  modelRequest?.abort();
  const controller = new AbortController();
  modelRequest = controller;
  $("#load-models").disabled = true;
  notice("#form-error");
  text($("#model-help"), "Reading Pi’s configured models…");
  try {
    const data = await request(`/api/models?workspace=${encodeURIComponent(workspace)}`, { signal: controller.signal });
    if (!dialog.open || controller.signal.aborted) return;
    resetModels(data.models.length ? "Choose a model" : "No configured models available");
    data.models.forEach((model, index) => {
      const key = String(index);
      modelOptions.set(key, model);
      $("#lead-model").append(new Option(`${model.name} · ${model.provider} / ${model.id}`, key));
    });
    $("#lead-model").disabled = data.models.length === 0;
    text($("#model-help"), data.models.length ? "Choose an exact provider and model. No model has been selected for you." : "Configure a provider in Pi, then load models again. No inference was requested.");
  } catch (error) {
    if (!controller.signal.aborted) { notice("#form-error", error.message); text($("#model-help"), "Model listing unavailable."); }
  } finally { if (modelRequest === controller) $("#load-models").disabled = false; }
});
$("#lead-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("#save-department").disabled) return;
  const model = modelOptions.get($("#lead-model").value);
  if (!model) { notice("#form-error", "Load models and choose one before saving."); return; }
  const body = {
    name: $("#lead-name").value,
    handle: $("#lead-handle").value,
    role: $("#lead-role").value,
    workspace: $("#lead-workspace").value,
    provider: model.provider,
    model_id: model.id,
    permission: document.querySelector('input[name="permission"]:checked').value,
    enabled: $("#lead-enabled").checked,
  };
  if (editing) body.revision = editing.revision;
  saving = true;
  updatePermission();
  notice("#form-error");
  try {
    await request(editing ? `/api/leads/${editing.id}` : "/api/leads", { method: editing ? "PATCH" : "POST", body });
    dialog.close();
    await refresh();
  } catch (error) { notice("#form-error", error.message); }
  finally { saving = false; updatePermission(); }
});

$("#activity-toggle").addEventListener("click", () => {
  const panel = $("#activity-panel");
  panel.hidden = !panel.hidden;
  $("#activity-toggle").setAttribute("aria-expanded", String(!panel.hidden));
});
$("#activity-mark-read").addEventListener("click", () => {
  activities.forEach((activity) => { activity.read = true; });
  renderRunActivities();
});
document.addEventListener("visibilitychange", renderRunActivities);

if (!authenticated) requireLaunch();
else refresh();
window.addEventListener("hashchange", () => {
  const next = new URLSearchParams(location.hash.slice(1)).get("token");
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  if (!next) return;
  token = next;
  authenticated = true;
  try { sessionStorage.setItem(storageKey, token); } catch { /* Current tab retains access. */ }
  refresh();
});
setInterval(refresh, 1000);
