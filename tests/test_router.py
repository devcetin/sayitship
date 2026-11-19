import json

import httpx

from sayitship import router

PROJECTS = [{"name": "sandbox", "description": "scratch"}, {"name": "blog", "description": "Astro blog"}]
NAMES = ["sandbox", "blog"]


def test_prompt_lists_projects_history_and_context():
    history = {"blog": {"last_text": "dark mode ekle", "updated": 1000.0}}
    prompt = router.build_prompt(
        "bir de footer'ı düzelt", PROJECTS, history, clipboard="err", has_image=True, now=1000 + 300
    )
    assert "- sandbox: scratch" in prompt
    assert 'last task 5 min ago: "dark mode ekle"' in prompt
    assert "clipboard: 'err'" in prompt and "screenshot is attached" in prompt
    assert prompt.rstrip().endswith("bir de footer'ı düzelt")


def test_parse_decision_valid():
    raw = json.dumps({"request": "Docker  image", "route": "task", "project": "blog", "session": "continue", "answer": "", "reason": "r"})
    assert router.parse_decision(raw, NAMES, "doker imaj") == {
        "request": "Docker image", "route": "task", "project": "blog", "session": "continue", "answer": "", "reason": "r",
    }


def test_parse_decision_repairs_bad_values():
    raw = json.dumps({"route": "dance", "project": "nope", "session": "?", "answer": "x"})
    d = router.parse_decision(raw, NAMES)
    assert (d["route"], d["project"], d["session"], d["answer"]) == ("task", "sandbox", "new", "")


def test_answer_without_text_becomes_task():
    raw = json.dumps({"route": "answer", "project": "sandbox", "session": "new", "answer": " ", "reason": ""})
    assert router.parse_decision(raw, NAMES)["route"] == "task"


def test_route_falls_through_models_then_to_fallback(monkeypatch):
    calls = []

    def fake_call(model, prompt, schema, key, timeout, audio=None):
        calls.append(model)
        if model == "bad":
            raise httpx.ConnectError("503")
        return json.dumps({"route": "answer", "project": "sandbox", "session": "new",
                           "answer": "404 = bulunamadı", "reason": "general"}), {"promptTokenCount": 10}

    monkeypatch.setattr(router, "call_gemini", fake_call)
    d = router.route("404 ne demek", PROJECTS, {}, "key", ["bad", "good"])
    assert calls == ["bad", "good"]
    assert (d.route, d.model, d.answer, d.input_tokens) == ("answer", "good", "404 = bulunamadı", 10)

    monkeypatch.setattr(router, "call_gemini", lambda *a: (_ for _ in ()).throw(httpx.ConnectError("x")))
    d = router.route("x", PROJECTS, {}, "key", ["bad"])
    assert (d.route, d.project, d.session, d.model) == ("task", "sandbox", "new", "fallback")


def test_route_without_api_key_uses_fallback():
    d = router.route("x", PROJECTS, {}, "", ["m"])
    assert d.model == "fallback" and d.route == "task"


def test_missing_request_falls_back_to_original_text():
    raw = json.dumps({"route": "task", "project": "blog", "session": "new", "answer": "", "reason": ""})
    assert router.parse_decision(raw, NAMES, "ham metin")["request"] == "ham metin"


def test_audio_prompt_asks_for_transcript_instead_of_text():
    prompt = router.build_prompt("", PROJECTS, {}, has_audio=True)
    assert "attached audio recording" in prompt and "raw dictation" not in prompt
    assert "- blog: Astro blog" in prompt  # project names help spell the transcript


def test_audio_is_sent_as_inline_data(monkeypatch):
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            body = {"request": "Docker image farkı", "route": "answer", "project": "sandbox",
                    "session": "new", "answer": "a", "reason": "r"}
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]}

    def fake_post(url, headers, json, timeout):
        seen["parts"], seen["timeout"] = json["contents"][0]["parts"], timeout
        return FakeResponse()

    monkeypatch.setattr(router.httpx, "post", fake_post)
    d = router.route("", PROJECTS, {}, "key", ["m"], audio=(b"abc", "audio/mp4"))
    assert seen["parts"][1] == {"inline_data": {"mime_type": "audio/mp4", "data": "YWJj"}}
    assert seen["timeout"] >= 30
    assert d.request == "Docker image farkı"
