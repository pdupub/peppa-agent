from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Callable

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

    def parse_response_tool_calls(self, payload: dict[str, Any]) -> list[ToolCall]:
        return _parse_openai_style_tool_calls(
            payload,
            parse_arguments=_parse_qwen_arguments,
        )


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


def _parse_openai_style_tool_calls(
    payload: dict[str, Any],
    parse_arguments: Callable[[Any], dict[str, Any]] | None = None,
) -> list[ToolCall]:
    argument_parser = parse_arguments or _parse_arguments
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return []

    tool_calls: list[ToolCall] = []
    for choice in choices:
        choice_record = _as_record(choice)
        message = _as_record(choice_record.get("message"))
        for tool_call in _as_list(message.get("tool_calls")):
            parsed = _parse_openai_style_tool_call(
                tool_call,
                parse_arguments=argument_parser,
            )
            if parsed is not None:
                tool_calls.append(parsed)
    return tool_calls


def _parse_openai_style_tool_call(
    tool_call: Any,
    parse_arguments: Callable[[Any], dict[str, Any]],
) -> ToolCall | None:
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
        parsed_arguments = parse_arguments(raw_arguments)
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


def _parse_qwen_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return _decode_nested_json_strings(raw_arguments)
    if not isinstance(raw_arguments, str):
        raise ValueError("Tool call arguments must be a JSON object.")

    if not raw_arguments.strip():
        raise ValueError("Tool call arguments are empty.")

    last_error: json.JSONDecodeError | None = None
    for candidate in _qwen_argument_candidates(raw_arguments):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return _decode_nested_json_strings(parsed)

    if last_error is not None:
        raise ValueError(
            f"Tool call arguments are not valid JSON after qwen repair: {last_error}"
        ) from last_error
    raise ValueError("Tool call arguments must be a JSON object.")


def _qwen_argument_candidates(raw_arguments: str) -> list[str]:
    original = raw_arguments.strip()
    repaired = _fill_missing_json_values(_collapse_extra_quote_escapes(original))
    if repaired == original:
        return [original]
    return [original, repaired]


def _collapse_extra_quote_escapes(value: str) -> str:
    return re.sub(r'\\{2,}(?=")', r"\\", value)


def _fill_missing_json_values(value: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    index = 0

    while index < len(value):
        char = value[index]
        result.append(char)

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            index += 1
            continue

        if char == ":":
            lookahead = index + 1
            while lookahead < len(value) and value[lookahead].isspace():
                result.append(value[lookahead])
                lookahead += 1
            if lookahead < len(value) and value[lookahead] in ",}":
                result.append("{}")
            index = lookahead
            continue

        index += 1

    return "".join(result)


def _decode_nested_json_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _decode_nested_json_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_nested_json_strings(item) for item in value]
    if isinstance(value, str):
        parsed = _parse_nested_json_string(value)
        if parsed is not None:
            return _decode_nested_json_strings(parsed)
    return value


def _parse_nested_json_string(value: str) -> Any | None:
    current = value.strip()
    if not current.startswith(("[", "{")):
        return None

    for _ in range(3):
        try:
            return json.loads(current)
        except json.JSONDecodeError:
            decoded = _decode_json_string_layer(current)
            if decoded == current:
                current = _remove_quote_escapes(current)
            else:
                current = decoded

    try:
        return json.loads(current)
    except json.JSONDecodeError:
        return None


def _decode_json_string_layer(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, str) else value


def _remove_quote_escapes(value: str) -> str:
    return re.sub(r'\\+(?=")', "", value)


def _is_kimi_thinking_model(model: str) -> bool:
    normalized = model.lower().replace("_", "-")
    return normalized.startswith("kimi-k2.6") or normalized.startswith("kimi-k2-6")


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
