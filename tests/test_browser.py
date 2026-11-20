import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.browser
ORIGIN = os.environ.get("STUDIO_BROWSER_ORIGIN", "http://127.0.0.1:8766")
TOKEN = "browser-test-owner"
ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


def snapshot():
    response = httpx.get(ORIGIN + "/api/state", headers={"Authorization": "Bearer " + TOKEN})
    response.raise_for_status()
    return response.json()


def create_department(page, name, handle, role, model):
    page.get_by_role("button", name="Add department", exact=True).click()
    dialog = page.get_by_role("dialog", name="New department")
    dialog.get_by_label("Department name", exact=True).fill(name)
    dialog.get_by_label("Handle", exact=True).fill(handle)
    dialog.get_by_label("Role and instructions", exact=True).fill(role)
    dialog.get_by_role("button", name="Browse folders", exact=True).click()
    picker = page.get_by_role("dialog", name="Choose workspace folder")
    expect(picker.locator("#folder-location")).to_have_text(str(ROOT))
    picker.get_by_role("button", name="Use this folder", exact=True).click()
    expect(dialog.get_by_label("Workspace directory", exact=True)).to_have_value(str(ROOT))
    dialog.get_by_role("button", name="Load models", exact=True).click()
    expect(dialog.get_by_label("Model", exact=True)).to_be_enabled()
    assert dialog.get_by_label("Model", exact=True).input_value() == ""
    dialog.get_by_label("Model", exact=True).select_option(label=model)
    dialog.get_by_role("button", name="Save department", exact=True).click()
    expect(dialog).not_to_be_visible()


def test_bootstrap_setup_routing_controls_reconnect_and_draft_preservation(browser):
    ARTIFACTS.mkdir(exist_ok=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(ORIGIN + "/#token=" + TOKEN)
    expect(page.get_by_text("Name your first department", exact=True)).to_be_visible()
    assert page.url == ORIGIN + "/"
    assert page.evaluate("sessionStorage.getItem('department-studio-owner')") == TOKEN
    page.screenshot(path=str(ARTIFACTS / "empty-desktop.png"), full_page=True)

    create_department(
        page, "星图 Studio", "atlas", "Build a small API", "Synthetic A · test / model-a"
    )
    create_department(
        page, "Canvas", "canvas", "Design the interface", "Synthetic B · test / model-b"
    )
    original = snapshot()["leads"][0]
    assert original["permission"] == "discuss"
    assert len({lead["conversation_id"] for lead in snapshot()["leads"]}) == 2

    composer = page.get_by_label("Message to the room", exact=True)
    composer.fill("Draft survives polling")
    composer.focus()
    page.wait_for_timeout(1300)
    expect(composer).to_have_value("Draft survives polling")
    expect(composer).to_be_focused()
    page.get_by_role("button", name="Resume room", exact=True).click()
    expect(page.get_by_text("Room running", exact=True)).to_be_visible()
    composer.fill("@atlas record the contract")
    expect(page.locator("#recipient-preview")).to_contain_text("@atlas")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_text("Synthetic test reply from 星图 Studio.", exact=True)).to_be_visible()

    page.get_by_role("button", name="Edit 星图 Studio", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit department")
    field = dialog.get_by_label("Department name", exact=True)
    field.fill("Foundry")
    field.focus()
    page.wait_for_timeout(1300)
    expect(field).to_have_value("Foundry")
    expect(field).to_be_focused()
    dialog.get_by_label("Handle", exact=True).fill("forge")
    dialog.get_by_role("button", name="Save department", exact=True).click()
    expect(dialog).not_to_be_visible()
    renamed = snapshot()["leads"][0]
    assert (renamed["id"], renamed["conversation_id"]) == (
        original["id"],
        original["conversation_id"],
    )
    assert (
        next(m for m in snapshot()["messages"] if m["sender_kind"] == "lead")["sender_name"]
        == "星图 Studio"
    )

    composer.fill("@atlas old handle")
    expect(page.locator("#recipient-preview")).to_contain_text("Unknown or disabled")
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
    composer.fill("@forge use the new handle")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_text("Synthetic test reply from Foundry.", exact=True)).to_be_visible()
    before = len(snapshot()["deliveries"])
    literal = '<img src=x onerror="window.roomXss=true"> public note'
    composer.fill(literal)
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_text(literal, exact=True)).to_be_visible()
    assert page.evaluate("window.roomXss") is None
    assert len(snapshot()["deliveries"]) == before

    page.get_by_role("button", name="Edit Foundry", exact=True).click()
    dialog.get_by_label("Develop", exact=True).check()
    expect(
        dialog.get_by_text("These tools run with your local account's access.", exact=False)
    ).to_be_visible()
    expect(
        dialog.get_by_role("button", name="Enable Develop and save", exact=True)
    ).to_be_disabled()
    dialog.get_by_label("I allow local editing, writing and shell for this department.").check()
    dialog.get_by_role("button", name="Enable Develop and save", exact=True).click()
    expect(dialog).not_to_be_visible()
    assert snapshot()["leads"][0]["permission"] == "develop"

    composer.fill("@forge synthetic wait")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.locator(".lead-status").filter(has_text="Working")).to_be_visible()
    page.get_by_role("button", name="Pause & stop", exact=True).click()
    expect(page.get_by_text("Paused · runtimes idle", exact=True)).to_be_visible()
    deliveries = snapshot()["deliveries"]
    assert deliveries[-1]["state"] == "interrupted"

    composer.fill("Still here after reconnect")
    page.context.set_offline(True)
    expect(page.get_by_text("Reconnecting…", exact=True)).to_be_visible(timeout=15000)
    expect(composer).to_have_value("Still here after reconnect")
    page.context.set_offline(False)
    expect(page.get_by_text("Connected locally", exact=True)).to_be_visible(timeout=15000)
    expect(composer).to_have_value("Still here after reconnect")
    page.reload()
    expect(page.get_by_role("button", name="Edit Foundry", exact=True)).to_be_visible()
    expect(page.get_by_text(literal, exact=True)).to_be_visible()
    page.screenshot(path=str(ARTIFACTS / "room-desktop.png"), full_page=True)
    assert errors == []
    context.close()


