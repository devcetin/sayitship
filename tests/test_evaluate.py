from sayitship import evaluate


def test_dataset_and_fixture_are_consistent():
    cases = evaluate.load_cases(evaluate.EVAL_DIR / "dataset.jsonl")
    projects, history = evaluate.load_fixture(evaluate.EVAL_DIR / "projects.json")
    names = {p["name"] for p in projects}
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) >= 60
    for c in cases:
        exp = c["expected"]
        assert exp["route"] in ("answer", "task")
        if exp["route"] == "task":
            assert exp["project"] in names and exp["session"] in ("continue", "new")
            if exp["session"] == "continue":
                assert exp["project"] in history, c["id"]


def test_score_rules():
    task = {"route": "task", "project": "blog", "session": "new"}
    assert evaluate.score(task, dict(task))["exact"]
    wrong_project = evaluate.score(task, {"route": "task", "project": "sandbox", "session": "new"})
    assert wrong_project == {"route": True, "project": False, "session": True, "exact": False}
    answer = {"route": "answer"}
    assert evaluate.score(answer, {"route": "answer", "project": "x", "session": "new"})["exact"]
    assert evaluate.score(answer, None)["exact"] is False


def test_summarize_percentages_latency_and_cost():
    rows = [
        {"score": {"exact": True, "route": True, "project": True, "session": True}, "latency_ms": 100,
         "error": "", "input_tokens": 1000, "output_tokens": 100},
        {"score": {"exact": False, "route": True, "project": False, "session": True}, "latency_ms": 300,
         "error": "", "input_tokens": 1000, "output_tokens": 100},
        {"score": {"exact": False, "route": False, "project": None, "session": None}, "latency_ms": 9,
         "error": "HTTPError", "input_tokens": 0, "output_tokens": 0},
    ]
    s = evaluate.summarize("m", rows, {"m": {"input": 0.1, "output": 0.4}})
    assert (s["exact"], s["route"], s["project"], s["errors"]) == ("33%", "67%", "50%", 1)
    assert s["p50_ms"] in (100, 300) and s["p95_ms"] == 300
    assert s["cost_per_1000"] == "$0.140"  # (1000*0.1 + 100*0.4) / 1e6 * 1000
