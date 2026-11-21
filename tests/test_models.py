from pathlib import Path

import pytest

from department_studio.models import ModelCatalogError, load_catalog

CATALOG = """
[[providers]]
id = "gateway"
name = "Local Gateway"
api = "openai-completions"
base_url = "https://gateway.example/v1"
api_key_env = "GATEWAY_KEY"

[providers.pi_compat]
requiresReasoningContentOnAssistantMessages = true
thinkingFormat = "deepseek"

[[providers.models]]
id = "model-fast"
name = "Fast"
context_window = 128000
max_output_tokens = 16000
runtimes = ["pi", "claude", "deepseek"]

[[providers.models]]
id = "model-claude-only"
name = "Claude only"
context_window = 200000
max_output_tokens = 32000
runtimes = ["claude"]
"""


def catalog_file(tmp_path: Path, text: str = CATALOG) -> Path:
    path = tmp_path / "models.toml"
    path.write_text(text)
    return path


def test_default_catalog_contains_deepseek_v4_flash_and_pro():
    catalog = load_catalog()
    models = {(item.provider, item.id): item for item in catalog.options()}
    assert ("deepseek", "deepseek-v4-flash") in models
    assert ("deepseek", "deepseek-v4-pro") in models
    assert models[("deepseek", "deepseek-v4-flash")].context_window == 1_000_000
    assert models[("deepseek", "deepseek-v4-pro")].name == "DeepSeek V4 Pro"
    assert all(model.provider == "deepseek" for model in catalog.options())


def test_configured_catalog_is_loaded_and_filtered_by_runtime(tmp_path):
    catalog = load_catalog(catalog_file(tmp_path))
    assert [model.id for model in catalog.options("pi")] == ["model-fast"]
    assert [model.id for model in catalog.options("claude")] == [
        "model-fast",
        "model-claude-only",
    ]
    assert [model.id for model in catalog.options("deepseek")] == ["model-fast"]
    assert all(model.runtimes == ("pi", "claude", "deepseek") for model in catalog.options()[:1])


def test_selection_exposes_provider_and_optional_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "secret-value")
    catalog = load_catalog(catalog_file(tmp_path))
    selection = catalog.require("gateway", "model-fast", "pi")
    assert selection.provider.base_url == "https://gateway.example/v1"
    assert selection.model.id == "model-fast"
    assert selection.api_key == "secret-value"
    assert selection.provider.pi_compat["thinkingFormat"] == "deepseek"


def test_missing_credential_is_actionable_without_exposing_a_value(tmp_path, monkeypatch):
    monkeypatch.delenv("GATEWAY_KEY", raising=False)
    catalog = load_catalog(catalog_file(tmp_path))
    selection = catalog.require("gateway", "model-fast", "pi")
    assert selection.api_key is None
    with pytest.raises(ModelCatalogError, match="GATEWAY_KEY"):
        selection.require_api_key()


@pytest.mark.parametrize(
    "old_text,new_text,expected",
    [
        ('api = "openai-completions"', 'api = "anthropic-messages"', "openai-completions"),
        ('id = "gateway"', 'id = "Bad Provider"', "provider id"),
        ("context_window = 128000", "context_window = 0", "context_window"),
        ("max_output_tokens = 16000", "max_output_tokens = 999999999", "max_output_tokens"),
        ('runtimes = ["pi", "claude", "deepseek"]', 'runtimes = ["unknown"]', "runtime"),
        (
            'base_url = "https://gateway.example/v1"',
            'base_url = "https://user:pass@gateway.example/v1"',
            "base_url",
        ),
        ('api_key_env = "GATEWAY_KEY"', 'api_key_env = "not a name"', "api_key_env"),
    ],
)
def test_invalid_catalog_entries_are_rejected(tmp_path, old_text, new_text, expected):
    text = CATALOG.replace(old_text, new_text)
    with pytest.raises(ModelCatalogError, match=expected):
        load_catalog(catalog_file(tmp_path, text))


def test_duplicate_model_ids_are_rejected(tmp_path):
    text = CATALOG.replace('id = "model-claude-only"', 'id = "model-fast"')
    with pytest.raises(ModelCatalogError, match="Duplicate"):
        load_catalog(catalog_file(tmp_path, text))


def test_unknown_or_unsupported_model_is_rejected(tmp_path):
    catalog = load_catalog(catalog_file(tmp_path))
    with pytest.raises(ModelCatalogError, match="not configured"):
        catalog.require("gateway", "missing", "pi")
    with pytest.raises(ModelCatalogError, match="not available"):
        catalog.require("gateway", "model-claude-only", "pi")


def test_catalog_file_errors_are_actionable(tmp_path):
    with pytest.raises(ModelCatalogError, match="could not be read"):
        load_catalog(tmp_path / "missing.toml")
    with pytest.raises(ModelCatalogError, match="invalid TOML"):
        load_catalog(catalog_file(tmp_path, "providers = ["))


def test_default_catalog_is_self_contained():
    from department_studio import models

    source = Path(models.__file__).with_name("default_models.toml").read_text()
    assert 'api = "openai-completions"' in source
    assert "deepseek-v4-flash" in source
    assert "deepseek-v4-pro" in source
