"""Router: one small LLM call decides what to do with a spoken request.

It answers three questions at once:
  route   - "answer" (a general question the router answers itself) or "task" (Claude Code does work)
  project - which project folder the task belongs to
  session - "continue" the last Claude session in that project, or start a "new" one
"""

import json
import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("sayitship")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

INSTRUCTIONS = """You are the router of a voice assistant for a software developer.
The user pressed a button on their phone and spoke a request. Decide how to handle it.

route:
- "answer": a general-knowledge or explanation question you can answer well from your own
  knowledge, with no need to look at files, run anything or check live data.
  Then write the answer in "answer": at most 2 short sentences, in the user's language.
- "task": anything that needs work on the computer: reading, creating or changing files or code,
  running commands, looking things up on the web, or live information (weather, news, prices,
  today's date). When unsure, choose "task".

project: for a task, the project it belongs to, chosen from the list below by name and
description. If the request names no project and fits none clearly, use the first one.

session:
- "continue": the request builds on the project's last task (it says things like "also",
  "now", "that file", "undo it", "az önceki", "bir de", "onu", "şimdi de") and the last task
  was recent.
- "new": everything else.

reason: a few words on why.

Projects (the first one is the default):
{projects}

Context sent with the request:
{context}

Spoken request:
{text}
"""


@dataclass
class Decision:
    route: str  # "answer" | "task"
    project: str
    session: str  # "continue" | "new"
    answer: str
    reason: str
    model: str  # model that decided, or "fallback"
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"


def build_prompt(
    text: str,
    projects: list[dict],
    history: dict[str, dict],
    clipboard: str = "",
    url: str = "",
    has_image: bool = False,
    now: float | None = None,
) -> str:
    """projects: [{"name", "description"}]; history: name -> {"last_text", "updated"}."""
    now = time.time() if now is None else now
    lines = []
    for p in projects:
        line = f"- {p['name']}: {p.get('description') or '(no description)'}"
        last = history.get(p["name"])
        if last:
            line += f' | last task {_ago(now - last["updated"])}: "{last["last_text"][:120]}"'
        lines.append(line)
    context = []
    if clipboard:
        context.append(f"clipboard: {clipboard[:300]!r}")
    if url:
        context.append(f"shared link: {url}")
    if has_image:
        context.append("a screenshot is attached")
    return INSTRUCTIONS.format(
        projects="\n".join(lines),
        context="\n".join(context) or "(none)",
        text=text,
    )


def response_schema(project_names: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "route": {"type": "STRING", "enum": ["answer", "task"]},
            "project": {"type": "STRING", "enum": project_names},
            "session": {"type": "STRING", "enum": ["continue", "new"]},
            "answer": {"type": "STRING"},
            "reason": {"type": "STRING"},
        },
        "required": ["route", "project", "session", "answer", "reason"],
        "propertyOrdering": ["reason", "route", "project", "session", "answer"],
    }


def parse_decision(raw: str, project_names: list[str]) -> dict:
    """Validate the model's JSON. Invalid parts fall back to safe values."""
    data = json.loads(raw)
    route = data.get("route") if data.get("route") in ("answer", "task") else "task"
    project = data.get("project") if data.get("project") in project_names else project_names[0]
    session = data.get("session") if data.get("session") in ("continue", "new") else "new"
    answer = str(data.get("answer") or "").strip()
    if route == "answer" and not answer:
        route = "task"  # nothing to say, so let Claude handle it
    return {
        "route": route,
        "project": project,
        "session": session,
        "answer": answer if route == "answer" else "",
        "reason": str(data.get("reason") or "")[:200],
    }


def call_gemini(model: str, prompt: str, schema: dict, api_key: str, timeout: float) -> tuple[str, dict]:
    response = httpx.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    return text, body.get("usageMetadata", {})


def route(
    text: str,
    projects: list[dict],
    history: dict[str, dict],
    api_key: str,
    models: list[str],
    clipboard: str = "",
    url: str = "",
    has_image: bool = False,
    timeout: float = 15,
) -> Decision:
    """Try each model in order; if all fail, fall back to a new task in the default project."""
    names = [p["name"] for p in projects]
    prompt = build_prompt(text, projects, history, clipboard, url, has_image)
    schema = response_schema(names)
    start = time.perf_counter()
    if api_key:
        for model in models:
            try:
                raw, usage = call_gemini(model, prompt, schema, api_key, timeout)
                parsed = parse_decision(raw, names)
                return Decision(
                    **parsed,
                    model=model,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    input_tokens=usage.get("promptTokenCount", 0),
                    output_tokens=usage.get("candidatesTokenCount", 0)
                    + usage.get("thoughtsTokenCount", 0),
                )
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                log.warning("router model %s failed: %s", model, str(exc)[:200])
    return Decision(
        route="task",
        project=names[0],
        session="new",
        answer="",
        reason="router unavailable",
        model="fallback",
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
