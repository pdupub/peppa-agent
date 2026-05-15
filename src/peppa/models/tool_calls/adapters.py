from __future__ import annotations

from copy import deepcopy
from typing import Any
import json

from peppa.config import ModelSettings
from peppa.models.tool_calls.types import ToolCall


class ToolCallAdapter:
    name = "openai"

    def build_request_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 1.0,
    ) -> dict[str, Any]:
        prepared_tools = self.prepare_tools(tools)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if prepared_tools:
            payload["tools"] = prepared_tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        self.apply_provider_options(
            payload=payload,
            model=model,
            has_tools=bool(prepared_tools),
        )
        return payload

    def prepare_tools(
        self,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if tools is None:
            return None
        return deepcopy(tools)

    def apply_provider_options(
        self, *, payload: dict[str, Any], model: str, has_tools: bool
    ) -> None:
        return None

    def parse_response_tool_calls(self, payload: dict[str, Any]) -> list[ToolCall]:
        return _parse_openai_style_tool_calls(payload)


class OpenAICompatibleToolAdapter(ToolCallAdapter):
    name = "openai"


class DeepSeekToolAdapter(OpenAICompatibleToolAdapter):
    name = "deepseek"


class QwenToolAdapter(OpenAICompatibleToolAdapter):
    name = "qwen"

    def apply_provider_options(
        self, *, payload: dict[str, Any], model: str, has_tools: bool
    ) -> None:
        if has_tools:
            payload["enable_thinking"] = False


class KimiToolAdapter(OpenAICompatibleToolAdapter):
    name = "kimi"

    def prepare_tools(
        self,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        prepared_tools = super().prepare_tools(tools)
        if not prepared_tools:
            return prepared_tools

        for tool in prepared_tools:
            function = _as_record(tool.get("function"))
            if function and "strict" not in function:
                function["strict"] = False
        return prepared_tools

    def apply_provider_options(
        self, *, payload: dict[str, Any], model: str, has_tools: bool
    ) -> None:
        if has_tools and _is_kimi_thinking_model(model):
            payload["thinking"] = {"type": "disabled"}


ADAPTERS: dict[str, ToolCallAdapter] = {
    "openai": OpenAICompatibleToolAdapter(),
    "openai-compatible": OpenAICompatibleToolAdapter(),
    "compatible": OpenAICompatibleToolAdapter(),
    "deepseek": DeepSeekToolAdapter(),
    "qwen": QwenToolAdapter(),
    "dashscope": QwenToolAdapter(),
    "kimi": KimiToolAdapter(),
    "moonshot": KimiToolAdapter(),
}


def build_chat_request_payload(
    *,
    model_settings: ModelSettings | None,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    temperature: float = 1.0,
) -> dict[str, Any]:
    if model_settings is None and model is None:
        raise ValueError("Either model_settings or model must be provided.")

    adapter = select_tool_call_adapter(model_settings)
    model_name = model_settings.model if model_settings is not None else model
    if model_name is None:
        raise ValueError("Model name is missing.")

    return adapter.build_request_payload(
        model=model_name,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
    )


def select_tool_call_adapter(model_settings: ModelSettings | None) -> ToolCallAdapter:
    if model_settings is None:
        return ADAPTERS["openai"]

    adapter_name = (model_settings.tool_adapter or "auto").strip().lower()
    if adapter_name == "auto":
        adapter_name = _detect_adapter_name(model_settings)

    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        supported = ", ".join(sorted(ADAPTERS))
        raise ValueError(
            f"Unsupported tool_adapter {model_settings.tool_adapter!r}. "
            f"Supported values: auto, {supported}."
        )
    return adapter


def _detect_adapter_name(model_settings: ModelSettings) -> str:
    base_url = model_settings.base_url.lower()
    model = model_settings.model.lower()
    if "deepseek" in base_url or model.startswith("deepseek"):
        return "deepseek"
    if "dashscope" in base_url or model.startswith("qwen"):
        return "qwen"
    if "moonshot" in base_url or model.startswith("kimi"):
        return "kimi"
    return "openai"


def _parse_openai_style_tool_calls(payload: dict[str, Any]) -> list[ToolCall]:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return []

    tool_calls: list[ToolCall] = []
    for choice in choices:
        choice_record = _as_record(choice)
        message = _as_record(choice_record.get("message"))
        for tool_call in _as_list(message.get("tool_calls")):
            parsed = _parse_openai_style_tool_call(tool_call)
            if parsed is not None:
                tool_calls.append(parsed)
    return tool_calls


def _parse_openai_style_tool_call(tool_call: Any) -> ToolCall | None:
    tool_record = _as_record(tool_call)
    function = _as_record(tool_record.get("function"))
    name = _clean_text(function.get("name") or tool_record.get("name"))
    if not name:
        return None

    raw_arguments = function.get("arguments")
    if raw_arguments is None:
        raw_arguments = tool_record.get("arguments")

    parsed_arguments: dict[str, Any] | None = None
    parse_error: str | None = None
    try:
        parsed_arguments = _parse_arguments(raw_arguments)
    except ValueError as exc:
        parse_error = str(exc)

    return ToolCall(
        id=_clean_text(tool_record.get("id")) or None,
        name=name,
        arguments_raw=raw_arguments,
        arguments=parsed_arguments,
        parse_error=parse_error,
    )


def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        if not raw_arguments.strip():
            raise ValueError("Tool call arguments are empty.")
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Tool call arguments are not valid JSON: {exc}") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Tool call arguments must be a JSON object.")


def _is_kimi_thinking_model(model: str) -> bool:
    normalized = model.lower().replace("_", "-")
    return normalized.startswith("kimi-k2.6") or normalized.startswith("kimi-k2-6")


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
