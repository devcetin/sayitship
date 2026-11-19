import base64
import time

from sayitship import main

from .conftest import auth

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()


def test_missing_or_wrong_token_is_rejected(client):
    c, processed = client
    assert c.post("/task", json={"text": "hi"}).status_code == 401
    assert c.post("/task", json={"text": "hi"}, headers=auth("nope")).status_code == 401
    assert c.get("/tasks").status_code == 401
    assert processed == []


def test_empty_text_is_rejected(client):
    c, _ = client
    assert c.post("/task", json={"text": "   "}, headers=auth()).status_code == 422


def test_unknown_project_is_rejected(client):
    c, processed = client
    r = c.post("/task", json={"text": "hi", "project": "C:/Windows"}, headers=auth())
    assert r.status_code == 400
    assert processed == []


def test_valid_task_returns_202_and_is_recorded(client, store):
    c, processed = client
    r = c.post(
        "/task",
        json={"text": "README'yi düzelt", "clipboard": "Traceback ...", "url": "https://x.dev"},
        headers=auth(),
    )
    assert r.status_code == 202
    task_id = r.json()["id"]
    req = processed[0][0]
    assert (req.text, req.clipboard, req.url) == ("README'yi düzelt", "Traceback ...", "https://x.dev")
    row = c.get(f"/tasks/{task_id}", headers=auth()).json()
    assert row["status"] == "queued" and row["has_clipboard"] == 1 and row["has_url"] == 1
    assert c.get("/tasks", headers=auth()).json()[0]["id"] == task_id


def test_image_is_saved_to_inbox(client, settings):
    c, processed = client
    r = c.post("/task", json={"text": "ekrandaki gibi yap", "image": PNG}, headers=auth())
    assert r.status_code == 202
    path = processed[0][0].image_path
    assert path.parent == settings.data_dir / "inbox" and path.suffix == ".png" and path.exists()


def test_non_image_upload_is_rejected(client):
    c, _ = client
    bad = base64.b64encode(b"MZ this is an exe").decode()
    assert c.post("/task", json={"text": "x", "image": bad}, headers=auth()).status_code == 422


# ---- approvals ----------------------------------------------------------------------------

def hook_auth():
    return {"Authorization": f"Bearer {main.HOOK_TOKEN}"}


def create_approval(c, notifications):
    r = c.post("/internal/approvals", json={"tool": "Bash", "detail": "npm install"}, headers=hook_auth())
    assert r.status_code == 200
    approval_id = r.json()["id"]
    yes_url = notifications[-1][1]["actions"][0]["url"]
    return approval_id, yes_url.split("?key=")[1]


def test_internal_endpoints_need_hook_token_not_main_token(client):
    c, _ = client
    body = {"tool": "Bash", "detail": "rm -rf x"}
    assert c.post("/internal/approvals", json=body).status_code == 401
    assert c.post("/internal/approvals", json=body, headers=auth()).status_code == 401


def test_approval_flow_allow(client, notifications, settings):
    c, _ = client
    approval_id, key = create_approval(c, notifications)
    args, kwargs = notifications[-1]
    assert "npm install" in args[3]
    assert settings.token not in str(kwargs["actions"])  # main token never goes to ntfy
    assert c.get(f"/internal/approvals/{approval_id}", headers=hook_auth()).json()["decision"] is None
    assert c.post(f"/approvals/{approval_id}/allow?key={key}").status_code == 200
    assert c.get(f"/internal/approvals/{approval_id}", headers=hook_auth()).json()["decision"] == "allow"
    # the key works only once
    assert c.post(f"/approvals/{approval_id}/deny?key={key}").status_code == 409


def test_approval_rejects_wrong_key_and_expired(client, notifications, store):
    c, _ = client
    approval_id, key = create_approval(c, notifications)
    assert c.post(f"/approvals/{approval_id}/allow?key=wrong").status_code == 403
    assert c.post(f"/approvals/{approval_id}/maybe?key={key}").status_code == 404
    store._exec("UPDATE approvals SET created = ?", (time.time() - 3600,))
    assert c.post(f"/approvals/{approval_id}/allow?key={key}").status_code == 410


M4A = base64.b64encode(b"\x00\x00\x00\x20ftypM4A " + b"0" * 32).decode()


def test_audio_without_text_is_accepted(client, settings):
    c, processed = client
    object.__setattr__(settings, "gemini_api_key", "k")
    r = c.post("/task", json={"audio": M4A}, headers=auth())
    assert r.status_code == 202
    req = processed[0][0]
    assert req.text == "" and req.audio[1] == "audio/mp4" and req.audio[0].startswith(b"\x00\x00\x00\x20ftyp")


def test_audio_needs_gemini_key_and_known_format(client, settings):
    c, processed = client
    assert c.post("/task", json={"audio": M4A}, headers=auth()).status_code == 422  # no key
    object.__setattr__(settings, "gemini_api_key", "k")
    bad = base64.b64encode(b"not audio at all").decode()
    assert c.post("/task", json={"audio": bad}, headers=auth()).status_code == 422
    assert c.post("/task", json={}, headers=auth()).status_code == 422  # neither text nor audio
    assert processed == []


def test_audio_mime_detection():
    assert main.audio_mime(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "audio/wav"
    assert main.audio_mime(b"ID3\x04") == "audio/mp3"
    assert main.audio_mime(b"OggS\x00") == "audio/ogg"
    assert main.audio_mime(b"RIFF\x00\x00\x00\x00WEBP") is None


def test_unfinished_tasks_are_marked_interrupted_on_restart(store):
    store.add_task("old", "x", False, False, False)
    store.update_task("old", status="running")
    store.add_task("done", "y", False, False, False)
    store.update_task("done", status="done")
    assert store.mark_interrupted() == 1
    assert store.get_task("old")["status"] == "interrupted"
    assert store.get_task("done")["status"] == "done"
