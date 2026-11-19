import pytest

from sayitship import hook


@pytest.mark.parametrize(
    "command",
    ["git status", "git diff --stat", "ls -la", "cat README.md", "grep -r foo src", "pwd"],
)
def test_read_only_commands_are_safe(command):
    assert hook.is_safe(command)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /", "npm install", "git push", "git status; rm x", "cat a > b", "ls | sh",
        "echo $(whoami)", "find . -delete", "find . -exec rm {} ;", "lsblk", "", "git statusx",
    ],
)
def test_other_commands_are_not_safe(command):
    assert not hook.is_safe(command)


def test_safe_bash_is_allowed_without_asking(monkeypatch):
    monkeypatch.setattr(hook, "ask_phone", lambda *a: pytest.fail("should not ask"))
    out = hook.handle({"tool_name": "Bash", "tool_input": {"command": "git status"}}, {})
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_risky_bash_asks_the_phone(monkeypatch):
    asked = []
    monkeypatch.setattr(hook, "ask_phone", lambda *a: asked.append(a) or hook.decision("deny", "no"))
    env = {"SAYITSHIP_URL": "http://s", "SAYITSHIP_HOOK_TOKEN": "t"}
    out = hook.handle({"tool_name": "Bash", "tool_input": {"command": "npm install"}}, env)
    assert asked[0][:2] == ("Bash", "npm install")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_errors_fail_closed():
    # no SAYITSHIP_URL in env -> KeyError -> deny
    out = hook.handle({"tool_name": "Bash", "tool_input": {"command": "npm install"}}, {})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_ask_phone_polls_until_decided(monkeypatch):
    answers = iter([{"id": "a1"}, {"decision": None}, {"decision": "allow"}])
    monkeypatch.setattr(hook, "_request", lambda *a, **k: next(answers))
    monkeypatch.setattr(hook.time, "sleep", lambda s: None)
    out = hook.ask_phone("Bash", "npm i", "http://s", "t", timeout=10)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
