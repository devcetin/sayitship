"""Router: one small LLM call decides what to do with a spoken request.

It answers three questions at once:
  route   - "answer" (a general question the router answers itself) or "task" (Claude Code does work)
  project - which project folder the task belongs to
  session - "continue" the last Claude session in that project, or start a "new" one
"""

import base64
import json
import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("sayitship")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

INSTRUCTIONS = """You are the router of a voice assistant for a software developer.
The user pressed a button on their phone and spoke a request. Decide how to handle it.

{request_rules}

route:
- "answer": a general-knowledge or explanation question you can answer well from your own
  knowledge, with no need to look at files, run anything or check live data.
  Then write the answer in "answer": at most 2 short sentences, in the user's language.
- "task": anything that needs work on the computer: reading, creating or changing files or code,
  running commands, looking things up on the web, or live information (weather, news, prices,
  today's date). When unsure, choose "task".

project: for a task, the project it belongs to, chosen from the list below by name and
description.
- Requests that are not about any project's code (notes, lists, reminders, general look-ups,
  live information, small throwaway scripts) go to the first project.
- A request about code that names no project and fits none by description goes to the
  project whose last task was less than 30 minutes ago, if there is one; otherwise the first.

session:
- "new" if the user asks for a fresh start ("new session", "yeni oturum", "baştan başla").
- "continue" if the chosen project's last task was less than 30 minutes ago.
- "continue" if the request clearly refers to the project's last task ("the fix you made",
  "az önce eklediğin", "onu geri al"), however long ago it was.
- "new" otherwise.

reason: a few words on why.

Projects (the first one is the default):
{projects}

Context sent with the request:
{context}

{request_section}
"""

TEXT_RULES = """request: the text comes from phone dictation, often in Turkish. Dictation mangles English
technical words into similar-sounding Turkish or English words (for example "Doctor yemeği"
or "doker imaj" for "Docker image", "pull rikuest" for "pull request", "riyekt" for "React").
First rewrite the request as the user most likely meant it, in the user's language, with
technical terms spelled correctly. Change nothing else. Base every decision below on this
rewritten request."""

AUDIO_RULES = """request: the request is in the attached audio recording, usually Turkish with English
technical terms. Transcribe it word for word in the language spoken. Spell technical terms,
library names and the project names listed below the way they are normally written
(for example "Docker image", "pull request", "FastAPI"), not as they sound in Turkish.
Base every decision below on this transcript."""


@dataclass
class Decision:
    request: str  # the request as the router understood it (dictation errors fixed)
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
    has_audio: bool = False,
) -> str:
    """projects: [{"name", "description"}]; history: name -> {"last_text", "updated"}.

    With has_audio the request itself is in an attached recording, and text is empty.
    """
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
    if has_audio:
        rules, section = AUDIO_RULES, "Spoken request: in the attached audio recording."
    else:
        rules, section = TEXT_RULES, f"Spoken request (raw dictation):\n{text}"
    return INSTRUCTIONS.format(
        request_rules=rules,
        projects="\n".join(lines),
        context="\n".join(context) or "(none)",
        request_section=section,
    )


def response_schema(project_names: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "request": {"type": "STRING"},
            "route": {"type": "STRING", "enum": ["answer", "task"]},
            "project": {"type": "STRING", "enum": project_names},
            "session": {"type": "STRING", "enum": ["continue", "new"]},
            "answer": {"type": "STRING"},
            "reason": {"type": "STRING"},
        },
        "required": ["request", "route", "project", "session", "answer", "reason"],
        "propertyOrdering": ["request", "reason", "route", "project", "session", "answer"],
    }


def parse_decision(raw: str, project_names: list[str], original: str = "") -> dict:
    """Validate the model's JSON. Invalid parts fall back to safe values."""
    data = json.loads(raw)
    route = data.get("route") if data.get("route") in ("answer", "task") else "task"
    project = data.get("project") if data.get("project") in project_names else project_names[0]
    session = data.get("session") if data.get("session") in ("continue", "new") else "new"
    answer = str(data.get("answer") or "").strip()
    if route == "answer" and not answer:
        route = "task"  # nothing to say, so let Claude handle it
    request = " ".join(str(data.get("request") or "").split())[:4000] or original
    return {
        "request": request,
        "route": route,
        "project": project,
        "session": session,
        "answer": answer if route == "answer" else "",
        "reason": str(data.get("reason") or "")[:200],
    }


def call_gemini(
    model: str,
    prompt: str,
    schema: dict,
    api_key: str,
    timeout: float,
    audio: tuple[bytes, str] | None = None,
) -> tuple[str, dict]:
    parts: list[dict] = [{"text": prompt}]
    if audio:
        data, mime = audio
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    response = httpx.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": api_key},
        json={
            "contents": [{"parts": parts}],
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
    audio: tuple[bytes, str] | None = None,
) -> Decision:
    """Try each model in order; if all fail, fall back to a new task in the default project.

    audio: (bytes, mime type) of a voice recording; the model transcribes it into "request".
    """
    names = [p["name"] for p in projects]
    prompt = build_prompt(
        text, projects, history, clipboard, url, has_image, has_audio=audio is not None
    )
    schema = response_schema(names)
    if audio:
        timeout = max(timeout, 30)  # transcribing takes longer than reading text
    start = time.perf_counter()
    if api_key:
        for model in models:
            try:
                raw, usage = call_gemini(model, prompt, schema, api_key, timeout, audio)
                parsed = parse_decision(raw, names, text)
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
        request=text,
        route="task",
        project=names[0],
        session="new",
        answer="",
        reason="router unavailable",
        model="fallback",
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
