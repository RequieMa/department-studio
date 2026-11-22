import pytest

from department_studio.domain import Conflict, Invalid
from tests.factories import create_lead


def test_empty_workspace_does_not_silently_select_server_working_directory(store, tmp_path):
    with pytest.raises(Invalid, match="existing local directory"):
        create_lead(store, tmp_path, workspace="")


def test_user_names_and_rename_preserve_identity(store, tmp_path):
    assert store.list_leads() == []
    lead = create_lead(store, tmp_path)
    post = store.post_public_reply(lead.id, "Contract recorded")
    renamed = store.update_lead(lead.id, lead.revision, {"name": "Foundry", "handle": "forge"})
    assert renamed.id == lead.id
    assert renamed.conversation_id == lead.conversation_id
    assert renamed.role == "Build the backend"
    assert renamed.backend_kind == "pi"
    assert store.list_messages()[0].id == post.id
    assert store.list_messages()[0].sender_name == "星图 Studio"
    assert store.list_messages()[0].sender_handle == "atlas"
    assert store.resolve_mentions("@forge review this") == [lead.id]
    with pytest.raises(Invalid, match="atlas"):
        store.resolve_mentions("@atlas review")


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", " "),
        ("name", "a" * 81),
        ("handle", "all"),
        ("handle", "you"),
        ("handle", "system"),
        ("handle", "123"),
        ("handle", "some department"),
        ("handle", "a" * 33),
        ("role", ""),
        ("role", "r" * 8001),
        ("provider", ""),
        ("provider", "x" * 201),
        ("model_id", ""),
        ("workspace", "/missing/department-studio-directory"),
        ("backend_kind", "a2a"),
    ],
)
def test_invalid_configuration(store, tmp_path, field, value):
    with pytest.raises((Invalid, ValueError)):
        create_lead(store, tmp_path, **{field: value})


def test_handles_are_normalized_and_unique(store, tmp_path):
    lead = create_lead(store, tmp_path, "ATLAS")
    assert lead.handle == "atlas"
    with pytest.raises(Conflict, match="handle"):
        create_lead(store, tmp_path, "Atlas", name="Other")


def test_workspace_must_be_directory_and_is_canonical(store, tmp_path):
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises((Invalid, ValueError)):
        create_lead(store, file)
    link = tmp_path / "linked"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert create_lead(store, link).workspace == str(tmp_path)


def test_workspace_change_creates_session_but_retains_audit(store, tmp_path):
    lead = create_lead(store, tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    changed = store.update_lead(lead.id, lead.revision, {"workspace": str(other)})
    assert changed.id == lead.id
    assert changed.conversation_id != lead.conversation_id
    assert {r["conversation_id"] for r in store.list_session_refs(lead.id)} == {
        lead.conversation_id,
        changed.conversation_id,
    }


def test_revision_conflict_and_model_change(store, tmp_path):
    lead = create_lead(store, tmp_path)
    changed = store.update_lead(lead.id, lead.revision, {"model_id": "exact-model-b"})
    assert changed.conversation_id == lead.conversation_id
    assert changed.revision == lead.revision + 1
    with pytest.raises(Conflict, match="revision"):
        store.update_lead(lead.id, lead.revision, {"name": "Old editor"})


@pytest.mark.parametrize("state", ["queued", "running", "stopping"])
def test_busy_edits_rejected(store, tmp_path, state):
    lead = create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas work")
    if state != "queued":
        store.claim_delivery()
    if state == "stopping":
        store.pause()
    with pytest.raises(Conflict, match="busy"):
        store.update_lead(lead.id, lead.revision, {"name": "Changed"})


def test_two_leads_sharing_workspace_have_distinct_identity_and_session(store, tmp_path):
    a = create_lead(store, tmp_path, "atlas")
    b = create_lead(store, tmp_path, "canvas", name="Canvas", role="Review interfaces")
    assert a.id != b.id
    assert a.conversation_id != b.conversation_id
    assert a.role != b.role


def test_runtime_change_starts_a_fresh_native_conversation(store, tmp_path):
    lead = create_lead(store, tmp_path)
    changed = store.update_lead(lead.id, lead.revision, {"backend_kind": "claude"})
    assert changed.backend_kind == "claude"
    assert changed.conversation_id != lead.conversation_id
    refs = {item["conversation_id"] for item in store.list_session_refs(lead.id)}
    assert {lead.conversation_id, changed.conversation_id} <= refs


def test_worker_model_is_optional_but_paired(store, tmp_path):
    lead = create_lead(store, tmp_path)
    assert (lead.worker_provider, lead.worker_model_id) == ("", "")
    changed = store.update_lead(
        lead.id,
        lead.revision,
        {"worker_provider": "test", "worker_model_id": "model-b"},
    )
    assert (changed.worker_provider, changed.worker_model_id) == ("test", "model-b")
    with pytest.raises(Invalid):
        create_lead(store, tmp_path, worker_provider="test")
    with pytest.raises(Invalid):
        create_lead(store, tmp_path, worker_model_id="model-b")


def test_legacy_permission_setting_is_ignored(store, tmp_path):
    import json

    lead = create_lead(store, tmp_path)
    settings = json.loads(
        store._db.execute("SELECT settings FROM leads WHERE id=?", (lead.id,)).fetchone()[
            "settings"
        ]
    )
    settings["permission"] = "develop"
    settings.pop("worker_provider", None)
    settings.pop("worker_model_id", None)
    with store._transaction():
        store._db.execute(
            "UPDATE leads SET settings=? WHERE id=?",
            (json.dumps(settings), lead.id),
        )
    loaded = store.get_lead(lead.id)
    assert not hasattr(loaded, "permission")
    assert (loaded.worker_provider, loaded.worker_model_id) == ("", "")
