from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from peppa import __version__
from peppa.config import ConfigError, ModelSettings, load_settings
from peppa.core import Agent, MAX_PROMPT_HISTORY_MESSAGES
from peppa.identity import (
    IDENTITY_TOOL_NAME,
    ConversationIdentityStore,
    identity_tool_choice,
    identity_update_tools,
)
from peppa.memory import (
    AUTO_MEMORY_EXTRACTION_TURN_THRESHOLD,
    MEMORY_TOOL_NAME,
    MemoryAutoExtractionState,
    MemoryAutoExtractionStore,
    MemoryGraphStore,
    MemoryRecallStore,
    Storage,
    TraceRecord,
    memory_graph_update_tools,
    memory_tool_choice,
)
from peppa.models import ModelClient
from peppa.paths import DATABASE_PATH, ROOT_DIR, WEB_DIST_DIR, ensure_runtime_dirs
from peppa.prompts import load_skill
from peppa.topics import TOPIC_BOUNDARY_TOOL_NAME


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None
    conversation_id: str | None = None
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    prompt_history_messages: int = Field(
        default=MAX_PROMPT_HISTORY_MESSAGES,
        ge=0,
        le=50,
    )


class ChatResponse(BaseModel):
    conversation_id: str
    trace: dict[str, Any]


class MemoryRecallRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    prompt_history_messages: int = Field(
        default=MAX_PROMPT_HISTORY_MESSAGES,
        ge=0,
        le=50,
    )


class MemoryRecallResponse(BaseModel):
    message: str
    memory_recall: dict[str, Any]


class MemoryExtractionRequest(BaseModel):
    trace_ids: list[str] = Field(min_length=1, max_length=20)
    model: str | None = None
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class MemoryExtractionResponse(BaseModel):
    trace: dict[str, Any]


class MemorySummaryUpdateRequest(BaseModel):
    summary: str = ""


class MemoryTagUpdateRequest(BaseModel):
    name: str | None = None
    kind: str | None = None


class MemoryMergeRequest(BaseModel):
    target_id: str = Field(min_length=1)


class IdentityExtractionRequest(BaseModel):
    trace_ids: list[str] = Field(min_length=1, max_length=20)
    model: str | None = None
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class IdentityExtractionResponse(BaseModel):
    trace: dict[str, Any]
    identity: dict[str, Any]


@dataclass(frozen=True)
class MemoryExtractionRunResult:
    trace: TraceRecord
    source_traces: list[TraceRecord]
    success: bool


