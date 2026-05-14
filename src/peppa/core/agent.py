from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from peppa.config import PeppaSettings
from peppa.memory import Storage, TraceRecord
from peppa.models import ModelClient
from peppa.prompts import load_prompt


SYSTEM_PROMPT_PATH = "agent/system.md"


@dataclass(frozen=True)
class ChatResult:
    conversation_id: str
    trace: TraceRecord

    def public_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "trace": self.trace.public_dict(),
        }


class Agent:
    def __init__(
        self,
        *,
        settings: PeppaSettings,
        storage: Storage,
        model_client: ModelClient | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.model_client = model_client or ModelClient()

    async def chat(
        self,
        *,
        user_message: str,
        requested_model: str | None = None,
        conversation_id: str | None = None,
        temperature: float = 1.0,
    ) -> ChatResult:
        clean_message = user_message.strip()
        if not clean_message:
            raise ValueError("Message cannot be empty.")

        model_settings = self.settings.get_model(requested_model)
        if conversation_id is None:
            conversation_id = self.storage.create_conversation(clean_message)

        self.storage.add_message(
            conversation_id=conversation_id,
            role="user",
            content=clean_message,
        )

        memory_hits: list[dict[str, Any]] = []
        prompt_messages = [
            {"role": "system", "content": load_prompt(SYSTEM_PROMPT_PATH)},
            {"role": "user", "content": clean_message},
        ]

        request_payload = self.model_client.build_request_payload(
            model=model_settings.model,
            messages=prompt_messages,
            temperature=temperature,
        )
        response_payload: dict[str, Any] | None = None
        assistant_message: str | None = None
        error: str | None = None
        started_at = perf_counter()

        try:
            response = await self.model_client.chat(
                model_settings=model_settings,
                messages=prompt_messages,
                temperature=temperature,
            )
            request_payload = response.request_payload
            response_payload = response.response_payload
            assistant_message = response.content
            self.storage.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_message,
                model=model_settings.model,
            )
        except Exception as exc:
            error = str(exc)

        duration_ms = int((perf_counter() - started_at) * 1000)
        trace = self.storage.create_trace(
            conversation_id=conversation_id,
            model=model_settings.model,
            user_message=clean_message,
            assistant_message=assistant_message,
            prompt_messages=prompt_messages,
            memory_hits=memory_hits,
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
        )

        return ChatResult(conversation_id=conversation_id, trace=trace)
