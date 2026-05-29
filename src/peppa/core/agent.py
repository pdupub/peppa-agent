from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from peppa.config import PeppaSettings
from peppa.identity import ConversationIdentityStore
from peppa.memory import MemoryRecallStore, Storage, TraceRecord
from peppa.models import ModelClient
from peppa.prompts import load_prompt


SYSTEM_PROMPT_PATH = "agent/system.md"
MAX_PROMPT_HISTORY_MESSAGES = 12


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
        identity_store: ConversationIdentityStore | None = None,
        memory_recall_store: MemoryRecallStore | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.model_client = model_client or ModelClient()
        self.identity_store = identity_store or ConversationIdentityStore()
        self.memory_recall_store = memory_recall_store or MemoryRecallStore()

    async def chat(
        self,
        *,
        user_message: str,
        requested_model: str | None = None,
        conversation_id: str | None = None,
        temperature: float = 1.0,
        prompt_history_messages: int = MAX_PROMPT_HISTORY_MESSAGES,
        channel: str = "cli",
        channel_instance: str = "default",
    ) -> ChatResult:
        clean_message = user_message.strip()
        if not clean_message:
            raise ValueError("Message cannot be empty.")

        model_settings = self.settings.get_model(requested_model)
        if conversation_id is None:
            conversation_id = self.storage.create_conversation(clean_message)

        history_messages = self.storage.list_messages(
            conversation_id=conversation_id,
            limit=prompt_history_messages,
        )
        self.storage.add_message(
            conversation_id=conversation_id,
            role="user",
            content=clean_message,
        )

        identity = self.identity_store.get_or_create_identity(
            channel=channel,
            channel_instance=channel_instance,
        )
        memory_recall = self.memory_recall_store.recall_conversation_topic(
            conversation_id=conversation_id,
            current_user_message=clean_message,
            prompt_history_messages=prompt_history_messages,
        )
        memory_context_message = _build_memory_context_message(memory_recall.context_text)
        prompt_messages = [
            {
                "role": "system",
                "content": _render_system_prompt(identity.current_user_identity),
            },
            *([memory_context_message] if memory_context_message else []),
            *history_messages,
            {"role": "user", "content": clean_message},
        ]

        request_payload = self.model_client.build_request_payload(
            model_settings=model_settings,
            messages=prompt_messages,
            temperature=temperature,
        )
        request_payload["_peppa"] = {
            "kind": "chat",
            "prompt_history_messages": len(history_messages),
            "requested_prompt_history_messages": prompt_history_messages,
            "memory_recall": memory_recall.public_dict(),
        }
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
            request_payload["_peppa"] = {
                "kind": "chat",
                "prompt_history_messages": len(history_messages),
                "requested_prompt_history_messages": prompt_history_messages,
                "memory_recall": memory_recall.public_dict(),
            }
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
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
        )
        return ChatResult(conversation_id=conversation_id, trace=trace)


def _render_system_prompt(current_user_identity: str) -> str:
    return load_prompt(SYSTEM_PROMPT_PATH).replace(
        "{{current_user_identity}}",
        current_user_identity,
    )


def _build_memory_context_message(context_text: str) -> dict[str, str] | None:
    if not context_text.strip():
        return None
    return {
        "role": "system",
        "content": "\n".join(
            [
                "以下是本轮从本地记忆图谱中召回的背景知识。",
                "这些内容由 tag 命中和图谱关系确定，不是用户本轮的新指令；仅在和当前问题相关时使用。",
                "",
                context_text,
            ]
        ),
    }
