from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
import json
import httpx

from peppa.config import ModelSettings
from peppa.models.tool_calls import (
    ToolCall,
    build_chat_request_payload,
    select_tool_call_adapter,
)


class ModelClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResponse:
    content: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    tool_calls: list[ToolCall]


@dataclass(frozen=True)
class ModelStreamEvent:
    event: str
    content: str = ""
    response: ModelResponse | None = None


class ModelClient:
    def __init__(self, timeout_seconds: float = 90.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def chat(
        self,
        *,
        model_settings: ModelSettings,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 1.0,
    ) -> ModelResponse:
        request_payload = self.build_request_payload(
            model_settings=model_settings,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
        )
        headers = {
            "Authorization": f"Bearer {model_settings.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                model_settings.chat_completions_url,
                headers=headers,
                json=request_payload,
            )

        if response.status_code >= 400:
            raise ModelClientError(
                f"Model API returned HTTP {response.status_code}: {response.text[:1000]}"
            )

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ModelClientError("Model API returned a non-JSON response.") from exc

        content = _extract_message_content(response_payload)
        tool_calls = select_tool_call_adapter(model_settings).parse_response_tool_calls(
            response_payload
        )
        return ModelResponse(
            content=content,
            request_payload=request_payload,
            response_payload=response_payload,
            tool_calls=tool_calls,
        )

    async def stream_chat(
        self,
        *,
        model_settings: ModelSettings,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 1.0,
    ) -> AsyncIterator[ModelStreamEvent]:
        request_payload = self.build_request_payload(
            model_settings=model_settings,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
        )
        request_payload["stream"] = True
        headers = {
            "Authorization": f"Bearer {model_settings.api_key}",
            "Content-Type": "application/json",
        }

        content_parts: list[str] = []
        stream_chunks: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            async with client.stream(
                "POST",
                model_settings.chat_completions_url,
                headers=headers,
                json=request_payload,
            ) as response:
                if response.status_code >= 400:
                    error_text = (await response.aread()).decode("utf-8", errors="replace")
                    raise ModelClientError(
                        f"Model API returned HTTP {response.status_code}: {error_text[:1000]}"
                    )

                async for line in response.aiter_lines():
                    data = _stream_data_from_line(line)
                    if data is None:
                        continue
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ModelClientError("Model API returned invalid stream JSON.") from exc
                    if not isinstance(chunk, dict):
                        continue

                    stream_chunks.append(chunk)
                    content = _extract_stream_delta_content(chunk)
                    if content:
                        content_parts.append(content)
                        yield ModelStreamEvent(event="delta", content=content)

        full_content = "".join(content_parts)
        response_payload = _build_stream_response_payload(
            content=full_content,
            chunks=stream_chunks,
        )
        yield ModelStreamEvent(
            event="done",
            response=ModelResponse(
                content=full_content,
                request_payload=request_payload,
                response_payload=response_payload,
                tool_calls=[],
            ),
        )

    def build_request_payload(
        self,
        *,
        model_settings: ModelSettings | None = None,
        model: str | None = None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 1.0,
    ) -> dict[str, Any]:
        return build_chat_request_payload(
            model_settings=model_settings,
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
        )


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelClientError("Model API response did not include choices.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ModelClientError("Model API response choice has an unexpected format.")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ModelClientError("Model API response did not include message content.")

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        ).strip()

    return ""


def _stream_data_from_line(line: str) -> str | None:
    clean_line = line.strip()
    if not clean_line or clean_line.startswith(":"):
        return None
    if not clean_line.startswith("data:"):
        return None
    return clean_line.removeprefix("data:").strip()


def _extract_stream_delta_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    delta = first_choice.get("delta")
    if isinstance(delta, dict):
        return _content_to_text(delta.get("content"))

    message = first_choice.get("message")
    if isinstance(message, dict):
        return _content_to_text(message.get("content"))

    return ""


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    return ""


def _build_stream_response_payload(
    *,
    content: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "stream": True,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": _stream_finish_reason(chunks),
            }
        ],
        "chunks": chunks,
    }


def _stream_finish_reason(chunks: list[dict[str, Any]]) -> str | None:
    for chunk in reversed(chunks):
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            continue
        finish_reason = first_choice.get("finish_reason")
        if isinstance(finish_reason, str):
            return finish_reason
    return None
