from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from peppa import __version__
from peppa.config import ConfigError, load_settings
from peppa.core import Agent
from peppa.memory import Storage
from peppa.paths import DATABASE_PATH, ROOT_DIR, WEB_DIST_DIR, ensure_runtime_dirs


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None
    conversation_id: str | None = None
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)


class ChatResponse(BaseModel):
    conversation_id: str
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

    mount_web_app(app, WEB_DIST_DIR)
    return app


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
