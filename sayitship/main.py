"""HTTP entry point: accept a task, answer right away, run it in the background."""

import logging
import secrets
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .runner import run_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="sayitship")


def get_settings() -> Settings:
    return load_settings()


class Task(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    workdir: str | None = None  # a name from WORKDIRS, never a raw path


def check_token(
    authorization: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> Settings:
    scheme, _, given = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(given, settings.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return settings


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/task", status_code=202)
def create_task(
    task: Task,
    background: BackgroundTasks,
    settings: Settings = Depends(check_token),
) -> dict:
    text = task.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is empty")

    name = task.workdir or next(iter(settings.workdirs))
    if name not in settings.workdirs:
        raise HTTPException(status_code=400, detail="unknown workdir")

    task_id = uuid.uuid4().hex[:8]
    background.add_task(
        run_task,
        task_id,
        text,
        settings.workdirs[name],
        settings.task_timeout,
        settings.claude_args,
        settings.ntfy_server,
        settings.ntfy_topic,
    )
    return {"id": task_id, "status": "accepted", "workdir": name}
