"""Handle one request in the background: route it, then answer or run Claude Code, then notify."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import router
from .config import REPO_ROOT, Project, Settings
from .db import Store
from .notify import send_notification

log = logging.getLogger("sayitship")

SUMMARY_HINT = (
    "\n\nThe user will only see the last paragraph of your reply, as a phone notification. "
    "So end with one short plain-text paragraph (no Markdown, at most 3 sentences) in the "
    "language of the request: if the request asked for information, give the answer itself "
    "with the key facts and numbers; otherwise say what you did."
)
MAX_SUMMARY = 600
HOOK_SCRIPT = Path(__file__).with_name("hook.py")
# Variables the child must not see: our own secrets and leftovers from a parent Claude session.
HIDDEN_ENV = ("SAYITSHIP_TOKEN", "NTFY_TOPIC", "GEMINI_API_KEY")

_project_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass
class Request:
    task_id: str
    text: str
    clipboard: str = ""
    url: str = ""
    image_path: Path | None = None
    project: str | None = None  # forced by the client; skips the router's project choice
    understood: str = ""  # the router's cleaned-up text, or its transcript of the audio
    audio: tuple[bytes, str] | None = None  # (recording, mime type) instead of dictated text


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def project_lock(name: str) -> threading.Lock:
    """One Claude run per project at a time; a second task waits its turn."""
    with _locks_guard:
        return _project_locks.setdefault(name, threading.Lock())


def build_prompt(req: Request) -> str:
    parts = [req.understood or req.text]
    if req.text and req.understood and req.understood != req.text:
        parts.append(
            f"\n\n(This request came from voice dictation. Raw transcript: \"{req.text}\". "
            "If the cleaned-up version above looks wrong, go by the transcript.)"
        )
    if req.clipboard:
        parts.append(f"\n\nClipboard content sent with this request:\n<clipboard>\n{req.clipboard}\n</clipboard>")
    if req.url:
        parts.append(f"\n\nLink shared with this request: {req.url}")
    if req.image_path:
        parts.append(
            f"\n\nA screenshot is attached at {req.image_path.as_posix()}. Look at it with the Read tool."
        )
    return "".join(parts) + SUMMARY_HINT


def _rule_path(path: Path) -> str:
    """C:/Users/x -> //c/Users/x, the absolute-path form Claude Code permission rules use."""
    posix = path.resolve().as_posix()
    if len(posix) > 1 and posix[1] == ":":
        posix = "/" + posix[0].lower() + posix[2:]
    return "/" + posix


def protected_rules(settings: Settings) -> list[str]:
    """Claude may never change sayitship itself or read its secrets, whatever the project."""
    repo, data = _rule_path(REPO_ROOT), _rule_path(settings.data_dir)
    rules = [f"Edit({repo}/**)", f"Write({repo}/**)", f"Read({repo}/.env)"]
    rules += [f"Edit({data}/**)", f"Write({data}/**)", f"Read({data}/*.db)", f"Read({data}/*.log)"]
    return rules


def hook_python() -> Path:
    """The hook needs a console Python: under autostart sys.executable is pythonw.exe."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return console if exe.name.lower() == "pythonw.exe" and console.exists() else exe


def hook_settings_file(settings: Settings) -> Path:
    """Write the Claude Code settings: every Bash call goes through hook.py; sayitship is off limits."""
    command = f'"{hook_python().as_posix()}" "{HOOK_SCRIPT.as_posix()}"'
    data = {
        "permissions": {"deny": protected_rules(settings)},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": command, "timeout": settings.approval_timeout + 30}
                    ],
                }
            ]
        }
    }
    path = settings.data_dir / "claude-settings.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def build_command(
    claude_bin: str,
    extra_args: list[str],
    settings_file: Path,
    resume_id: str | None = None,
    add_dirs: list[Path] | None = None,
) -> list[str]:
    # The prompt goes through stdin, so no quoting problems with spaces or Turkish letters.
    cmd = [claude_bin, "-p", "--output-format", "json", "--settings", str(settings_file)]
    if resume_id:
        cmd += ["--resume", resume_id]
    for folder in add_dirs or []:
        cmd += ["--add-dir", str(folder)]
    return cmd + extra_args


def child_env(settings: Settings, hook_token: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDECODE", "CLAUDE_")) and k not in HIDDEN_ENV
    }
    env["SAYITSHIP_URL"] = settings.public_url
    env["SAYITSHIP_HOOK_TOKEN"] = hook_token
    env["SAYITSHIP_APPROVAL_TIMEOUT"] = str(settings.approval_timeout)
    env["SAYITSHIP_PROTECTED"] = "|".join({REPO_ROOT.as_posix(), settings.data_dir.as_posix()})
    return env


def parse_claude_output(stdout: str) -> tuple[str, str | None, bool]:
    """Return (last paragraph, session id, is_error) from claude's JSON output."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "Done, but the output could not be read.", None, True
    result = str(data.get("result") or "").strip()
    session_id = data.get("session_id")
    if data.get("is_error"):
        return f"Error: {result or data.get('subtype', 'unknown')}"[:MAX_SUMMARY], session_id, True
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
    summary = paragraphs[-1] if paragraphs else "Done (no text output)."
    return _short(summary, MAX_SUMMARY), session_id, False


