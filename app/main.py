"""FastAPI entry point: WebSocket chat endpoint, health check and the demo UI."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .config import settings
from .copilot import Copilot, build_client
from .guardrails import build_guardrail
from .retrieval import build_retriever
from .store import build_order_repository, build_session_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_QUESTION_CHARS = 2000

app = FastAPI(title="Bedrock Support Copilot")
copilot = Copilot(
    settings=settings,
    client=build_client(settings),
    retriever=build_retriever(settings),
    guardrail=build_guardrail(settings),
    sessions=build_session_store(settings),
    orders=build_order_repository(settings),
)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": settings.mode,
        "model": settings.model_id,
        "knowledge_base": bool(settings.knowledge_base_id),
        "guardrail": bool(settings.guardrail_id),
    }


@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    session_id = ws.query_params.get("session_id") or uuid.uuid4().hex
    await ws.send_json({"type": "session", "session_id": session_id})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                question = str(json.loads(raw).get("message", "")).strip()
            except (json.JSONDecodeError, AttributeError):
                question = raw.strip()
            if not question:
                continue
            if len(question) > MAX_QUESTION_CHARS:
                await ws.send_json({"type": "error", "message": "Message too long."})
                continue
            async for event in copilot.run_turn(session_id, question):
                await ws.send_json(event)
    except WebSocketDisconnect:
        pass
