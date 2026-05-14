from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from peppa import __version__
from peppa.config import ConfigError, load_settings
from peppa.core import Agent
from peppa.memory import Storage, memory_graph_update_tools, memory_tool_choice
from peppa.models import ModelClient
from peppa.paths import DATABASE_PATH, ROOT_DIR, WEB_DIST_DIR, ensure_runtime_dirs
from peppa.prompts import load_prompt


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None
    conversation_id: str | None = None
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class ChatResponse(BaseModel):
    conversation_id: str
    trace: dict[str, Any]


class MemoryToolTestRequest(BaseModel):
    trace_ids: list[str] = Field(min_length=1, max_length=20)
    model: str | None = None
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class MemoryToolTestResponse(BaseModel):
    trace: dict[str, Any]


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    storage = Storage()
    storage.initialize()

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
            return load_settings().public_dict()
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        try:
            settings = load_settings()
            agent = Agent(settings=settings, storage=storage)
            result = await agent.chat(
                user_message=request.message,
                requested_model=request.model,
                conversation_id=request.conversation_id,
                temperature=request.temperature,
            )
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return ChatResponse(**result.public_dict())

    @app.get("/api/traces")
    async def traces(limit: int = 25) -> dict[str, Any]:
        return {
            "traces": [trace.public_dict() for trace in storage.list_traces(limit=limit)],
        }

    @app.get("/api/traces/{trace_id}")
    async def trace(trace_id: str) -> dict[str, Any]:
        record = storage.get_trace(trace_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Trace not found.")
        return record.public_dict()

    @app.post("/api/memory/tool-call-test", response_model=MemoryToolTestResponse)
    async def memory_tool_call_test(request: MemoryToolTestRequest) -> MemoryToolTestResponse:
        try:
            settings = load_settings()
            model_settings = settings.get_model(request.model)
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        selected_traces = []
        for trace_id in request.trace_ids:
            record = storage.get_trace(trace_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
            if _is_tool_call_trace(record.public_dict()):
                raise HTTPException(
                    status_code=400,
                    detail=f"Tool-call traces cannot be used as memory test input: {trace_id}",
                )
            selected_traces.append(record)

        selected_traces.sort(key=lambda item: item.created_at)
        prompt_messages = _build_memory_tool_test_messages(
            [trace.public_dict() for trace in selected_traces]
        )
        tools = memory_graph_update_tools()
        tool_choice = memory_tool_choice()
        model_client = ModelClient()
        request_payload = model_client.build_request_payload(
            model=model_settings.model,
            messages=prompt_messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=request.temperature,
        )
        request_payload["_peppa"] = {
            "kind": "memory_tool_test",
            "source_trace_ids": request.trace_ids,
            "source_trace_order": [trace.id for trace in selected_traces],
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
        except Exception as exc:
            error = str(exc)

        conversation_id = storage.create_conversation("Memory tool-call test")
        duration_ms = int((perf_counter() - started_at) * 1000)
        trace = storage.create_trace(
            conversation_id=conversation_id,
            model=model_settings.model,
            user_message=f"Memory tool-call test from {len(selected_traces)} trace(s)",
            assistant_message=assistant_message,
            prompt_messages=prompt_messages,
            memory_hits=[],
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=duration_ms,
            error=error,
        )

        return MemoryToolTestResponse(trace=trace.public_dict())

    mount_web_app(app, WEB_DIST_DIR)
    return app


def _build_memory_tool_test_messages(source_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
            "content": load_prompt("memory/tool-call-test-system.md"),
        },
        {
            "role": "user",
            "content": "以下是按时间顺序排列的对话内容：\n\n" + "\n\n".join(context_blocks),
        },
    ]


def _is_tool_call_trace(trace: dict[str, Any]) -> bool:
    request_meta = trace.get("request_payload", {}).get("_peppa")
    if isinstance(request_meta, dict) and request_meta.get("kind") == "memory_tool_test":
        return True

    response_payload = trace.get("response_payload")
    if not isinstance(response_payload, dict):
        return False
    choices = response_payload.get("choices")
    if not isinstance(choices, list):
        return False
    return any(
        isinstance(choice, dict)
        and isinstance(choice.get("message"), dict)
        and isinstance(choice["message"].get("tool_calls"), list)
        and len(choice["message"]["tool_calls"]) > 0
        for choice in choices
    )


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