def run_claude(
    req: Request, project: Project, resume_id: str | None, settings: Settings, hook_token: str
) -> tuple[str, str | None, bool]:
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        return "claude command not found.", None, True
    add_dirs = [req.image_path.parent] if req.image_path else []
    try:
        proc = subprocess.run(
            build_command(
                claude_bin, settings.claude_args, hook_settings_file(settings), resume_id, add_dirs
            ),
            input=build_prompt(req),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=project.path,
            env=child_env(settings, hook_token),
            timeout=settings.task_timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Task stopped after {settings.task_timeout} seconds.", None, True
    if proc.returncode != 0 and not proc.stdout.strip():
        return (proc.stderr.strip() or "claude failed.")[-MAX_SUMMARY:], None, True
    return parse_claude_output(proc.stdout)


def process(req: Request, settings: Settings, store: Store, hook_token: str) -> None:
    """Background worker for one request. Never raises: every outcome ends in a notification."""
    try:
        _process(req, settings, store, hook_token)
    except Exception as exc:
        log.exception("task %s crashed", req.task_id)
        store.update_task(req.task_id, status="error", summary=str(exc)[:MAX_SUMMARY], finished=time.time())
        send_notification(
            settings.ntfy_server, settings.ntfy_topic, "⚠️ sayitship error",
            f"{type(exc).__name__}: {exc}"[:MAX_SUMMARY],
        )


def _process(req: Request, settings: Settings, store: Store, hook_token: str) -> None:
    history = store.sessions()
    projects = [{"name": p.name, "description": p.description} for p in settings.projects.values()]
    decision = router.route(
        req.text, projects, history, settings.gemini_api_key, settings.router_models,
        clipboard=req.clipboard, url=req.url, has_image=req.image_path is not None, audio=req.audio,
    )
    if req.audio and decision.model == "fallback":
        # Without the model there is no transcript, so there is nothing to run.
        store.update_task(req.task_id, status="error", summary="transcription failed", finished=time.time())
        send_notification(
            settings.ntfy_server, settings.ntfy_topic, "⚠️ sayitship couldn't hear you",
            "The speech model did not answer. Please try again in a moment.",
        )
        return
    if req.project:  # the client chose the project explicitly
        decision.route, decision.project = "task", req.project
    req.understood = decision.request
    store.update_task(
        req.task_id, understood=decision.request, route=decision.route, project=decision.project,
        session=decision.session, router_model=decision.model, router_ms=decision.latency_ms,
        router_reason=decision.reason, status="running",
    )
    log.info(
        "task %s routed by %s in %d ms: %s / %s / %s (%s)", req.task_id, decision.model,
        decision.latency_ms, decision.route, decision.project, decision.session, decision.reason,
    )

    if decision.route == "answer":
        store.update_task(req.task_id, status="done", summary=decision.answer, finished=time.time())
        send_notification(
            settings.ntfy_server, settings.ntfy_topic, f"⚡ {_short(decision.request)}", decision.answer
        )
        return

    project = settings.projects[decision.project]
    with project_lock(project.name):
        # Read the session after taking the lock, so a queued task continues the newest one.
        last = store.sessions().get(project.name)
        resume_id = last["session_id"] if decision.session == "continue" and last else None
        summary, session_id, failed = run_claude(req, project, resume_id, settings, hook_token)
        if session_id and not failed:
            store.save_session(project.name, session_id, req.understood or req.text)

    store.update_task(
        req.task_id, status="error" if failed else "done", summary=summary,
        claude_session_id=session_id, finished=time.time(),
    )
    mode = "continue" if resume_id else "new"
    title = f"⚠️ {project.name} · error" if failed else f"🛠 {project.name} · {mode}"
    message = f"{summary}\n\n🎙 {req.understood}" if req.understood else summary
    send_notification(settings.ntfy_server, settings.ntfy_topic, title, message)
