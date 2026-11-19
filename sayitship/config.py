"""Settings read from environment variables (and a local .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    token: str
    ntfy_server: str
    ntfy_topic: str
    workdirs: dict[str, Path]  # name -> folder Claude Code is allowed to work in
    task_timeout: int  # seconds
    claude_args: list[str]


def parse_workdirs(raw: str) -> dict[str, Path]:
    """Parse "name=path;name2=path2". The first entry is the default."""
    workdirs: dict[str, Path] = {}
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        name, sep, path = item.partition("=")
        if not sep or not name.strip() or not path.strip():
            raise ValueError(f"WORKDIRS entry must look like name=path, got: {item!r}")
        workdirs[name.strip()] = Path(path.strip()).resolve()
    return workdirs


def load_settings() -> Settings:
    load_dotenv()
    token = os.environ.get("SAYITSHIP_TOKEN", "")
    if len(token) < 16:
        raise RuntimeError("SAYITSHIP_TOKEN is missing or too short (min 16 chars).")
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        raise RuntimeError("NTFY_TOPIC is missing.")
    workdirs = parse_workdirs(os.environ.get("WORKDIRS", ""))
    if not workdirs:
        raise RuntimeError("WORKDIRS is empty. Example: WORKDIRS=sandbox=C:/code/sandbox")
    for name, path in workdirs.items():
        if not path.is_dir():
            raise RuntimeError(f"WORKDIRS[{name}] is not a folder: {path}")
    return Settings(
        token=token,
        ntfy_server=os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        ntfy_topic=topic,
        workdirs=workdirs,
        task_timeout=int(os.environ.get("TASK_TIMEOUT", "1800")),
        claude_args=os.environ.get(
            "CLAUDE_ARGS",
            "--permission-mode acceptEdits --allowedTools Read Edit Write Glob Grep",
        ).split(),
    )