def test_mobile_layout_dialog_focus_and_missing_launch_credential(browser):
    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = context.new_page()
    page.goto(ORIGIN + "/")
    expect(page.get_by_text("Open the launch URL from your terminal.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_disabled()
    page.goto(ORIGIN + "/#token=" + TOKEN)
    expect(page.get_by_text("Connected locally", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="Add department", exact=True).click()
    dialog = page.get_by_role("dialog", name="New department")
    expect(dialog.get_by_label("Department name", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Add department", exact=True)).to_be_focused()
    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / "room-mobile.png"), full_page=True)
    context.close()


def test_restart_uncertainty_is_not_labeled_confirmed_idle(browser):
    context = browser.new_context()
    page = context.new_page()
    recovered = {
        "paused": True,
        "leads": [],
        "messages": [],
        "deliveries": [
            {
                "id": "interrupted-run",
                "message_id": "original-request",
                "state": "interrupted",
                "error": "Service restarted; previous execution outcome is uncertain.",
            }
        ],
    }
    page.route(
        "**/api/state",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(recovered)
        ),
    )
    page.goto(ORIGIN + "/#token=" + TOKEN)
    expect(page.get_by_text("Paused · inspect interrupted work", exact=True)).to_be_visible()
    expect(page.get_by_text("Paused · runtimes idle", exact=True)).not_to_be_visible()
    context.close()


def test_workspace_folder_picker_selection_cancel_and_model_reset(browser):
    ARTIFACTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="workspace-picker-", dir=ARTIFACTS) as directory:
        parent = Path(directory)
        empty = parent / "星图 workspace"
        empty.mkdir()
        literal = "<img src=x onerror=window.folderXss=true>"
        (parent / literal).mkdir()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ORIGIN + "/#token=" + TOKEN)
        page.get_by_role("button", name="Add department", exact=True).click()
        department = page.get_by_role("dialog", name="New department")
        department.get_by_label("Department name", exact=True).fill("Pathfinder")
        department.get_by_label("Handle", exact=True).fill("paths")
        department.get_by_label("Role and instructions", exact=True).fill("Check workspace setup")

        department.get_by_role("button", name="Browse folders", exact=True).click()
        picker = page.get_by_role("dialog", name="Choose workspace folder")
        expect(picker.locator("#folder-location")).to_have_text(str(ROOT))
        picker.get_by_role("button", name="Open artifacts", exact=True).click()
        picker.get_by_role("button", name=f"Open {parent.name}", exact=True).click()
        expect(picker.get_by_role("button", name=f"Open {literal}", exact=True)).to_be_visible()
        assert page.evaluate("window.folderXss") is None
        picker.get_by_label("Filter folders", exact=True).fill("星图")
        expect(picker.get_by_role("button", name=f"Open {literal}", exact=True)).not_to_be_visible()
        page.screenshot(path=str(ARTIFACTS / "folder-picker-desktop.png"), full_page=True)
        picker.get_by_role("button", name="Open 星图 workspace", exact=True).click()
        expect(picker.get_by_text("No subfolders. You can choose this folder.")).to_be_visible()
        picker.get_by_role("button", name="Use this folder", exact=True).click()
        expect(picker).not_to_be_visible()
        expect(department.get_by_label("Workspace directory", exact=True)).to_have_value(str(empty))

        department.get_by_role("button", name="Load models", exact=True).click()
        model = department.get_by_label("Model", exact=True)
        expect(model).to_be_enabled()
        model.select_option(label="Synthetic A · test / model-a")
        selected = model.input_value()
        department.get_by_role("button", name="Browse folders", exact=True).click()
        expect(picker.locator("#folder-location")).to_have_text(str(empty))
        picker.get_by_role("button", name="Up one folder", exact=True).click()
        expect(picker.locator("#folder-location")).to_have_text(str(parent))
        picker.get_by_role("button", name="Cancel", exact=True).click()
        expect(department.get_by_label("Workspace directory", exact=True)).to_have_value(str(empty))
        expect(model).to_have_value(selected)
        expect(department.get_by_role("button", name="Browse folders", exact=True)).to_be_focused()
        department.get_by_role("button", name="Save department", exact=True).click()
        expect(department).not_to_be_visible()
        original = next(lead for lead in snapshot()["leads"] if lead["handle"] == "paths")
        assert original["workspace"] == str(empty)

        page.get_by_role("button", name="Edit Pathfinder", exact=True).click()
        department = page.get_by_role("dialog", name="Edit department")
        model = department.get_by_label("Model", exact=True)
        department.get_by_role("button", name="Browse folders", exact=True).click()
        picker.get_by_role("button", name="Project folder", exact=True).click()
        expect(picker.locator("#folder-location")).to_have_text(str(ROOT))
        picker.get_by_role("button", name="Use this folder", exact=True).click()
        expect(model).to_be_disabled()
        expect(model).to_have_value("")
        expect(department.get_by_label("Role and instructions", exact=True)).to_have_value(
            "Check workspace setup"
        )
        department.get_by_role("button", name="Load models", exact=True).click()
        expect(model).to_be_enabled()
        model.select_option(label="Synthetic A · test / model-a")
        department.get_by_role("button", name="Save department", exact=True).click()
        expect(department).not_to_be_visible()
        changed = next(lead for lead in snapshot()["leads"] if lead["handle"] == "paths")
        assert changed["workspace"] == str(ROOT)
        assert changed["id"] == original["id"]
        assert changed["conversation_id"] != original["conversation_id"]
        assert errors == []
        context.close()


