"""Run one task with Claude Code in the background and report the result."""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .notify import send_notification

log = logging.getLogger("sayitship")

SUMMARY_HINT = (
    "\n\nWhen you are done, end your reply with one short plain sentence "
    "that summarizes what you did. Write it in the same language as the task."
)
MAX_SUMMARY = 300


def build_command(claude_bin: str, extra_args: list[str]) -> list[str]:
    # The prompt goes through stdin, so no quoting problems with spaces or Turkish letters.
    return [claude_bin, "-p", "--output-format", "json", *extra_args]


def child_env() -> dict[str, str]:
    """Environment for claude: drop variables left over from a parent Claude Code session."""
    return {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_"))
    }


def extract_summary(stdout: str) -> str:
    """Take the last non-empty line of claude's JSON `result` field."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "Done, but the output could not be read."
    result = str(data.get("result") or "").strip()
    if data.get("is_error"):
        return f"Error: {result or data.get('subtype', 'unknown')}"[:MAX_SUMMARY]
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    summary = lines[-1] if lines else "Done (no text output)."
    return summary[:MAX_SUMMARY]


def run_task(
    task_id: str,
    text: str,
    workdir: Path,
    timeout: int,
    extra_args: list[str],
    ntfy_server: str,
    ntfy_topic: str,
) -> None:
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        send_notification(ntfy_server, ntfy_topic, "sayitship: error", "claude command not found.")
        return

    log.info("task %s started in %s", task_id, workdir)
    try:
        proc = subprocess.run(
            build_command(claude_bin, extra_args),
            input=text + SUMMARY_HINT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=workdir,
            env=child_env(),
            timeout=timeout,
        )
        if proc.returncode != 0 and not proc.stdout.strip():
            title, message = "sayitship: error", (proc.stderr.strip() or "claude failed.")[-MAX_SUMMARY:]
        else:
            message = extract_summary(proc.stdout)
            title = "sayitship: error" if message.startswith("Error:") else "sayitship: done"
    except subprocess.TimeoutExpired:
        title, message = "sayitship: timeout", f"Task stopped after {timeout} seconds."
    except Exception as exc:  # report anything unexpected instead of failing silently
        log.exception("task %s crashed", task_id)
        title, message = "sayitship: error", f"{type(exc).__name__}: {exc}"[:MAX_SUMMARY]

    log.info("task %s finished: %s", task_id, title)
    send_notification(ntfy_server, ntfy_topic, title, message)
