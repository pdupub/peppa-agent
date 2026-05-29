from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from peppa.config import ModelSettings, PeppaSettings
from peppa.identity import ConversationIdentityStore
from peppa.memory import MemoryRecallResult, MemoryRecallStore, Storage, TraceRecord
from peppa.models import ModelClient, ModelResponse
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


@dataclass(frozen=True)
class ChatStreamEvent:
    event: str
    data: dict[str, Any]
    result: ChatResult | None = None


@dataclass(frozen=True)
class PreparedChat:
    model_settings: ModelSettings
    conversation_id: str
    clean_message: str
    prompt_messages: list[dict[str, Any]]
    history_message_count: int
    requested_prompt_history_messages: int
    memory_recall: MemoryRecallResult


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
        prepared = self._prepare_chat(
            user_message=user_message,
            requested_model=requested_model,
            conversation_id=conversation_id,
            prompt_history_messages=prompt_history_messages,
            channel=channel,
            channel_instance=channel_instance,
        )
        request_payload = self.model_client.build_request_payload(
            model_settings=prepared.model_settings,
            messages=prepared.prompt_messages,
            temperature=temperature,
        )
        request_payload["_peppa"] = _chat_request_meta(prepared)
        response_payload: dict[str, Any] | None = None
        assistant_message: str | None = None
        error: str | None = None
        started_at = perf_counter()

        try:
            response = await self.model_client.chat(
                model_settings=prepared.model_settings,
                messages=prepared.prompt_messages,
                temperature=temperature,
            )
            request_payload = response.request_payload
            request_payload["_peppa"] = _chat_request_meta(prepared)
            response_payload = response.response_payload
            assistant_message = response.content
            self.storage.add_message(
                conversation_id=prepared.conversation_id,
                role="assistant",
                content=assistant_message,
                model=prepared.model_settings.model,
            )
        except Exception as exc:
            error = str(exc)

        duration_ms = int((perf_counter() - started_at) * 1000)
        trace = self.storage.create_trace(
            conversation_id=prepared.conversation_id,
            model=prepared.model_settings.model,
            user_message=prepared.clean_message,
            assistant_message=assistant_message,
            prompt_messages=prepared.prompt_messages,
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
        )
        return ChatResult(conversation_id=prepared.conversation_id, trace=trace)

    async def stream_chat(
        self,
        *,
        user_message: str,
        requested_model: str | None = None,
        conversation_id: str | None = None,
        temperature: float = 1.0,
        prompt_history_messages: int = MAX_PROMPT_HISTORY_MESSAGES,
        channel: str = "cli",
        channel_instance: str = "default",
    ) -> AsyncIterator[ChatStreamEvent]:
        prepared = self._prepare_chat(
            user_message=user_message,
            requested_model=requested_model,
            conversation_id=conversation_id,
            prompt_history_messages=prompt_history_messages,
            channel=channel,
            channel_instance=channel_instance,
        )
        yield ChatStreamEvent(
            event="meta",
            data={"conversation_id": prepared.conversation_id},
        )

        request_payload = self.model_client.build_request_payload(
            model_settings=prepared.model_settings,
            messages=prepared.prompt_messages,
            temperature=temperature,
        )
        request_payload["stream"] = True
        request_payload["_peppa"] = _chat_request_meta(prepared)
        response_payload: dict[str, Any] | None = None
        response: ModelResponse | None = None
        content_parts: list[str] = []
        error: str | None = None
        started_at = perf_counter()

        try:
            async for model_event in self.model_client.stream_chat(
                model_settings=prepared.model_settings,
                messages=prepared.prompt_messages,
                temperature=temperature,
            ):
                if model_event.event == "delta":
                    content_parts.append(model_event.content)
                    yield ChatStreamEvent(
                        event="delta",
                        data={"content": model_event.content},
                    )
                elif model_event.event == "done" and model_event.response is not None:
                    response = model_event.response
        except Exception as exc:
            error = str(exc)

        assistant_message = response.content if response is not None else "".join(content_parts)
        if response is not None:
            request_payload = response.request_payload
            request_payload["_peppa"] = _chat_request_meta(prepared)
            response_payload = response.response_payload

        if assistant_message:
            self.storage.add_message(
                conversation_id=prepared.conversation_id,
                role="assistant",
                content=assistant_message,
                model=prepared.model_settings.model,
            )

        duration_ms = int((perf_counter() - started_at) * 1000)
        trace = self.storage.create_trace(
            conversation_id=prepared.conversation_id,
            model=prepared.model_settings.model,
            user_message=prepared.clean_message,
            assistant_message=assistant_message if assistant_message else None,
            prompt_messages=prepared.prompt_messages,
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
        )
        result = ChatResult(conversation_id=prepared.conversation_id, trace=trace)
        if error:
            yield ChatStreamEvent(
                event="error",
                data={
                    "message": error,
                    "conversation_id": prepared.conversation_id,
                    "trace": trace.public_dict(),
                },
                result=result,
            )
            return

        yield ChatStreamEvent(
            event="done",
            data={
                "conversation_id": prepared.conversation_id,
                "trace": trace.public_dict(),
            },
            result=result,
        )

    def _prepare_chat(
        self,
        *,
        user_message: str,
        requested_model: str | None,
        conversation_id: str | None,
        prompt_history_messages: int,
        channel: str,
        channel_instance: str,
    ) -> PreparedChat:
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
        return PreparedChat(
            model_settings=model_settings,
            conversation_id=conversation_id,
            clean_message=clean_message,
            prompt_messages=prompt_messages,
            history_message_count=len(history_messages),
            requested_prompt_history_messages=prompt_history_messages,
            memory_recall=memory_recall,
        )


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


def _chat_request_meta(prepared: PreparedChat) -> dict[str, Any]:
    return {
        "kind": "chat",
        "prompt_history_messages": prepared.history_message_count,
        "requested_prompt_history_messages": prepared.requested_prompt_history_messages,
        "memory_recall": prepared.memory_recall.public_dict(),
    }
