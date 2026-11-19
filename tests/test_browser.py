import json
import os
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
    dialog.get_by_label("Workspace directory", exact=True).fill(str(ROOT))
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
