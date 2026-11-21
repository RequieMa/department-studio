import pytest

from department_studio.domain import Conflict, Invalid
from tests.factories import create_lead


def edges(graph):
    return {(edge["a"], edge["b"]) for edge in graph["edges"]}


def test_new_departments_start_with_a_complete_bidirectional_graph(store, tmp_path):
    alpha = create_lead(store, tmp_path, "alpha", name="Alpha")
    beta = create_lead(store, tmp_path, "beta", name="Beta")
    gamma = create_lead(store, tmp_path, "gamma", name="Gamma")
    graph = store.hierarchy()
    assert [node["handle"] for node in graph["nodes"]] == ["alpha", "beta", "gamma"]
    assert edges(graph) == {
        tuple(sorted((alpha.id, beta.id))),
        tuple(sorted((alpha.id, gamma.id))),
        tuple(sorted((beta.id, gamma.id))),
    }
    assert store.can_address(alpha.id, beta.id) is True
    assert store.can_address(beta.id, alpha.id) is True
    assert store.can_address(alpha.id, alpha.id) is False


def test_removing_and_adding_an_edge_is_symmetric(store, tmp_path):
    alpha = create_lead(store, tmp_path, "alpha")
    beta = create_lead(store, tmp_path, "beta")
    graph = store.set_hierarchy_edge(alpha.id, beta.id, False)
    assert edges(graph) == set()
    assert store.can_address(alpha.id, beta.id) is False
    assert store.can_address(beta.id, alpha.id) is False
    graph = store.set_hierarchy_edge(beta.id, alpha.id, True)
    assert edges(graph) == {tuple(sorted((alpha.id, beta.id)))}
    assert store.can_address(alpha.id, beta.id) is True
    with pytest.raises(Invalid, match="itself"):
        store.set_hierarchy_edge(alpha.id, alpha.id, False)


def test_new_department_links_to_existing_and_deletion_removes_its_edges(store, tmp_path):
    alpha = create_lead(store, tmp_path, "alpha")
    beta = create_lead(store, tmp_path, "beta")
    gamma = create_lead(store, tmp_path, "gamma")
    assert len(edges(store.hierarchy())) == 3
    store.delete_lead(gamma.id, gamma.revision)
    remaining = store.hierarchy()
    assert {node["handle"] for node in remaining["nodes"]} == {"alpha", "beta"}
    assert edges(remaining) == {tuple(sorted((alpha.id, beta.id)))}


def test_bridge_recipients_are_rejected_when_the_edge_is_disconnected(store, tmp_path):
    alpha = create_lead(store, tmp_path, "alpha")
    gamma = create_lead(store, tmp_path, "gamma")
    store.set_hierarchy_edge(alpha.id, gamma.id, False)
    store.resume()
    store.post_human_message("@alpha start")
    delivery = store.claim_delivery()
    with pytest.raises(Conflict, match="@gamma"):
        store.post_bridge_message(
            delivery.id, delivery.generation, "call-1", "Peer request", ["gamma"]
        )
    assert not [m for m in store.list_messages() if m.text == "Peer request"]
    store.set_hierarchy_edge(alpha.id, gamma.id, True)
    receipt = store.post_bridge_message(
        delivery.id, delivery.generation, "call-2", "Peer request", ["gamma"]
    )
    assert receipt.recipient_ids == [gamma.id]


def test_connect_all_restores_missing_edges(store, tmp_path):
    alpha = create_lead(store, tmp_path, "alpha")
    beta = create_lead(store, tmp_path, "beta")
    gamma = create_lead(store, tmp_path, "gamma")
    store.set_hierarchy_edge(alpha.id, beta.id, False)
    store.set_hierarchy_edge(beta.id, gamma.id, False)
    graph = store.connect_all_departments()
    assert len(edges(graph)) == 3
