import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sayitship import main, notify, runner
from sayitship.config import Settings, parse_workdirs

TOKEN = "test-token-1234567890"


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(
        token=TOKEN,
        ntfy_server="https://ntfy.example",
        ntfy_topic="topic",
        workdirs={"sandbox": tmp_path},
        task_timeout=60,
        claude_args=[],
    )
    calls = []
    main.app.dependency_overrides[main.get_settings] = lambda: settings
    monkeypatch.setattr(main, "run_task", lambda *args: calls.append(args))
    yield TestClient(main.app), calls
    main.app.dependency_overrides.clear()


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_missing_token_is_rejected(client):
    c, calls = client
    assert c.post("/task", json={"text": "hi"}).status_code == 401
    assert calls == []


def test_wrong_token_is_rejected(client):
    c, calls = client
    assert c.post("/task", json={"text": "hi"}, headers=auth("nope")).status_code == 401
    assert calls == []


def test_empty_text_is_rejected(client):
    c, _ = client
    assert c.post("/task", json={"text": "   "}, headers=auth()).status_code == 422


def test_unknown_workdir_is_rejected(client):
    c, calls = client
    r = c.post("/task", json={"text": "hi", "workdir": "C:/Windows"}, headers=auth())
    assert r.status_code == 400
    assert calls == []


def test_valid_task_returns_202_and_runs_in_background(client, tmp_path):
    c, calls = client
    r = c.post("/task", json={"text": "README'yi düzelt"}, headers=auth())
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    assert len(calls) == 1
    assert calls[0][1] == "README'yi düzelt"
    assert calls[0][2] == tmp_path


def test_parse_workdirs_keeps_order(tmp_path):
    dirs = parse_workdirs(f"a={tmp_path};b={tmp_path}")
    assert list(dirs) == ["a", "b"]
    with pytest.raises(ValueError):
        parse_workdirs("no-equals-sign")


def test_extract_summary_takes_last_line():
    out = json.dumps({"result": "Did things.\n\nREADME güncellendi.", "is_error": False})
    assert runner.extract_summary(out) == "README güncellendi."
    assert runner.extract_summary("not json").startswith("Done")
    assert runner.extract_summary(json.dumps({"result": "boom", "is_error": True})) == "Error: boom"


def test_child_env_drops_parent_claude_vars(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "x")
    monkeypatch.setenv("PATH_TEST", "keep")
    env = runner.child_env()
    assert "CLAUDECODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env
    assert env["PATH_TEST"] == "keep"


def test_failed_notification_is_swallowed(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(notify.httpx, "post", boom)
    assert notify.send_notification("https://ntfy.example", "t", "title", "msg") is False
