"""Claude Code PreToolUse hook: ask the phone before Claude runs a shell command.

Claude Code starts this script before each Bash call and sends the call as JSON on stdin.
Read-only commands are allowed right away. Anything else becomes an approval request:
the server sends a Yes/No notification and this script waits for the answer.
On any error the answer is "deny" (fail closed).

Only the standard library is used, so the script runs without the package being installed.
"""

import json
import os
import re
import sys
import time
import urllib.request

SAFE_COMMANDS = (
    "git status", "git diff", "git log", "git show", "git branch", "git remote -v",
    "ls", "dir", "pwd", "cat", "type", "head", "tail", "wc", "echo",
    "where", "which", "rg", "grep", "find", "tree",
    "python --version", "node --version", "npm --version",
)
# Chaining, redirection, substitution and destructive find flags make any command unsafe.
UNSAFE_PATTERN = re.compile(r"[;&|<>`\n]|\$\(|-exec|-delete|-ok\b")


def is_safe(command: str) -> bool:
    command = command.strip()
    if not command or UNSAFE_PATTERN.search(command):
        return False
    return any(command == safe or command.startswith(safe + " ") for safe in SAFE_COMMANDS)


def decision(value: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": value,
            "permissionDecisionReason": reason,
        }
    }


def _request(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def ask_phone(tool: str, detail: str, base_url: str, token: str, timeout: int) -> dict:
    created = _request("POST", f"{base_url}/internal/approvals", token, {"tool": tool, "detail": detail})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _request("GET", f"{base_url}/internal/approvals/{created['id']}", token)
        if state.get("decision") == "allow":
            return decision("allow", "Approved on the phone.")
        if state.get("decision") == "deny":
            return decision("deny", "The user said no on the phone. Do not retry; explain what you wanted to do.")
        time.sleep(1)
    return decision("deny", "No answer from the phone in time. Do not retry.")


def handle(event: dict, env: dict) -> dict:
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        if is_safe(command):
            return decision("allow", "Read-only command.")
        detail = command
    else:
        detail = json.dumps(tool_input, ensure_ascii=False)
    try:
        return ask_phone(
            tool,
            detail[:500],
            env["SAYITSHIP_URL"],
            env["SAYITSHIP_HOOK_TOKEN"],
            int(env.get("SAYITSHIP_APPROVAL_TIMEOUT", "300")),
        )
    except Exception as exc:  # fail closed
        return decision("deny", f"Approval system error ({type(exc).__name__}). Do not retry.")


def main() -> None:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError:
        event = {}
    sys.stdout.write(json.dumps(handle(event, dict(os.environ))))


if __name__ == "__main__":
    main()
