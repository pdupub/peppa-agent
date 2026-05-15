from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib

from peppa.paths import CONFIG_PATH


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSettings:
    model: str
    base_url: str
    api_key: str
    tool_adapter: str = "auto"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "has_api_key": bool(self.api_key),
            "tool_adapter": self.tool_adapter,
        }


@dataclass(frozen=True)
class PeppaSettings:
    default_model: str
    models: tuple[ModelSettings, ...]

    def get_model(self, requested_model: str | None = None) -> ModelSettings:
        model_name = requested_model or self.default_model
        for model in self.models:
            if model.model == model_name:
                return model
        raise ConfigError(f"Unknown model: {model_name}")

    def public_dict(self) -> dict[str, Any]:
        return {
            "default_model": self.default_model,
            "models": [model.public_dict() for model in self.models],
        }


def load_settings(path: Path = CONFIG_PATH) -> PeppaSettings:
    if not path.exists():
        raise ConfigError(
            f"Missing config file: {path}. Copy config.example.toml to config.toml first."
        )

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ConfigError("config.toml must define at least one [[models]] entry.")

    models: list[ModelSettings] = []
    seen: set[str] = set()
    for index, raw_model in enumerate(raw_models, start=1):
        if not isinstance(raw_model, dict):
            raise ConfigError(f"Model entry #{index} must be a table.")

        model_name = _required_string(raw_model, "model", index)
        base_url = _required_string(raw_model, "base_url", index)
        api_key = _required_string(raw_model, "api_key", index)
        tool_adapter = _optional_string(raw_model, "tool_adapter", "auto")

        if model_name in seen:
            raise ConfigError(f"Duplicate model in config.toml: {model_name}")
        seen.add(model_name)
        models.append(
            ModelSettings(
                model=model_name,
                base_url=base_url,
                api_key=api_key,
                tool_adapter=tool_adapter,
            )
        )

    app_config = data.get("app", {})
    if app_config is None:
        app_config = {}
    if not isinstance(app_config, dict):
        raise ConfigError("[app] must be a table.")

    default_model = app_config.get("default_model") or models[0].model
    if not isinstance(default_model, str):
        raise ConfigError("[app].default_model must be a string.")
    if default_model not in seen:
        raise ConfigError(f"[app].default_model is not defined in [[models]]: {default_model}")

    return PeppaSettings(default_model=default_model, models=tuple(models))


def _required_string(raw_model: dict[str, Any], key: str, index: int) -> str:
    value = raw_model.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Model entry #{index} must define a non-empty {key!r}.")
    return value.strip()


def _optional_string(raw_model: dict[str, Any], key: str, default: str) -> str:
    value = raw_model.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip()
