import pytest

from department_studio.domain import Conflict, Invalid, NotFound
from department_studio.records import MAX_CONTENT_BYTES, RecordStore
from tests.fakes import until
from tests.test_api import http_app as http_app
from tests.test_api import lead_body


def test_record_store_creates_template_and_supports_create_append_read(tmp_path):
    records = RecordStore(tmp_path / "records").ensure()
    assert (tmp_path / "records" / "README.md").is_file()
    created = records.write("2026-11-21-audit.md", "# Audit\n", "create")
    assert created["path"].endswith("2026-11-21-audit.md")
    assert records.read("2026-11-21-audit.md")["content"] == "# Audit\n"
    records.write("2026-11-21-audit.md", "More evidence", "append")
    assert "More evidence" in records.read("2026-11-21-audit.md")["content"]
    records.write("2026-11-21-audit.md", "Replacement", "replace")
    assert records.read("2026-11-21-audit.md")["content"] == "Replacement"
    assert any(item["name"] == "2026-11-21-audit.md" for item in records.list())
    with pytest.raises(Conflict):
        records.write("2026-11-21-audit.md", "again", "create")


@pytest.mark.parametrize(
    "name",
    ["../../escape.md", "/tmp/escape.md", "no-extension", ".hidden.md", "bad name.md"],
)
def test_record_names_are_flat_markdown_filenames(tmp_path, name):
    records = RecordStore(tmp_path / "records")
    with pytest.raises(Invalid):
        records.write(name, "content")
    with pytest.raises(Invalid):
        records.read(name)


def test_record_content_is_bounded_and_missing_is_not_found(tmp_path):
    records = RecordStore(tmp_path / "records")
    with pytest.raises(Invalid, match="large"):
        records.write("big.md", "x" * (MAX_CONTENT_BYTES + 1))
    with pytest.raises(NotFound):
        records.read("missing.md")


async def test_owner_records_api_create_list_read_and_append(http_app):
    client, _, _ = http_app
    created = await client.post(
        "/api/records",
        json={"name": "2026-11-21-audit.md", "content": "# Audit\n"},
    )
    assert created.status_code == 201
    listing = (await client.get("/api/records")).json()
    assert listing["records"][0]["name"] == "README.md" or any(
        item["name"] == "2026-11-21-audit.md" for item in listing["records"]
    )
    read = await client.get("/api/records/2026-11-21-audit.md")
    assert read.status_code == 200
    assert read.json()["content"] == "# Audit\n"
    appended = await client.put(
        "/api/records/2026-11-21-audit.md",
        json={"name": "2026-11-21-audit.md", "content": "More", "mode": "append"},
    )
    assert appended.status_code == 200
    assert "More" in (await client.get("/api/records/2026-11-21-audit.md")).json()["content"]
    assert (await client.get("/api/records", headers={"Authorization": ""})).status_code == 401


async def test_runtime_bridge_records_are_scoped_to_an_active_delivery(http_app, tmp_path):
    client, app, _ = http_app
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    await client.post("/api/room/resume")
    await until(lambda: not app.state.store.paused)
    await client.post("/api/messages", json={"text": "@atlas record this"})
    await until(lambda: app.state.service._tokens)
    token = next(iter(app.state.service._tokens))
    unauthorized = await client.get(
        "/api/bridge/records", headers={"Authorization": "Bearer wrong"}
    )
    assert unauthorized.status_code == 401
    written = await client.post(
        "/api/bridge/records",
        headers={"Authorization": "Bearer " + token},
        json={"name": "2026-11-21-runtime.md", "content": "# Runtime note\n", "mode": "append"},
    )
    assert written.status_code == 200
    listed = await client.get("/api/bridge/records", headers={"Authorization": "Bearer " + token})
    assert any(item["name"] == "2026-11-21-runtime.md" for item in listed.json()["records"])
    read = await client.get(
        "/api/bridge/records/2026-11-21-runtime.md",
        headers={"Authorization": "Bearer " + token},
    )
    assert read.status_code == 200 and "# Runtime note" in read.json()["content"]
    # The browser owner credential cannot use runtime-only bridge routes.
    owner_bridge = await client.get("/api/bridge/records")
    assert owner_bridge.status_code == 403
    assert lead["id"]