WEB_IDENTITY_CHANNEL = "web"
WEB_IDENTITY_INSTANCE = "default"


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    storage = Storage()
    storage.initialize()
    memory_graph_store = MemoryGraphStore()
    memory_recall_store = MemoryRecallStore()
    memory_auto_extraction_store = MemoryAutoExtractionStore()
    memory_auto_extraction_store.initialize()
    identity_store = ConversationIdentityStore()
    identity_store.initialize()
    auto_memory_extraction_task: asyncio.Task[None] | None = None

    app = FastAPI(title="Peppa", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "root": str(ROOT_DIR),
            "database": str(DATABASE_PATH),
        }

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        try:
            config_payload = load_settings().public_dict()
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        config_payload["prompt_history_messages_default"] = MAX_PROMPT_HISTORY_MESSAGES
        return config_payload

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        nonlocal auto_memory_extraction_task
        try:
            settings = load_settings()
            model_settings = settings.get_model(request.model)
            agent = Agent(
                settings=settings,
                storage=storage,
                identity_store=identity_store,
                memory_recall_store=memory_recall_store,
            )
            result = await agent.chat(
                user_message=request.message,
                requested_model=request.model,
                conversation_id=request.conversation_id,
                temperature=request.temperature,
                prompt_history_messages=request.prompt_history_messages,
                channel=WEB_IDENTITY_CHANNEL,
                channel_instance=WEB_IDENTITY_INSTANCE,
            )
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if result.trace.error is None and (
            auto_memory_extraction_task is None or auto_memory_extraction_task.done()
        ):
            auto_memory_extraction_task = asyncio.create_task(
                _run_auto_memory_extraction(
                    storage=storage,
                    memory_graph_store=memory_graph_store,
                    identity_store=identity_store,
                    memory_auto_extraction_store=memory_auto_extraction_store,
                    current_trace_id=result.trace.id,
                    model_settings=model_settings,
                    temperature=request.temperature,
                )
            )
            auto_memory_extraction_task.add_done_callback(_consume_background_task_result)

        state = memory_auto_extraction_store.get_state()
        return ChatResponse(
            conversation_id=result.conversation_id,
            trace=_trace_payload_with_auto_memory_marker(result.trace, state),
        )

    @app.post("/api/memory/recall", response_model=MemoryRecallResponse)
    async def recall_memory(request: MemoryRecallRequest) -> MemoryRecallResponse:
        clean_message = request.message.strip()
        if not clean_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")
        if request.conversation_id:
            result = memory_recall_store.recall_conversation_topic(
                conversation_id=request.conversation_id,
                current_user_message=clean_message,
                prompt_history_messages=request.prompt_history_messages,
            )
        else:
            result = memory_recall_store.recall(clean_message)
        return MemoryRecallResponse(
            message=clean_message,
            memory_recall=result.public_dict(),
        )

    @app.get("/api/traces")
    async def traces(limit: int = 25) -> dict[str, Any]:
        state = memory_auto_extraction_store.get_state()
        return {
            "traces": [
                _trace_payload_with_auto_memory_marker(trace, state)
                for trace in storage.list_traces(limit=limit)
            ],
        }

    @app.get("/api/traces/{trace_id}")
    async def trace(trace_id: str) -> dict[str, Any]:
        record = storage.get_trace(trace_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Trace not found.")
        return _trace_payload_with_auto_memory_marker(
            record,
            memory_auto_extraction_store.get_state(),
        )

    @app.get("/api/memory/graph")
    async def memory_graph() -> dict[str, Any]:
        return memory_graph_store.get_memory_graph()

    @app.delete("/api/memory/graph/nodes/{node_id}")
    async def delete_memory_node(node_id: str) -> dict[str, Any]:
        if not memory_graph_store.delete_node(node_id):
            raise HTTPException(status_code=404, detail="Memory node not found.")
        return memory_graph_store.get_memory_graph()

    @app.patch("/api/memory/graph/nodes/{node_id}/summary")
    async def update_memory_node_summary(
        node_id: str,
        request: MemorySummaryUpdateRequest,
    ) -> dict[str, Any]:
        if not memory_graph_store.update_node_summary(node_id, request.summary):
            raise HTTPException(status_code=404, detail="Memory node not found.")
        return memory_graph_store.get_memory_graph()

    @app.post("/api/memory/graph/nodes/{node_id}/merge")
    async def merge_memory_node(node_id: str, request: MemoryMergeRequest) -> dict[str, Any]:
        try:
            merged = memory_graph_store.merge_nodes(node_id, request.target_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not merged:
            raise HTTPException(status_code=404, detail="Memory node not found.")
        return memory_graph_store.get_memory_graph()

    @app.delete("/api/memory/graph/edges/{edge_id}")
    async def delete_memory_edge(edge_id: str) -> dict[str, Any]:
        if not memory_graph_store.delete_edge(edge_id):
            raise HTTPException(status_code=404, detail="Memory edge not found.")
        return memory_graph_store.get_memory_graph()

    @app.patch("/api/memory/graph/edges/{edge_id}/summary")
    async def update_memory_edge_summary(
        edge_id: str,
        request: MemorySummaryUpdateRequest,
    ) -> dict[str, Any]:
        if not memory_graph_store.update_edge_summary(edge_id, request.summary):
            raise HTTPException(status_code=404, detail="Memory edge not found.")
        return memory_graph_store.get_memory_graph()

    @app.post("/api/memory/graph/edges/{edge_id}/merge")
    async def merge_memory_edge(edge_id: str, request: MemoryMergeRequest) -> dict[str, Any]:
        try:
            merged = memory_graph_store.merge_edges(edge_id, request.target_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not merged:
            raise HTTPException(status_code=404, detail="Memory edge not found.")
        return memory_graph_store.get_memory_graph()

    @app.patch("/api/memory/graph/tags/{tag_id}")
    async def update_memory_tag(tag_id: str, request: MemoryTagUpdateRequest) -> dict[str, Any]:
        try:
            updated = memory_graph_store.update_tag(
                tag_id,
                name=request.name,
                kind=request.kind,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Memory tag not found.")
        return memory_graph_store.get_memory_graph()

    @app.post("/api/memory/graph/tags/{tag_id}/merge")
    async def merge_memory_tag(tag_id: str, request: MemoryMergeRequest) -> dict[str, Any]:
        try:
            merged = memory_graph_store.merge_tags(tag_id, request.target_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not merged:
            raise HTTPException(status_code=404, detail="Memory tag not found.")
        return memory_graph_store.get_memory_graph()

    @app.get("/api/identity/context")
    async def identity_context() -> dict[str, Any]:
        identity = identity_store.get_or_create_identity(
            channel=WEB_IDENTITY_CHANNEL,
            channel_instance=WEB_IDENTITY_INSTANCE,
        )
        return {
            "identity": identity.public_dict(),
            "candidates": [
                candidate.public_dict() for candidate in identity_store.list_person_candidates()
            ],
        }

    @app.post("/api/identity/extract", response_model=IdentityExtractionResponse)
    async def extract_identity(request: IdentityExtractionRequest) -> IdentityExtractionResponse:
        try:
            settings = load_settings()
            model_settings = settings.get_model(request.model)
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        candidates = identity_store.list_person_candidates()
        if not candidates:
            raise HTTPException(
                status_code=400,
                detail="No person memory nodes are available for identity binding.",
            )

        selected_traces = []
        for trace_id in request.trace_ids:
            record = storage.get_trace(trace_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
            if _is_tool_call_trace(record.public_dict()):
                raise HTTPException(
                    status_code=400,
                    detail=f"Tool call traces cannot be used as identity input: {trace_id}",
                )
            selected_traces.append(record)

        selected_traces.sort(key=lambda item: item.created_at)
        current_identity = identity_store.get_or_create_identity(
            channel=WEB_IDENTITY_CHANNEL,
            channel_instance=WEB_IDENTITY_INSTANCE,
        )
        prompt_messages = _build_identity_extraction_messages(
            source_traces=[trace.public_dict() for trace in selected_traces],
            current_identity=current_identity.public_dict(),
            candidates=[candidate.public_dict() for candidate in candidates],
        )
        tools = identity_update_tools()
        tool_choice = identity_tool_choice()
        model_client = ModelClient()
        request_payload = model_client.build_request_payload(
            model_settings=model_settings,
            messages=prompt_messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=request.temperature,
        )
        request_payload["_peppa"] = {
            "kind": "identity_update",
            "source_trace_ids": request.trace_ids,
            "source_trace_order": [trace.id for trace in selected_traces],
            "channel": WEB_IDENTITY_CHANNEL,
            "channel_instance": WEB_IDENTITY_INSTANCE,
        }

        response_payload: dict[str, Any] | None = None
        assistant_message: str | None = None
        error: str | None = None
        started_at = perf_counter()
        try:
            response = await model_client.chat(
                model_settings=model_settings,
                messages=prompt_messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=request.temperature,
            )
            response_payload = response.response_payload
            assistant_message = response.content
            tool_errors = _apply_identity_tool_calls(
                identity_store=identity_store,
                tool_calls=response.tool_calls,
            )
            if tool_errors:
                error = "; ".join(tool_errors)
        except Exception as exc:
            error = str(exc)

        conversation_id = storage.create_conversation("Identity update")
        duration_ms = int((perf_counter() - started_at) * 1000)
        trace = storage.create_trace(
            conversation_id=conversation_id,
            model=model_settings.model,
            user_message=f"Identity update from {len(selected_traces)} trace(s)",
            assistant_message=assistant_message,
            prompt_messages=prompt_messages,
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
        )
        identity = identity_store.get_or_create_identity(
            channel=WEB_IDENTITY_CHANNEL,
            channel_instance=WEB_IDENTITY_INSTANCE,
        )

        return IdentityExtractionResponse(
            trace=trace.public_dict(),
            identity=identity.public_dict(),
        )

    @app.post("/api/memory/extract", response_model=MemoryExtractionResponse)
    async def extract_memory(request: MemoryExtractionRequest) -> MemoryExtractionResponse:
        try:
            settings = load_settings()
            model_settings = settings.get_model(request.model)
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        result = await _run_memory_extraction(
            storage=storage,
            memory_graph_store=memory_graph_store,
            identity_store=identity_store,
            source_traces=_load_memory_source_traces(storage, request.trace_ids),
            model_settings=model_settings,
            temperature=request.temperature,
            mode="manual",
        )

        return MemoryExtractionResponse(trace=result.trace.public_dict())

    mount_web_app(app, WEB_DIST_DIR)
    return app


async def _run_auto_memory_extraction(
    *,
    storage: Storage,
    memory_graph_store: MemoryGraphStore,
    identity_store: ConversationIdentityStore,
    memory_auto_extraction_store: MemoryAutoExtractionStore,
    current_trace_id: str,
    model_settings: ModelSettings,
    temperature: float,
) -> None:
    try:
        state = memory_auto_extraction_store.get_state()
        pending_traces = [
            trace
            for trace in storage.list_traces_after(
                state.last_source_trace_created_at if state else None
            )
            if _is_ordinary_chat_trace(trace)
        ]
        if not pending_traces:
            return

        current_trace = next(
            (trace for trace in pending_traces if trace.id == current_trace_id),
            None,
        )
        if current_trace is None:
            return

        trigger = _auto_memory_extraction_trigger(
            pending_traces=pending_traces,
            current_trace=current_trace,
        )
        if trigger is None:
            return

        result = await _run_memory_extraction(
            storage=storage,
            memory_graph_store=memory_graph_store,
            identity_store=identity_store,
            source_traces=pending_traces,
            model_settings=model_settings,
            temperature=temperature,
            mode="auto",
            trigger=trigger,
        )
        if result.success:
            memory_auto_extraction_store.mark_extracted(
                last_source_trace=result.source_traces[-1],
                extraction_trace_id=result.trace.id,
            )
    except Exception:
        return


async def _run_memory_extraction(
    *,
    storage: Storage,
    memory_graph_store: MemoryGraphStore,
    identity_store: ConversationIdentityStore,
    source_traces: list[TraceRecord],
    model_settings: ModelSettings,
    temperature: float,
    mode: str,
    trigger: str | None = None,
) -> MemoryExtractionRunResult:
    selected_traces = sorted(source_traces, key=lambda item: item.created_at)
    current_identity = identity_store.get_or_create_identity(
        channel=WEB_IDENTITY_CHANNEL,
        channel_instance=WEB_IDENTITY_INSTANCE,
    )
    prompt_messages = _build_memory_extraction_messages(
        source_traces=[trace.public_dict() for trace in selected_traces],
        current_user_identity=current_identity.current_user_identity,
    )
    tools = memory_graph_update_tools()
    tool_choice = memory_tool_choice()
    model_client = ModelClient()
    request_payload = model_client.build_request_payload(
        model_settings=model_settings,
        messages=prompt_messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
    )
    source_trace_ids = [trace.id for trace in selected_traces]
    request_payload["_peppa"] = {
        "kind": "memory_extraction",
        "mode": mode,
        "source_trace_ids": source_trace_ids,
        "source_trace_order": source_trace_ids,
        "current_user_identity": current_identity.current_user_identity,
        "current_user_memory_node_id": current_identity.memory_node_id,
    }
    if trigger:
        request_payload["_peppa"]["trigger"] = trigger

    response_payload: dict[str, Any] | None = None
    response_tool_calls = []
    assistant_message: str | None = None
    error: str | None = None
    started_at = perf_counter()
    try:
        response = await model_client.chat(
            model_settings=model_settings,
            messages=prompt_messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
        )
        response_payload = response.response_payload
        response_tool_calls = response.tool_calls
        assistant_message = response.content
    except Exception as exc:
        error = str(exc)

    conversation_id = storage.create_conversation("Memory extraction")
    duration_ms = int((perf_counter() - started_at) * 1000)
    trace = storage.create_trace(
        conversation_id=conversation_id,
        model=model_settings.model,
        user_message=f"Memory extraction from {len(selected_traces)} trace(s)",
        assistant_message=assistant_message,
        prompt_messages=prompt_messages,
        request_payload=request_payload,
        response_payload=response_payload,
        duration_ms=duration_ms,
        error=error,
    )

    success = error is None
    if response_payload is not None and success:
        followup_errors = []
        try:
            await asyncio.to_thread(
                memory_graph_store.record_tool_calls,
                extraction_trace_id=trace.id,
                model=model_settings.model,
                tool_calls=response_tool_calls,
                source_trace_ids=source_trace_ids,
            )
        except Exception as exc:
            followup_errors.append(str(exc))
        followup_errors.extend(_memory_tool_call_errors(response_tool_calls))
        if followup_errors:
            success = False
            updated_trace = storage.update_trace_error(trace.id, "; ".join(followup_errors))
            if updated_trace is not None:
                trace = updated_trace

    return MemoryExtractionRunResult(
        trace=trace,
        source_traces=selected_traces,
        success=success,
    )


def _load_memory_source_traces(storage: Storage, trace_ids: list[str]) -> list[TraceRecord]:
    selected_traces = []
    for trace_id in trace_ids:
        record = storage.get_trace(trace_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
        if _is_tool_call_trace(record.public_dict()):
            raise HTTPException(
                status_code=400,
                detail=f"Memory extraction traces cannot be used as input: {trace_id}",
            )
        selected_traces.append(record)
    return selected_traces


def _auto_memory_extraction_trigger(
    *,
    pending_traces: list[TraceRecord],
    current_trace: TraceRecord,
) -> str | None:
    if _has_topic_boundary_tool_call(current_trace.public_dict()):
        return "topic_boundary"
    if len(pending_traces) >= AUTO_MEMORY_EXTRACTION_TURN_THRESHOLD:
        return "turn_count"
    return None


def _trace_payload_with_auto_memory_marker(
    trace: TraceRecord,
    state: MemoryAutoExtractionState | None,
) -> dict[str, Any]:
    payload = trace.public_dict()
    cutoff = state.last_source_trace_created_at if state else None
    payload["auto_memory_extracted"] = bool(
        cutoff and trace.created_at <= cutoff and _is_ordinary_chat_trace(trace)
    )
    return payload


def _is_ordinary_chat_trace(trace: TraceRecord) -> bool:
    payload = trace.public_dict()
    if _is_tool_call_trace(payload):
        return False
    request_meta = payload.get("request_payload", {}).get("_peppa")
    if isinstance(request_meta, dict) and request_meta.get("kind") not in {None, "chat"}:
        return False
    return True


def _has_topic_boundary_tool_call(trace: dict[str, Any]) -> bool:
    response_payload = trace.get("response_payload")
    if not isinstance(response_payload, dict):
        return False
    choices = response_payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            continue
        tool_calls = choice["message"].get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if _tool_call_name(tool_call) == TOPIC_BOUNDARY_TOOL_NAME:
                return True
    return False


def _memory_tool_call_errors(tool_calls: list[Any]) -> list[str]:
    errors = []
    for tool_call in tool_calls:
        if tool_call.name != MEMORY_TOOL_NAME:
            continue
        if tool_call.parse_error or tool_call.arguments is None:
            errors.append(tool_call.parse_error or "Memory tool call arguments are missing.")
    return errors


def _consume_background_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception:
        return


def _apply_identity_tool_calls(
    *,
    identity_store: ConversationIdentityStore,
    tool_calls: list[Any],
) -> list[str]:
    errors = []
    for tool_call in tool_calls:
        if tool_call.name != IDENTITY_TOOL_NAME:
            continue
        if tool_call.parse_error or tool_call.arguments is None:
            errors.append(tool_call.parse_error or "Identity tool call arguments are missing.")
            continue
        try:
            identity_store.bind_identity_from_tool_arguments(
                channel=WEB_IDENTITY_CHANNEL,
                channel_instance=WEB_IDENTITY_INSTANCE,
                arguments=tool_call.arguments,
            )
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def _build_identity_extraction_messages(
    *,
    source_traces: list[dict[str, Any]],
    current_identity: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    context_blocks = []
    for index, trace in enumerate(source_traces, start=1):
        assistant_text = trace.get("assistant_message") or trace.get("error") or ""
        context_blocks.append(
            "\n".join(
                [
                    f"## Turn {index}",
                    f"trace_id: {trace.get('id')}",
                    f"model: {trace.get('model')}",
                    f"user: {trace.get('user_message')}",
                    f"assistant: {assistant_text}",
                ]
            )
        )

    user_content = "\n\n".join(
        [
            "当前对话入口身份状态：",
            json.dumps(current_identity, ensure_ascii=False, indent=2),
            "候选 person nodes：",
            json.dumps(candidates, ensure_ascii=False, indent=2),
            "以下是按时间顺序排列的对话内容：",
            "\n\n".join(context_blocks),
        ]
    )

    return [
        {
            "role": "system",
            "content": load_skill("conversation-identity/SKILL.md"),
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _build_memory_extraction_messages(
    *,
    source_traces: list[dict[str, Any]],
    current_user_identity: str,
) -> list[dict[str, Any]]:
    context_blocks = []
    for index, trace in enumerate(source_traces, start=1):
        assistant_text = trace.get("assistant_message") or trace.get("error") or ""
        context_blocks.append(
            "\n".join(
                [
                    f"## Turn {index}",
                    f"trace_id: {trace.get('id')}",
                    f"model: {trace.get('model')}",
                    f"user: {trace.get('user_message')}",
                    f"assistant: {assistant_text}",
                ]
            )
        )

    return [
        {
            "role": "system",
            "content": _render_identity_template(
                load_skill("memory-extraction/SKILL.md"),
                current_user_identity=current_user_identity,
            ),
        },
        {
            "role": "user",
            "content": "以下是按时间顺序排列的对话内容：\n\n" + "\n\n".join(context_blocks),
        },
    ]


def _render_identity_template(content: str, *, current_user_identity: str) -> str:
    return content.replace("{{current_user_identity}}", current_user_identity)


def _is_tool_call_trace(trace: dict[str, Any]) -> bool:
    request_meta = trace.get("request_payload", {}).get("_peppa")
    if isinstance(request_meta, dict) and request_meta.get("kind") in {
        "identity_update",
        "memory_extraction",
    }:
        return True

    response_payload = trace.get("response_payload")
    if not isinstance(response_payload, dict):
        return False
    choices = response_payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            continue
        tool_calls = choice["message"].get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if _tool_call_name(tool_call) != TOPIC_BOUNDARY_TOOL_NAME:
                return True
    return False


def _tool_call_name(tool_call: Any) -> str | None:
    if not isinstance(tool_call, dict):
        return None
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    name = tool_call.get("name")
    return name if isinstance(name, str) else None


def mount_web_app(app: FastAPI, dist_dir: Path) -> None:
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    index_file = dist_dir / "index.html"

    @app.get("/", response_model=None)
    async def index():
        if index_file.exists():
            return FileResponse(index_file)
        return {
            "message": "Peppa API is running. Build the web console with `npm run build` in web/."
        }

    @app.get("/{path:path}", response_model=None)
    async def spa_fallback(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "Web console is not built yet."}


app = create_app()
