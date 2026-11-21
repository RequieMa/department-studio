import uuid
from time import monotonic

import httpx
from playwright.sync_api import expect

from tests.test_browser import ORIGIN, ROOT, TOKEN
from tests.test_browser import browser as browser

pytestmark = __import__("pytest").mark.browser


def client():
    return httpx.Client(base_url=ORIGIN, headers={"Authorization": "Bearer " + TOKEN}, timeout=10)


def wait_for(page, predicate, timeout=8):
    deadline = monotonic() + timeout
    while not predicate():
        assert monotonic() < deadline, "Timed out waiting for browser state"
        page.wait_for_timeout(40)


def project_state(http):
    return http.get("/api/projects").json()


def create_project(http, name):
    response = http.post("/api/projects", json={"name": name})
    response.raise_for_status()
    return response.json()["project"]


def switch_project(http, project_id):
    response = http.post(f"/api/projects/{project_id}/activate")
    response.raise_for_status()
    return response.json()


def delete_project(http, project):
    response = http.delete(
        f"/api/projects/{project['id']}", params={"confirm_name": project["name"]}
    )
    response.raise_for_status()


def create_department(http, handle, name):
    response = http.post(
        "/api/leads",
        json={
            "name": name,
            "handle": handle,
            "role": "Synthetic browser verification",
            "provider": "test",
            "model_id": "model-a",
            "workspace": str(ROOT),
        },
    )
    response.raise_for_status()
    return response.json()


def cleanup_project(http, original_id, project):
    current = project_state(http)
    if current["active_id"] != original_id:
        switch_project(http, original_id)
    try:
        delete_project(http, project)
    except httpx.HTTPStatusError:
        pass


def test_project_history_switch_records_theme_and_delete(browser):
    http = client()
    original = project_state(http)
    original_name = next(
        item["name"] for item in original["projects"] if item["id"] == original["active_id"]
    )
    name = f"Browser project {uuid.uuid4().hex[:8]}"
    project = None
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(ORIGIN + "/#token=" + TOKEN)
        expect(page.locator("#active-project-name")).to_have_text(original_name)

        page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert (
            page.evaluate("getComputedStyle(document.documentElement).backgroundColor")
            == "rgb(11, 17, 23)"
        )
        page.reload()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")

        page.locator("#projects-toggle").click()
        page.get_by_label("New project name").fill(name)
        page.get_by_role("button", name="Create project", exact=True).click()
        expect(page.locator("#active-project-name")).to_have_text(name)
        expect(page.get_by_text("Name your first department", exact=True)).to_be_visible()
        project = next(item for item in project_state(http)["projects"] if item["name"] == name)

        page.locator("#records-toggle").click()
        dialog = page.get_by_role("dialog", name="Project records")
        expect(dialog.locator("#records-path")).to_contain_text("records")
        dialog.get_by_label("New record filename").fill("2026-11-21-browser-audit.md")
        dialog.get_by_label("Content").fill("# Browser audit\n\nDurable evidence.")
        dialog.get_by_role("button", name="Save record", exact=True).click()
        entry = dialog.locator(".record-entry", has_text="2026-11-21-browser-audit.md")
        expect(entry).to_be_visible()
        entry.click()
        expect(dialog.locator("#records-content")).to_contain_text("Durable evidence.")
        dialog.get_by_role("button", name="Close", exact=True).first.click()

        page.locator("#projects-toggle").click()
        row = page.locator(".project-row", has_text=original_name)
        row.get_by_role("button", name="Switch", exact=True).click()
        expect(page.locator("#active-project-name")).to_have_text(original_name)
        page.locator("#projects-toggle").click()
        page.once("dialog", lambda confirmation: confirmation.accept())
        row = page.locator(".project-row", has_text=name)
        row.get_by_role("button", name="Delete…", exact=True).click()
        expect(page.locator(".project-row", has_text=name)).to_have_count(0)
        project = None
        assert errors == []
    finally:
        if project is not None:
            cleanup_project(http, original["active_id"], project)
        http.close()
        context.close()