def test_mention_autocomplete_is_caret_aware_accessible_and_composition_safe(browser):
    context = browser.new_context()
    page = context.new_page()
    room_state = {
        "paused": True,
        "messages": [],
        "deliveries": [],
        "leads": [
            {
                "id": "atlas", "name": "Atlas", "handle": "atlas", "provider": "test",
                "model_id": "model-a", "workspace": "/workspace", "enabled": True,
                "permission": "discuss", "status": "running",
            },
            {
                "id": "canvas", "name": "Canvas", "handle": "canvas", "provider": "test",
                "model_id": "model-b", "workspace": "/workspace", "enabled": True,
                "permission": "discuss", "status": "queued",
            },
            {
                "id": "disabled", "name": "Disabled", "handle": "disabled", "provider": "test",
                "model_id": "model-c", "workspace": "/workspace", "enabled": False,
                "permission": "discuss", "status": "idle",
            },
            {
                "id": "deleted", "name": "Old team", "handle": "old", "provider": "test",
                "model_id": "model-d", "workspace": "/workspace", "enabled": True,
                "deleted": True, "permission": "discuss", "status": "idle",
            },
        ],
    }
    page.route(
        "**/api/state",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(room_state)
        ),
    )
    page.goto(ORIGIN + "/#token=" + TOKEN)
    composer = page.get_by_label("Message to the room", exact=True)
    composer.fill("@")
    choices = page.get_by_role("listbox", name="Available departments")
    expect(choices).to_be_visible()
    expect(choices.get_by_role("option", name="All departments, @all")).to_be_visible()
    expect(choices.get_by_role("option", name="Atlas, @atlas")).to_be_visible()
    expect(choices.get_by_role("option", name="Canvas, @canvas")).to_be_visible()
    expect(choices.get_by_role("option", name="Disabled, @disabled")).not_to_be_visible()
    expect(choices.get_by_role("option", name="Old team, @old")).not_to_be_visible()

    composer.press("ArrowDown")
    composer.press("Tab")
    expect(composer).to_have_value("@atlas")
    expect(choices).not_to_be_visible()
    page.wait_for_timeout(1200)
    expect(choices).not_to_be_visible()

    composer.fill("Discuss @can now")
    composer.evaluate(
        "node => { node.setSelectionRange(12, 12); "
        "node.dispatchEvent(new Event('click', {bubbles: true})); }"
    )
    expect(choices.get_by_role("option", name="Canvas, @canvas")).to_be_visible()
    composer.press("Enter")
    expect(composer).to_have_value("Discuss @canvas now")

    composer.fill("mail@can")
    expect(choices).not_to_be_visible()
    composer.fill("@can")
    composer.dispatch_event("compositionstart")
    expect(choices).not_to_be_visible()
    composer.dispatch_event("compositionend")
    expect(choices.get_by_role("option", name="Canvas, @canvas")).to_be_visible()
    composer.press("Escape")
    expect(choices).not_to_be_visible()
    page.wait_for_timeout(1200)
    expect(choices).not_to_be_visible()
    composer.fill("@can")
    expect(choices.get_by_role("option", name="Canvas, @canvas")).to_be_visible()
    page.get_by_role("button", name="Add department", exact=True).focus()
    expect(choices).not_to_be_visible()
    page.wait_for_timeout(1200)
    expect(choices).not_to_be_visible()
    composer.fill("@can")
    choices.get_by_role("option", name="Canvas, @canvas").click()
    expect(composer).to_have_value("@canvas")
    page.wait_for_timeout(1200)
    expect(choices).not_to_be_visible()
    context.close()


