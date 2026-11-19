"""Router eval: run the public test set against one or more models and report the numbers.

    python -m sayitship.evaluate --models gemini-3.5-flash-lite,gemini-flash-lite-latest

Writes eval/results/<model>.jsonl (one line per case) and eval/results.md (summary table).
"""

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from . import router
from .config import REPO_ROOT, user_env

EVAL_DIR = REPO_ROOT / "eval"
NOW = 1_800_000_000.0  # fixed clock, so "minutes ago" in the prompt is the same on every run


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_fixture(path: Path) -> tuple[list[dict], dict[str, dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    history = {
        name: {"last_text": h["last_text"], "updated": NOW - h["minutes_ago"] * 60}
        for name, h in data["history"].items()
    }
    return data["projects"], history


def score(expected: dict, got: dict | None) -> dict:
    """Which parts of the decision were right. Project and session only count for tasks."""
    if got is None:
        return {"route": False, "project": None, "session": None, "exact": False}
    route_ok = got["route"] == expected["route"]
    if expected["route"] == "task":
        project_ok = route_ok and got["project"] == expected["project"]
        session_ok = route_ok and got["session"] == expected["session"]
        return {"route": route_ok, "project": project_ok, "session": session_ok,
                "exact": route_ok and project_ok and session_ok}
    return {"route": route_ok, "project": None, "session": None, "exact": route_ok}


def call_with_retry(model: str, prompt: str, schema: dict, api_key: str, retries: int = 3):
    for attempt in range(retries + 1):
        try:
            return router.call_gemini(model, prompt, schema, api_key, timeout=30)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 503) and attempt < retries:
                time.sleep(10 * (attempt + 1))
                continue
            raise


def run_model(model: str, cases: list[dict], projects: list[dict], history: dict, api_key: str, delay: float) -> list[dict]:
    names = [p["name"] for p in projects]
    schema = router.response_schema(names)
    rows = []
    for i, case in enumerate(cases, 1):
        prompt = router.build_prompt(
            case["text"], projects, history,
            clipboard=case.get("clipboard", ""), url=case.get("url", ""),
            has_image=bool(case.get("image")), now=NOW,
        )
        start = time.perf_counter()
        got, usage, error = None, {}, ""
        try:
            raw, usage = call_with_retry(model, prompt, schema, api_key)
            got = router.parse_decision(raw, names)
        except Exception as exc:  # record and keep going
            error = f"{type(exc).__name__}: {str(exc)[:120]}"
        latency = int((time.perf_counter() - start) * 1000)
        row = {
            "id": case["id"], "text": case["text"], "expected": case["expected"], "got": got,
            "score": score(case["expected"], got), "latency_ms": latency, "error": error,
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
        }
        rows.append(row)
        mark = "ok " if row["score"]["exact"] else "ERR" if error else "x  "
        print(f"[{model}] {i:>3}/{len(cases)} {mark} {case['id']} {latency} ms")
        time.sleep(delay)
    return rows


def _pct(values: list[bool | None]) -> str:
    counted = [v for v in values if v is not None]
    return f"{100 * sum(counted) / len(counted):.0f}%" if counted else "-"


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def summarize(model: str, rows: list[dict], prices: dict) -> dict:
    ok_rows = [r for r in rows if not r["error"]]
    latencies = [r["latency_ms"] for r in ok_rows]
    price = prices.get(model)
    cost = None
    if price and ok_rows:
        per_call = statistics.mean(
            r["input_tokens"] * price["input"] / 1e6 + r["output_tokens"] * price["output"] / 1e6
            for r in ok_rows
        )
        cost = per_call * 1000
    return {
        "model": model,
        "cases": len(rows),
        "errors": len(rows) - len(ok_rows),
        "exact": _pct([r["score"]["exact"] for r in rows]),
        "route": _pct([r["score"]["route"] for r in rows]),
        "project": _pct([r["score"]["project"] for r in rows]),
        "session": _pct([r["score"]["session"] for r in rows]),
        "dictation": _pct([r["score"]["exact"] for r in rows if r.get("id", "").startswith("n")]),
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "cost_per_1000": f"${cost:.3f}" if cost is not None else "-",
    }


def write_report(summaries: list[dict], path: Path, cases: int) -> None:
    header = "| model | exact | route | project | session | noisy dictation | p50 | p95 | cost / 1000 requests | errors |"
    lines = [
        "# Router eval results",
        "",
        f"{cases} cases from `eval/dataset.jsonl`, run on {time.strftime('%Y-%m-%d')}.",
        "",
        header,
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['model']} | {s['exact']} | {s['route']} | {s['project']} | {s['session']} | {s['dictation']} "
            f"| {s['p50_ms']} ms | {s['p95_ms']} ms | {s['cost_per_1000']} | {s['errors']} |"
        )
    lines += [
        "",
        "- **exact**: route, project and session all right.",
        "- **project / session**: scored only on cases where the right answer is a task.",
        "- **noisy dictation**: exact score on the `n*` cases, where speech-to-text mangled technical words.",
        "- Latency is measured from this PC, including network; errors are excluded from latency and cost.",
        "- p95 includes waiting out the API's `503 overloaded` replies (retried after 10 s, 20 s, 30 s);",
        "  p50 is closer to a normal call. In real use the server tries the next model instead of waiting.",
        "- A model with errors could not be scored on those cases (the API kept answering 503).",
        "- Cost uses token counts reported by the API and prices in `eval/prices.json`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", default=os.environ.get("ROUTER_MODELS", "gemini-3.5-flash-lite"))
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between calls (free tier limits)")
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases")
    parser.add_argument("--report", action="store_true", help="rebuild results.md from saved results")
    args = parser.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    prices_file = EVAL_DIR / "prices.json"
    prices = json.loads(prices_file.read_text(encoding="utf-8")) if prices_file.exists() else {}

    if args.report:
        summaries, cases = [], 0
        for model in models:
            rows = load_cases(EVAL_DIR / "results" / f"{model}.jsonl")
            cases = len(rows)
            summaries.append(summarize(model, rows, prices))
        write_report(summaries, EVAL_DIR / "results.md", cases)
        print(f"wrote {EVAL_DIR / 'results.md'}")
        return

    api_key = user_env("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set.")
    cases = load_cases(EVAL_DIR / "dataset.jsonl")
    if args.limit:
        cases = cases[: args.limit]
    projects, history = load_fixture(EVAL_DIR / "projects.json")

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    summaries = []
    for model in models:
        rows = run_model(model, cases, projects, history, api_key, args.delay)
        with (out_dir / f"{model}.jsonl").open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        summaries.append(summarize(model, rows, prices))
        print(summaries[-1])
    write_report(summaries, EVAL_DIR / "results.md", len(cases))
    print(f"wrote {EVAL_DIR / 'results.md'}")


if __name__ == "__main__":
    main()