def test_hierarchy_graph_and_peer_message_collapses(browser):
    http = client()
    original = project_state(http)
    suffix = uuid.uuid4().hex[:6]
    project = create_project(http, f"Hierarchy {suffix}")
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        first = create_department(http, f"one{suffix}", "Hierarchy One")
        second = create_department(http, f"two{suffix}", "Hierarchy Two")
        page.goto(ORIGIN + "/#token=" + TOKEN)
        expect(page.locator("#active-project-name")).to_have_text(project["name"])
        page.locator("#hierarchy-toggle").click()
        dialog = page.get_by_role("dialog", name="Department hierarchy")
        expect(dialog.locator(".hierarchy-node")).to_have_count(2)
        expect(dialog.locator(".hierarchy-edge-group")).to_have_count(1)
        dialog.locator(".hierarchy-edge-hit").click(force=True)
        wait_for(page, lambda: len(http.get("/api/hierarchy").json()["edges"]) == 0)
        expect(dialog.locator("#hierarchy-status")).to_contain_text("Disconnected")
        dialog.locator(".hierarchy-node").nth(0).click(force=True)
        dialog.locator(".hierarchy-node").nth(1).click(force=True)
        wait_for(page, lambda: len(http.get("/api/hierarchy").json()["edges"]) == 1)
        expect(dialog.locator("#hierarchy-status")).to_contain_text("Connected")
        dialog.get_by_role("button", name="Done", exact=True).click()

        page.get_by_role("button", name="Resume room", exact=True).click()
        expect(page.get_by_text("Room running", exact=True)).to_be_visible()
        composer = page.get_by_label("Message to the room", exact=True)
        composer.fill(f"@{first['handle']} synthetic peer to {second['handle']}")
        page.get_by_role("button", name="Send message", exact=True).click()
        summary = page.locator(".message-collapse", has_text="Hierarchy One → Hierarchy Two").first
        expect(summary).to_be_visible()
        article = summary.locator("xpath=..")
        expect(article.locator(".message-detail")).to_be_hidden()
        summary.click()
        expect(article.locator(".message-detail")).to_be_visible()
        expect(article.locator(".message-text")).to_contain_text("Synthetic peer request")
        assert errors == []
    finally:
        cleanup_project(http, original["active_id"], project)
        http.close()
        context.close()


def test_unaddressed_message_continues_and_public_note_opts_out(browser):
    http = client()
    original = project_state(http)
    suffix = uuid.uuid4().hex[:6]
    project = create_project(http, f"Addressing {suffix}")
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        first = create_department(http, f"addr{suffix}", "Addressing One")
        create_department(http, f"other{suffix}", "Addressing Two")
        page.goto(ORIGIN + "/#token=" + TOKEN)
        expect(page.locator("#active-project-name")).to_have_text(project["name"])
        page.get_by_role("button", name="Resume room", exact=True).click()
        expect(page.get_by_text("Room running", exact=True)).to_be_visible()
        composer = page.get_by_label("Message to the room", exact=True)
        composer.fill(f"@{first['handle']} first request")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(
            page.get_by_text("Synthetic test reply from Addressing One.", exact=True)
        ).to_be_visible()
        before = len(
            [m for m in http.get("/api/state").json()["messages"] if m["sender_kind"] == "human"]
        )

        composer.fill("follow without a mention")
        expect(page.locator("#recipient-preview")).to_contain_text(
            f"Continuing with @{first['handle']}"
        )
        page.get_by_role("button", name="Send message", exact=True).click()
        wait_for(
            page,
            lambda: (
                len(
                    [
                        m
                        for m in http.get("/api/state").json()["messages"]
                        if m["sender_kind"] == "human"
                    ]
                )
                == before + 1
            ),
        )
        humans = [
            m for m in http.get("/api/state").json()["messages"] if m["sender_kind"] == "human"
        ]
        assert humans[-1]["recipient_ids"] == [first["id"]]

        composer.fill("public update")
        page.locator("#public-note").check()
        expect(page.locator("#recipient-preview")).to_contain_text("Public note")
        page.get_by_role("button", name="Send message", exact=True).click()
        wait_for(
            page,
            lambda: (
                len(
                    [
                        m
                        for m in http.get("/api/state").json()["messages"]
                        if m["sender_kind"] == "human"
                    ]
                )
                == before + 2
            ),
        )
        humans = [
            m for m in http.get("/api/state").json()["messages"] if m["sender_kind"] == "human"
        ]
        assert humans[-1]["recipient_ids"] == []
        assert http.get("/api/state").json()["active_recipient_ids"] == [first["id"]]
        assert errors == []
    finally:
        cleanup_project(http, original["active_id"], project)
        http.close()
        context.close()


def test_dark_mode_follows_system_without_a_stored_choice(browser):
    http = client()
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="dark")
    page = context.new_page()
    try:
        page.goto(ORIGIN + "/#token=" + TOKEN)
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        page.reload()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
    finally:
        http.close()
        context.close()
