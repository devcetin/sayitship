"""Settings read from environment variables, a local .env file and projects.json."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    description: str


@dataclass(frozen=True)
class Settings:
    token: str
    ntfy_server: str
    ntfy_topic: str
    projects: dict[str, Project]  # first one is the default
    public_url: str  # how the phone reaches this server (used in approval buttons)
    data_dir: Path
    task_timeout: int = 1800
    approval_timeout: int = 300
    gemini_api_key: str = ""
    router_models: list[str] = field(default_factory=list)
    claude_args: list[str] = field(default_factory=list)

    @property
    def default_project(self) -> Project:
        return next(iter(self.projects.values()))


def load_projects(path: Path) -> dict[str, Project]:
    """Read projects.json: a list of {"name", "path", "description"}."""
    if not path.is_file():
        raise RuntimeError(f"{path.name} not found. Copy projects.example.json to {path.name}.")
    projects: dict[str, Project] = {}
    for item in json.loads(path.read_text(encoding="utf-8")):
        name = str(item["name"]).strip()
        folder = Path(item["path"]).expanduser().resolve()
        if not folder.is_dir():
            raise RuntimeError(f"Project {name!r}: folder does not exist: {folder}")
        projects[name] = Project(name, folder, str(item.get("description", "")).strip())
    if not projects:
        raise RuntimeError(f"{path.name} has no projects.")
    return projects


def user_env(name: str) -> str:
    """Read a variable from the process, or on Windows from the saved user variables.

    A shell opened before the variable was set does not see it; the registry always does.
    """
    value = os.environ.get(name, "")
    if value or os.name != "nt":
        return value
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return ""


def _list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    token = os.environ.get("SAYITSHIP_TOKEN", "")
    if len(token) < 16:
        raise RuntimeError("SAYITSHIP_TOKEN is missing or too short (min 16 chars).")
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        raise RuntimeError("NTFY_TOPIC is missing.")

    host = os.environ.get("HOST", "127.0.0.1")
    port = os.environ.get("PORT", "8787")
    data_dir = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        token=token,
        ntfy_server=os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        ntfy_topic=topic,
        projects=load_projects(Path(os.environ.get("PROJECTS_FILE", REPO_ROOT / "projects.json"))),
        public_url=os.environ.get("PUBLIC_URL", f"http://{host}:{port}").rstrip("/"),
        data_dir=data_dir,
        task_timeout=int(os.environ.get("TASK_TIMEOUT", "1800")),
        approval_timeout=int(os.environ.get("APPROVAL_TIMEOUT", "300")),
        gemini_api_key=user_env("GEMINI_API_KEY"),
        router_models=_list(
            os.environ.get("ROUTER_MODELS", "gemini-3.5-flash-lite,gemini-flash-lite-latest")
        ),
        claude_args=os.environ.get(
            "CLAUDE_ARGS",
            "--permission-mode acceptEdits "
            "--allowedTools Read Edit Write Glob Grep WebSearch WebFetch Bash",
        ).split(),
    )
