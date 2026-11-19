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
const rosterNodes = new Map();
const messageNodes = new Map();
const dialog = $("#lead-dialog");
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
      header.append(avatar, element("span", "message-author", message.sender_name),
        element("span", "message-handle", message.sender_kind === "human" ? "project lead" : `@${message.sender_handle}`), time);
      article.append(header, element("div", "message-text", message.text));
      if (message.recipient_handles.length) {
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
      const handle = message.recipient_handles[message.recipient_ids.indexOf(delivery.lead_id)] || "department";
      const diagnostic = ["Runtime started.", "Runtime is working."].includes(delivery.diagnostic) ? "" : delivery.diagnostic;
      const detail = delivery.error || diagnostic || "";
      text(row, `@${handle} · ${delivery.state}${detail ? ` — ${detail}` : ""}`);
      row.classList.toggle("warning", ["failed", "interrupted", "stopping"].includes(delivery.state));
    }
  }
  if (firstSnapshot || nearBottom) conversation.scrollTop = conversation.scrollHeight;
  firstSnapshot = false;
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
      renderControls();
      previewRecipients();
    } catch {
      if (authenticated) text($("#connection"), "Reconnecting…");
    } finally { polling = null; }
  })();
  return polling;
}

function previewRecipients() {
  const input = $("#message-text").value;
  const handles = Array.from(input.matchAll(/(?:^|[^\p{L}\p{N}_@])@([\p{L}\p{N}_-]+)/gu), (match) => match[1].toLowerCase());
  const selected = new Set();
  const unknown = [];
  for (const handle of handles) {
    if (handle === "all") state.leads.filter((lead) => lead.enabled).forEach((lead) => selected.add(lead.handle));
    else if (state.leads.some((lead) => lead.handle === handle && lead.enabled)) selected.add(handle);
    else unknown.push(handle);
  }
  const invalid = unknown.length > 0;
  let description = "Public note · no department will be notified";
  if (invalid) description = `Unknown or disabled: ${[...new Set(unknown)].map((handle) => `@${handle}`).join(", ")}`;
  else if (selected.size) description = `To ${[...selected].map((handle) => `@${handle}`).join(", ")}${state.paused ? " · room paused; this note will not start work" : ""}`;
  text($("#recipient-preview"), description);
  $("#recipient-preview").classList.toggle("invalid", invalid);
  $("#send").disabled = !authenticated || sending || invalid || !input.trim();
}

$("#message-text").addEventListener("input", previewRecipients);
$("#message-text").addEventListener("keydown", (event) => {
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
