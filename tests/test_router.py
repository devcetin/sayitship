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
    raw = json.dumps({"route": "task", "project": "blog", "session": "continue", "answer": "", "reason": "r"})
    assert router.parse_decision(raw, NAMES) == {
        "route": "task", "project": "blog", "session": "continue", "answer": "", "reason": "r",
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

    def fake_call(model, prompt, schema, key, timeout):
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