def test_delete_department_confirmation_uses_revision_and_blocks_busy_departments(browser):
    context = browser.new_context()
    page = context.new_page()
    lead = {
        "id": "atlas", "name": "Atlas", "handle": "atlas", "provider": "test",
        "model_id": "model-a", "workspace": "/workspace", "enabled": True,
        "permission": "discuss", "status": "idle", "revision": 4,
    }
    room_state = {"paused": False, "messages": [], "deliveries": [], "leads": [lead]}
    deleted_requests = []

    page.route(
        "**/api/state",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(room_state)
        ),
    )

    def delete_atlas(route):
        deleted_requests.append(route.request)
        assert route.request.method == "DELETE"
        room_state["leads"] = []
        route.fulfill(
            status=200,
            json={"id": "atlas", "revision": 5, "deleted_at": "2026-11-20T04:00:00+00:00"},
        )

    page.route("**/api/leads/atlas*", delete_atlas)
    page.goto(ORIGIN + "/#token=" + TOKEN)
    composer = page.get_by_label("Message to the room", exact=True)
    composer.fill("Keep this draft")
    page.get_by_role("button", name="Edit Atlas", exact=True).click()
    department = page.get_by_role("dialog", name="Edit department")
    department.get_by_role("button", name="Delete department…", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Delete department")
    expect(confirmation.get_by_text("public room history", exact=False)).to_be_visible()
    expect(confirmation.get_by_text("workspace files are retained", exact=False)).to_be_visible()
    expect(confirmation.get_by_text("handle remains reserved", exact=False)).to_be_visible()
    delete_input = confirmation.get_by_label("Type the department handle to confirm", exact=True)
    delete_input.fill("@atlas")
    confirmation.get_by_role("button", name="Delete department", exact=True).click()
    expect(confirmation).not_to_be_visible()
    expect(page.get_by_role("button", name="Edit Atlas", exact=True)).not_to_be_visible()
    expect(page.get_by_text("Name your first department", exact=True)).to_be_visible()
    expect(composer).to_have_value("Keep this draft")
    assert len(deleted_requests) == 1
    assert "revision=4" in deleted_requests[0].url

    room_state["leads"] = [{**lead, "status": "running"}]
    page.reload()
    page.get_by_role("button", name="Edit Atlas", exact=True).click()
    department = page.get_by_role("dialog", name="Edit department")
    department.get_by_role("button", name="Delete department…", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Delete department")
    expect(
        confirmation.get_by_text("queued, running or stopping work", exact=False)
    ).to_be_visible()
    expect(confirmation.get_by_text("Pause & stop", exact=False)).to_be_visible()
    expect(
        confirmation.get_by_role("button", name="Delete department", exact=True)
    ).to_be_disabled()
    assert len(deleted_requests) == 1
    context.close()


def test_workspace_folder_picker_error_recovery_and_mobile_focus(browser):
    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = context.new_page()
    failures = 0

    def unavailable_once(route):
        nonlocal failures
        if failures == 0:
            failures += 1
            route.fulfill(status=422, json={"detail": "This folder is not accessible."})
        else:
            route.continue_()

    page.route("**/api/folders*", unavailable_once)
    page.goto(ORIGIN + "/#token=" + TOKEN)
    page.get_by_role("button", name="Add department", exact=True).click()
    department = page.get_by_role("dialog", name="New department")
    department.get_by_role("button", name="Browse folders", exact=True).click()
    picker = page.get_by_role("dialog", name="Choose workspace folder")
    expect(picker.get_by_text("This folder is not accessible.", exact=True)).to_be_visible()
    expect(picker.get_by_role("button", name="Use this folder", exact=True)).to_be_disabled()
    picker.get_by_role("button", name="Project folder", exact=True).click()
    expect(picker.locator("#folder-location")).to_have_text(str(ROOT))
    expect(picker.get_by_role("button", name="Use this folder", exact=True)).to_be_enabled()
    assert picker.evaluate("node => node.scrollWidth <= node.clientWidth")
    ARTIFACTS.mkdir(exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / "folder-picker-mobile.png"), full_page=True)
    page.keyboard.press("Escape")
    expect(picker).not_to_be_visible()
    expect(department).to_be_visible()
    expect(department.get_by_role("button", name="Browse folders", exact=True)).to_be_focused()
    expect(department.get_by_label("Workspace directory", exact=True)).to_have_value("")
    page.keyboard.press("Escape")
    expect(department).not_to_be_visible()
    expect(page.get_by_role("button", name="Add department", exact=True)).to_be_focused()
    context.close()
