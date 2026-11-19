import json
from pathlib import Path

import httpx
import pytest

from sayitship import notify, runner
from sayitship.router import Decision


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(runner, "send_notification", lambda *a, **k: out.append(a) or True)
    return out


def fake_decision(route="task", project="blog", session="new", answer="", request="cleaned"):
    return lambda *a, **k: Decision(
        request=request, route=route, project=project, session=session, answer=answer,
        reason="r", model="m1", latency_ms=5,
    )


def test_answer_route_notifies_without_running_claude(monkeypatch, settings, store, sent):
    monkeypatch.setattr(runner.router, "route", fake_decision("answer", answer="404 = bulunamadı", request="404 ne demek"))
    monkeypatch.setattr(runner, "run_claude", lambda *a: pytest.fail("claude must not run"))
    store.add_task("t1", "404 ne", False, False, False)
    runner.process(runner.Request("t1", "404 ne"), settings, store, "hook")
    assert sent[-1][2:] == ("⚡ 404 ne demek", "404 = bulunamadı")
    assert store.get_task("t1")["status"] == "done"


def test_task_runs_in_routed_project_and_saves_session(monkeypatch, settings, store, sent):
    monkeypatch.setattr(runner.router, "route", fake_decision("task", "blog", "new"))
    seen = []
    monkeypatch.setattr(runner, "run_claude", lambda req, project, resume, s, h: seen.append((project.name, resume)) or ("Footer düzeltildi.", "sess-1", False))
    store.add_task("t1", "footer", False, False, False)
    runner.process(runner.Request("t1", "footer"), settings, store, "hook")
    assert seen == [("blog", None)]
    assert store.sessions()["blog"]["session_id"] == "sess-1"
    assert sent[-1][2:] == ("🛠 blog · new", "Footer düzeltildi.\n\n🎙 cleaned")
    assert store.get_task("t1")["understood"] == "cleaned"
    row = store.get_task("t1")
    assert (row["route"], row["project"], row["router_model"], row["claude_session_id"]) == ("task", "blog", "m1", "sess-1")


def test_continue_resumes_last_session(monkeypatch, settings, store, sent):
    store.save_session("blog", "sess-old", "dark mode")
    monkeypatch.setattr(runner.router, "route", fake_decision("task", "blog", "continue"))
    seen = []
    monkeypatch.setattr(runner, "run_claude", lambda req, project, resume, s, h: seen.append(resume) or ("ok", "sess-new", False))
    store.add_task("t2", "bir de", False, False, False)
    runner.process(runner.Request("t2", "bir de"), settings, store, "hook")
    assert seen == ["sess-old"]
    assert store.sessions()["blog"]["session_id"] == "sess-new"
    assert sent[-1][2] == "🛠 blog · continue"


def test_client_forced_project_overrides_router(monkeypatch, settings, store, sent):
    monkeypatch.setattr(runner.router, "route", fake_decision("answer", "sandbox", answer="x"))
    seen = []
    monkeypatch.setattr(runner, "run_claude", lambda req, project, *a: seen.append(project.name) or ("ok", None, False))
    store.add_task("t3", "x", False, False, False)
    runner.process(runner.Request("t3", "x", project="blog"), settings, store, "hook")
    assert seen == ["blog"]


def test_crash_still_notifies(monkeypatch, settings, store, sent):
    monkeypatch.setattr(runner.router, "route", lambda *a, **k: 1 / 0)
    store.add_task("t4", "x", False, False, False)
    runner.process(runner.Request("t4", "x"), settings, store, "hook")
    assert sent[-1][2] == "⚠️ sayitship error"
    assert store.get_task("t4")["status"] == "error"


def test_prompt_includes_context():
    req = runner.Request("t", "düzelt", clipboard="Traceback", url="https://x.dev", image_path=Path("C:/d/inbox/t.png"))
    prompt = runner.build_prompt(req)
    assert prompt.startswith("düzelt")
    assert "<clipboard>\nTraceback\n</clipboard>" in prompt
    assert "https://x.dev" in prompt and "C:/d/inbox/t.png" in prompt


def test_build_command_and_hook_settings(settings):
    path = runner.hook_settings_file(settings)
    hooks = json.loads(path.read_text())["hooks"]["PreToolUse"][0]
    assert hooks["matcher"] == "Bash" and "hook.py" in hooks["hooks"][0]["command"]
    cmd = runner.build_command("claude", ["--x"], path, resume_id="s1", add_dirs=[Path("C:/in")])
    assert cmd[:4] == ["claude", "-p", "--output-format", "json"]
    assert cmd[cmd.index("--resume") + 1] == "s1" and "--add-dir" in cmd and cmd[-1] == "--x"


def test_child_env_hides_secrets_and_parent_claude_vars(monkeypatch, settings):
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "SAYITSHIP_TOKEN", "NTFY_TOPIC", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("PATH_TEST", "keep")
    env = runner.child_env(settings, "hook-token")
    assert not {"CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "SAYITSHIP_TOKEN", "NTFY_TOPIC", "GEMINI_API_KEY"} & set(env)
    assert env["PATH_TEST"] == "keep" and env["SAYITSHIP_HOOK_TOKEN"] == "hook-token"
    assert env["SAYITSHIP_URL"] == settings.public_url


def test_parse_claude_output():
    out = json.dumps({"result": "Did things.\n\nREADME güncellendi.", "is_error": False, "session_id": "s"})
    assert runner.parse_claude_output(out) == ("README güncellendi.", "s", False)
    assert runner.parse_claude_output("not json")[2] is True
    assert runner.parse_claude_output(json.dumps({"result": "boom", "is_error": True}))[0] == "Error: boom"


def test_failed_notification_is_swallowed(monkeypatch):
    monkeypatch.setattr(notify.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x")))
    assert notify.send_notification("https://ntfy.example", "t", "title", "msg") is False


def test_prompt_uses_understood_text_and_keeps_raw_transcript():
    req = runner.Request("t", "Doctor yemeği ile konteyner farkı", understood="Docker image ile container farkı")
    prompt = runner.build_prompt(req)
    assert prompt.startswith("Docker image ile container farkı")
    assert 'Raw transcript: "Doctor yemeği ile konteyner farkı"' in prompt
    assert "Raw transcript" not in runner.build_prompt(runner.Request("t", "aynı", understood="aynı"))


def test_audio_without_router_reports_instead_of_running(monkeypatch, settings, store, sent):
    monkeypatch.setattr(runner.router, "route", lambda *a, **k: Decision(
        request="", route="task", project="sandbox", session="new", answer="", reason="",
        model="fallback", latency_ms=1))
    monkeypatch.setattr(runner, "run_claude", lambda *a: pytest.fail("nothing to run"))
    store.add_task("t5", "(voice recording)", False, False, False)
    runner.process(runner.Request("t5", "", audio=(b"x", "audio/mp4")), settings, store, "hook")
    assert sent[-1][2] == "⚠️ sayitship couldn't hear you"
    assert store.get_task("t5")["status"] == "error"
