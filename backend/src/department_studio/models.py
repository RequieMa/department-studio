"""User-configured OpenAI-compatible model catalog.

Department Studio owns model selection. Runtimes translate a catalog entry into
their own flags or environment; no runtime's provider list is treated as the
catalog. Only OpenAI-compatible HTTP roots are accepted in this increment.
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from department_studio.backends.base import ModelOption

RUNTIMES = {"pi": "Pi", "claude": "Claude Code", "deepseek": "DeepSeek Harness"}
SUPPORTED_API = "openai-completions"
DEFAULT_CATALOG = Path(__file__).with_name("default_models.toml")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_SAFE_COMPAT_TYPES = (str, bool, int, float)


class ModelCatalogError(ValueError):
    """A public, actionable catalog or selection failure."""


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    context_window: int
    max_output_tokens: int
    reasoning: bool
    runtimes: tuple[str, ...]

    def supports(self, runtime: str) -> bool:
        return runtime in self.runtimes


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    api: str
    base_url: str
    anthropic_base_url: str | None
    api_key_env: str | None
    pi_compat: dict
    models: tuple[Model, ...]


@dataclass(frozen=True)
class ModelSelection:
    provider: Provider
    model: Model
    api_key: str | None

    def require_api_key(self) -> str | None:
        if self.provider.api_key_env and not self.api_key:
            raise ModelCatalogError(
                f"No API key is set for provider '{self.provider.id}'. Set "
                f"{self.provider.api_key_env} in the environment that launches "
                "Department Studio."
            )
        return self.api_key


def _text(value, name: str, *, maximum: int = 200, pattern=None) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ModelCatalogError(f"Model configuration field '{name}' is invalid.")
    value = value.strip()
    if pattern is not None and not pattern.fullmatch(value):
        raise ModelCatalogError(f"Model configuration field '{name}' has an invalid value.")
    return value


def _http_url(value, name: str) -> str:
    text = _text(value, name, maximum=2048)
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise ModelCatalogError(f"Model configuration field '{name}' is not a valid URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ModelCatalogError(
            f"Model configuration field '{name}' must be an HTTP(S) URL without "
            "credentials, query or fragment."
        )
    return text


def _positive_int(value, name: str, *, maximum: int = 100_000_000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ModelCatalogError(f"Model configuration field '{name}' must be a positive integer.")
    return value


def _compat(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 32:
        raise ModelCatalogError("Model configuration field 'pi_compat' must be a table.")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 100:
            raise ModelCatalogError("Model configuration field 'pi_compat' has an invalid key.")
        if isinstance(item, list):
            if len(item) > 32 or not all(isinstance(entry, _SAFE_COMPAT_TYPES) for entry in item):
                raise ModelCatalogError(
                    "Model configuration field 'pi_compat' has an invalid value."
                )
            result[key] = list(item)
        elif isinstance(item, _SAFE_COMPAT_TYPES):
            result[key] = item
        elif (
            isinstance(item, dict)
            and len(item) <= 32
            and all(
                isinstance(k, str) and isinstance(v, (str, bool, int, float))
                for k, v in item.items()
            )
        ):
            result[key] = dict(item)
        else:
            raise ModelCatalogError("Model configuration field 'pi_compat' has an invalid value.")
    return result


def _runtimes(value) -> tuple[str, ...]:
    if value is None:
        return tuple(RUNTIMES)
    if not isinstance(value, list) or not value:
        raise ModelCatalogError("Model configuration field 'runtimes' must be a non-empty list.")
    result = []
    for item in value:
        if not isinstance(item, str) or item not in RUNTIMES:
            raise ModelCatalogError(
                "Model configuration field 'runtimes' must name pi, claude or deepseek."
            )
        if item not in result:
            result.append(item)
    return tuple(result)


def _model(raw, provider_id: str, seen: set[str]) -> Model:
    if not isinstance(raw, dict):
        raise ModelCatalogError("Each model entry must be a table.")
    model_id = _text(raw.get("id"), "id", pattern=_IDENTIFIER)
    if model_id in seen:
        raise ModelCatalogError(f"Duplicate model id '{model_id}' in provider '{provider_id}'.")
    seen.add(model_id)
    context_window = _positive_int(raw.get("context_window"), "context_window")
    max_output_tokens = _positive_int(raw.get("max_output_tokens"), "max_output_tokens")
    if max_output_tokens >= context_window:
        raise ModelCatalogError(
            f"Model '{model_id}' max_output_tokens must be smaller than context_window."
        )
    reasoning = raw.get("reasoning", True)
    if type(reasoning) is not bool:
        raise ModelCatalogError(f"Model '{model_id}' reasoning must be a boolean.")
    return Model(
        id=model_id,
        name=_text(raw.get("name", model_id), "name"),
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        reasoning=reasoning,
        runtimes=_runtimes(raw.get("runtimes")),
    )


def _provider(raw, seen: set[str]) -> Provider:
    if not isinstance(raw, dict):
        raise ModelCatalogError("Each provider entry must be a table.")
    provider_id = _text(raw.get("id"), "provider id", pattern=_IDENTIFIER)
    if provider_id in seen:
        raise ModelCatalogError(f"Duplicate provider id '{provider_id}'.")
    api = raw.get("api")
    if api != SUPPORTED_API:
        raise ModelCatalogError(
            f"Provider '{provider_id}' must use api = \"{SUPPORTED_API}\"; "
            "no other provider protocol is supported."
        )
    api_key_env = raw.get("api_key_env")
    if api_key_env is not None:
        api_key_env = _text(api_key_env, "api_key_env", maximum=128, pattern=_ENV_NAME)
    models = raw.get("models")
    if not isinstance(models, list) or not models:
        raise ModelCatalogError(f"Provider '{provider_id}' must declare at least one model.")
    seen_models: set[str] = set()
    parsed_models = tuple(_model(item, provider_id, seen_models) for item in models)
    return Provider(
        id=provider_id,
        name=_text(raw.get("name", provider_id), "name"),
        api=api,
        base_url=_http_url(raw.get("base_url"), "base_url"),
        anthropic_base_url=(
            _http_url(raw["anthropic_base_url"], "anthropic_base_url")
            if raw.get("anthropic_base_url") is not None
            else None
        ),
        api_key_env=api_key_env,
        pi_compat=_compat(raw.get("pi_compat")),
        models=parsed_models,
    )


class ModelCatalog:
    def __init__(self, providers: tuple[Provider, ...]):
        self.providers = providers
        self._by_provider = {provider.id: provider for provider in providers}
        self._by_model = {
            (provider.id, model.id): model for provider in providers for model in provider.models
        }

    @classmethod
    def parse(cls, text: str) -> "ModelCatalog":
        try:
            data = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, UnicodeError) as exc:
            raise ModelCatalogError("The model configuration is invalid TOML.") from exc
        raw_providers = data.get("providers")
        if not isinstance(raw_providers, list) or not raw_providers:
            raise ModelCatalogError(
                "The model configuration must declare at least one [[providers]] entry."
            )
        seen: set[str] = set()
        providers = tuple(_provider(raw, seen) for raw in raw_providers)
        return cls(providers)

    def provider(self, provider_id: str) -> Provider:
        try:
            return self._by_provider[provider_id]
        except KeyError as exc:
            raise ModelCatalogError(
                f"Provider '{provider_id}' is not configured. Choose a configured model."
            ) from exc

    def model(self, provider_id: str, model_id: str) -> Model:
        self.provider(provider_id)
        try:
            return self._by_model[(provider_id, model_id)]
        except KeyError as exc:
            raise ModelCatalogError(
                f"Model '{model_id}' is not configured for provider '{provider_id}'. "
                "Choose a configured model."
            ) from exc

    def options(self, runtime: str | None = None) -> list[ModelOption]:
        if runtime is not None and runtime not in RUNTIMES:
            raise ModelCatalogError("Unknown agent runtime.")
        result = []
        for provider in self.providers:
            for model in provider.models:
                if runtime is not None and not model.supports(runtime):
                    continue
                result.append(
                    ModelOption(
                        provider=provider.id,
                        id=model.id,
                        name=model.name,
                        provider_name=provider.name,
                        context_window=model.context_window,
                        runtimes=model.runtimes,
                        credential_env=provider.api_key_env,
                        credential_ready=(
                            not provider.api_key_env or bool(os.environ.get(provider.api_key_env))
                        ),
                    )
                )
        return result

    def require(self, provider_id: str, model_id: str, runtime: str) -> ModelSelection:
        if runtime not in RUNTIMES:
            raise ModelCatalogError("Unknown agent runtime.")
        provider = self.provider(provider_id)
        model = self.model(provider_id, model_id)
        if not model.supports(runtime):
            raise ModelCatalogError(
                f"Model '{model_id}' is not available for the {RUNTIMES[runtime]} runtime. "
                "Choose another model or runtime."
            )
        env_name = provider.api_key_env
        return ModelSelection(
            provider=provider,
            model=model,
            api_key=os.environ.get(env_name) if env_name else None,
        )


def load_catalog(path: Path | None = None) -> ModelCatalog:
    source = Path(path) if path is not None else DEFAULT_CATALOG
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ModelCatalogError(
            f"The model configuration file could not be read: {source.name}."
        ) from exc
    return ModelCatalog.parse(text)
