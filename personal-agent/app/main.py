from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import skills
from .agent import run_agent

app = FastAPI(title="Personal Skill Agent")

STATIC_DIR = Path(__file__).parent / "static"

# Single-user local tool: one in-memory conversation.
_history: list[dict] = []


@app.get("/api/health")
def health():
    return {"ok": True, "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/api/skills")
def list_skills():
    return [
        {"name": s.name, "description": s.description, "file_count": len(s.files)}
        for s in skills.discover_skills()
    ]


@app.get("/api/skills/{name}")
def get_skill(name: str):
    s = skills.get_skill(name)
    if s is None:
        raise HTTPException(404, f"no such skill: {name}")
    return {"name": s.name, "description": s.description, "instructions": s.body, "files": s.files}


@app.get("/api/skills/{name}/file")
def get_skill_file(name: str, path: str):
    try:
        return {"content": skills.read_skill_file(name, path)}
    except skills.SkillError as e:
        raise HTTPException(400, str(e))


class CreateSkillBody(BaseModel):
    name: str
    description: str
    content: str


@app.post("/api/skills")
def create_skill(body: CreateSkillBody):
    try:
        s = skills.create_skill(body.name, body.description, body.content)
    except skills.SkillError as e:
        raise HTTPException(400, str(e))
    return {"name": s.name, "description": s.description, "files": s.files}


@app.delete("/api/skills/{name}")
def delete_skill(name: str):
    try:
        skills.delete_skill(name)
    except skills.SkillError as e:
        raise HTTPException(400, str(e))
    return {"deleted": name}


class DownloadSkillBody(BaseModel):
    repo_url: str
    skill_path: str | None = None
    rename: str | None = None


@app.post("/api/skills/download")
def download_skill(body: DownloadSkillBody):
    try:
        s = skills.download_skill(body.repo_url, body.skill_path, body.rename)
    except skills.SkillError as e:
        raise HTTPException(400, str(e))
    return {"name": s.name, "description": s.description, "files": s.files}


class ChatBody(BaseModel):
    message: str


@app.post("/api/chat/stream")
def chat_stream(body: ChatBody):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set on the server")

    q: queue.Queue = queue.Queue()
    SENTINEL = object()

    def worker():
        def log(event: dict):
            q.put(event)

        try:
            new_history = run_agent(_history, body.message, log)
            _history.clear()
            _history.extend(new_history)
            q.put({"type": "done"})
        except Exception as e:  # surface to the UI instead of a bare 500
            q.put({"type": "error", "text": str(e)})
        finally:
            q.put(SENTINEL)

    def gen():
        threading.Thread(target=worker, daemon=True).start()
        while True:
            event = q.get()
            if event is SENTINEL:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/chat/reset")
def chat_reset():
    _history.clear()
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
