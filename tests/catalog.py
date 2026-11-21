"""Deterministic model catalog for tests; never a live provider."""

from department_studio.models import ModelCatalog

TEST_CATALOG = ModelCatalog.parse(
    """
[[providers]]
id = "test"
name = "Synthetic"
api = "openai-completions"
base_url = "https://models.example.invalid/v1"
anthropic_base_url = "https://models.example.invalid/anthropic"

[[providers.models]]
id = "model-a"
name = "Synthetic A"
context_window = 128000
max_output_tokens = 16000
runtimes = ["pi", "claude", "deepseek"]

[[providers.models]]
id = "model-b"
name = "Synthetic B"
context_window = 128000
max_output_tokens = 16000
runtimes = ["pi", "claude", "deepseek"]

[[providers.models]]
id = "model-c"
name = "Synthetic C"
context_window = 128000
max_output_tokens = 16000
runtimes = ["pi", "claude", "deepseek"]

[[providers.models]]
id = "model-d"
name = "Synthetic D"
context_window = 128000
max_output_tokens = 16000
runtimes = ["pi", "claude", "deepseek"]

[[providers.models]]
id = "fixture"
name = "Fixture"
context_window = 128000
max_output_tokens = 16000
runtimes = ["pi", "claude", "deepseek"]
"""
)
