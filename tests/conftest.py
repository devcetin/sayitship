import pytest
from fastapi.testclient import TestClient

from sayitship import main
from sayitship.config import Project, Settings
from sayitship.db import Store

TOKEN = "test-token-1234567890"


@pytest.fixture
def settings(tmp_path):
    work = tmp_path / "work"
    other = tmp_path / "other"
    work.mkdir()
    other.mkdir()
    return Settings(
        token=TOKEN,
        ntfy_server="https://ntfy.example",
        ntfy_topic="topic",
        projects={
            "sandbox": Project("sandbox", work, "scratch files"),
            "blog": Project("blog", other, "Astro blog"),
        },
        public_url="http://100.1.2.3:8787",
        data_dir=tmp_path,
        approval_timeout=5,
        gemini_api_key="",
        router_models=["m1"],
        claude_args=[],
    )


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture
def notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "send_notification", lambda *a, **k: sent.append((a, k)) or True)
    return sent


@pytest.fixture
def client(settings, store, monkeypatch):
    processed = []
    main.app.dependency_overrides[main.get_settings] = lambda: settings
    main.app.dependency_overrides[main.get_store] = lambda: store
    monkeypatch.setattr(main, "process", lambda *args: processed.append(args))
    yield TestClient(main.app), processed
    main.app.dependency_overrides.clear()


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}
