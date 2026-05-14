from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import httpx

from peppa.config import ModelSettings


class ModelClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResponse:
    content: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]


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
            model=model_settings.model,
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
        return ModelResponse(
            content=content,
            request_payload=request_payload,
            response_payload=response_payload,
        )

    def build_request_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 1.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload


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
