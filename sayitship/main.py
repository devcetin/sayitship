"""HTTP entry point: accept a request, answer right away, do the work in the background."""

import base64
import binascii
import hashlib
import logging
import secrets
import time
import uuid
from functools import lru_cache

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .db import Store
from .notify import send_notification
from .runner import Request, process

log = logging.getLogger("sayitship")

app = FastAPI(title="sayitship")

# A fresh secret per server start, given only to the approval hook (never the main token).
HOOK_TOKEN = secrets.token_urlsafe(32)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"RIFF": "webp"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024


def audio_mime(raw: bytes) -> str | None:
    """Recognize the audio formats Gemini accepts. iPhone recordings are .m4a (MP4 container)."""
    if raw[4:8] == b"ftyp":
        return "audio/mp4"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        return "audio/wav"
    if raw[:3] == b"ID3" or raw[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mp3"
    if raw[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return "audio/aac"
    if raw[:4] == b"OggS":
        return "audio/ogg"
    if raw[:4] == b"fLaC":
        return "audio/flac"
    return None


def decode_b64(data: str, what: str) -> bytes:
    try:
        return base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail=f"{what} is not valid base64")


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@lru_cache
def get_store() -> Store:
    store = Store(get_settings().data_dir / "sayitship.db")
    if store.mark_interrupted():
        log.info("marked unfinished tasks from the previous run as interrupted")
    return store


def _bearer_ok(authorization: str, expected: str) -> bool:
    scheme, _, given = authorization.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(given.encode(), expected.encode())


def check_token(
    authorization: str = Header(default=""), settings: Settings = Depends(get_settings)
) -> Settings:
    if not _bearer_ok(authorization, settings.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return settings


def check_hook_token(authorization: str = Header(default="")) -> None:
    if not _bearer_ok(authorization, HOOK_TOKEN):
        raise HTTPException(status_code=401, detail="invalid token")


class TaskIn(BaseModel):
    text: str = Field(default="", max_length=4000)  # dictated text, or empty when audio is sent
    audio: str = Field(default="", max_length=MAX_AUDIO_BYTES * 4 // 3 + 4)  # base64 recording
    clipboard: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=2000)
    image: str = Field(default="", max_length=MAX_IMAGE_BYTES * 4 // 3 + 4)  # base64
    project: str | None = None  # a name from projects.json, never a raw path


def save_image(data_b64: str, task_id: str, settings: Settings):
    raw = decode_b64(data_b64, "image")
    ext = next((e for magic, e in IMAGE_TYPES.items() if raw.startswith(magic)), None)
    if ext is None:
        raise HTTPException(status_code=422, detail="image must be PNG, JPEG, GIF or WebP")
    inbox = settings.data_dir / "inbox"
    inbox.mkdir(exist_ok=True)
    path = inbox / f"{task_id}.{ext}"
    path.write_bytes(raw)
    return path


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/task", status_code=202)
def create_task(
    task: TaskIn,
    background: BackgroundTasks,
    settings: Settings = Depends(check_token),
    store: Store = Depends(get_store),
) -> dict:
    text = task.text.strip()
    audio = None
    if task.audio.strip():
        raw = decode_b64(task.audio, "audio")
        mime = audio_mime(raw)
        if mime is None:
            raise HTTPException(status_code=422, detail="audio must be m4a, wav, mp3, aac, ogg or flac")
        if not settings.gemini_api_key:
            raise HTTPException(status_code=422, detail="audio needs GEMINI_API_KEY on the server")
        audio = (raw, mime)
    if not text and audio is None:
        raise HTTPException(status_code=422, detail="send text or audio")
    if task.project and task.project not in settings.projects:
        raise HTTPException(status_code=400, detail="unknown project")

    task_id = uuid.uuid4().hex[:8]
    image_path = save_image(task.image, task_id, settings) if task.image.strip() else None
    req = Request(
        task_id=task_id,
        text=text,
        clipboard=task.clipboard.strip(),
        url=task.url.strip(),
        image_path=image_path,
        project=task.project,
        audio=audio,
    )
    store.add_task(
        task_id, text or "(voice recording)", bool(req.clipboard), bool(req.url), image_path is not None
    )
    background.add_task(process, req, settings, store, HOOK_TOKEN)
    return {"id": task_id, "status": "accepted"}


@app.get("/tasks")
def list_tasks(
    limit: int = Query(default=20, ge=1, le=200),
    _: Settings = Depends(check_token),
    store: Store = Depends(get_store),
) -> list[dict]:
    return store.recent_tasks(limit)


@app.get("/tasks/{task_id}")
def get_task(task_id: str, _: Settings = Depends(check_token), store: Store = Depends(get_store)) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="not found")
    return task


# ---- approvals -----------------------------------------------------------------------------

class ApprovalIn(BaseModel):
    tool: str = Field(max_length=100)
    detail: str = Field(max_length=2000)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@app.post("/internal/approvals", dependencies=[Depends(check_hook_token)])
def create_approval(
    body: ApprovalIn, settings: Settings = Depends(get_settings), store: Store = Depends(get_store)
) -> dict:
    """Called by hook.py. Sends a Yes/No notification whose buttons carry a one-time key."""
    approval_id = uuid.uuid4().hex[:12]
    key = secrets.token_urlsafe(24)  # only its hash is stored
    store.add_approval(approval_id, _hash(key), body.tool, body.detail)
    base = f"{settings.public_url}/approvals/{approval_id}"
    send_notification(
        settings.ntfy_server,
        settings.ntfy_topic,
        f"❓ Claude wants to run {body.tool}",
        body.detail,
        actions=[
            {"action": "http", "label": "Yes", "url": f"{base}/allow?key={key}", "method": "POST", "clear": True},
            {"action": "http", "label": "No", "url": f"{base}/deny?key={key}", "method": "POST", "clear": True},
        ],
        priority=4,
    )
    return {"id": approval_id}


@app.get("/internal/approvals/{approval_id}", dependencies=[Depends(check_hook_token)])
def get_approval(approval_id: str, store: Store = Depends(get_store)) -> dict:
    approval = store.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"id": approval_id, "decision": approval["decision"]}


@app.post("/approvals/{approval_id}/{decision}")
def decide(
    approval_id: str,
    decision: str,
    key: str = Query(min_length=1),
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
) -> dict:
    """Pressed from the phone. The one-time key from the notification is the only credential."""
    if decision not in ("allow", "deny"):
        raise HTTPException(status_code=404, detail="not found")
    approval = store.get_approval(approval_id)
    if approval is None or not secrets.compare_digest(approval["key_hash"], _hash(key)):
        raise HTTPException(status_code=403, detail="invalid key")
    if time.time() - approval["created"] > settings.approval_timeout + 60:
        raise HTTPException(status_code=410, detail="expired")
    if not store.decide_approval(approval_id, decision):
        raise HTTPException(status_code=409, detail="already decided")
    log.info("approval %s: %s", approval_id, decision)
    return {"id": approval_id, "decision": decision}
