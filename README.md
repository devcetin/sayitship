# sayitship

**Press one button. Say it. Your coding agent ships it.**

Press the iPhone Action Button, speak a request and put the phone back in your pocket.
A small router decides what to do with it: answer a quick question on the spot, or hand the
work to Claude Code in the right project, continuing the last session when you are clearly
following up. You get the result as a notification. Risky commands ask your phone first.
You never open an app.

sayitship is not another remote-control app for coding agents. It is a voice entry layer
that sits in front of the tools you already use: iOS Shortcuts, Tailscale, Claude Code and ntfy.

## How it works

```
 iPhone                                   your PC (reachable only over Tailscale)
┌─────────────────────┐   POST /task    ┌──────────────────────────────────────────────┐
│ Action Button       │ ──────────────▶ │ FastAPI  → 202 Accepted right away            │
│ Shortcut: record    │   Bearer token  │    │                                         │
│ (+ clipboard,       │                 │    ▼  background                             │
│    screenshot, link)│                 │ Router (Gemini Flash-Lite): transcribe+route  │
└─────────────────────┘                 │    ├─ answer ─────────────▶ ntfy: ⚡ answer    │
          ▲                             │    └─ task: project + new/continue           │
          │ notification                │          ▼                                   │
          │ (Yes/No buttons for         │    claude -p  (in that project's folder,     │
          │  risky commands)            │               --resume last session)         │
┌─────────┴───────────┐                 │          │  Bash call? → hook → phone Yes/No │
│ ntfy app            │ ◀────────────── │          ▼                                   │
└─────────────────────┘                 │    one-sentence summary → ntfy: 🛠 project    │
                                        └──────────────────────────────────────────────┘
```

### Walkthrough: one request, file by file

**1. The door: [`main.py`](sayitship/main.py).** The Shortcut posts to `/task` with a Bearer
token. FastAPI checks the token first (`check_token`, compared with `secrets.compare_digest` so
response time leaks nothing), then validates the body: text or an audio recording, optional
clipboard, link and screenshot, and at most a project *name*. A client can never send a folder
path. The request gets an id, is written to SQLite as `queued`, handed to a background task, and
the phone gets `202 Accepted` at once. That last part is the key design choice: a Claude Code
run can take minutes, and an iOS Shortcut cannot wait that long, so the flow is asynchronous and
the result comes back later as a notification.

**2. The decision: [`router.py`](sayitship/router.py).** One call to Gemini Flash-Lite, with a
JSON schema so the answer is always machine-readable, decides everything at once:

- `request`: what you meant. For audio, the transcript (your project names are in the prompt, so
  they come out spelled right). For dictated text, a repaired version ("pay torç notbuk" →
  "PyTorch notebook").
- `route`: `answer` for a general question the model can answer itself, `task` for anything that
  needs files, commands or live data.
- `project` and `session`: which folder, and whether to continue the last Claude session there
  (project active in the last 30 minutes, or you point at the last task) or start fresh.

Every value is validated (`parse_decision`): an unknown project becomes the default, an empty
answer becomes a task. If a model fails it tries the next one in `ROUTER_MODELS`; if all fail, a
text request still runs as a new task in the default project, so a flaky API never loses work.

**3. The work: [`runner.py`](sayitship/runner.py).** An `answer` goes straight to ntfy and Claude
never starts. A `task` takes that project's lock (one run per project at a time; a second request
waits its turn), then starts `claude -p` in the project folder with:

- the request on stdin (no shell quoting problems with Turkish letters),
- `--resume <session id>` when continuing,
- a generated settings file holding the approval hook and permission rules,
- an environment without the server's secrets.

Claude's JSON output gives the session id (saved for next time) and the reply. Claude is asked to
end with one plain paragraph that answers the question or says what it did, and that paragraph
becomes the notification.

**4. The guard: [`hook.py`](sayitship/hook.py).** Claude Code calls this script before every shell
command. Shell access is not in Claude's allowed tools, so only this hook can grant it.
Read-only commands (`git status`, `ls`, …) pass. Anything else (chaining, redirection, flags
that run programs or write files, anything touching sayitship's own files) goes to the server,
which sends a Yes/No notification. The hook waits for your tap. Any error, timeout or crash ends
in "deny".

**5. The helpers.**

- [`notify.py`](sayitship/notify.py) publishes to ntfy as JSON, because HTTP headers cannot carry
  Turkish letters.
- [`db.py`](sayitship/db.py) is the SQLite task history, the approvals and the last session per
  project.
- [`config.py`](sayitship/config.py) reads `.env` and `projects.json` and refuses to start on bad
  values.
- [`evaluate.py`](sayitship/evaluate.py) runs the router on the public test sets.

## Router eval

The router is the part that can be wrong, so it is measured. `eval/dataset.jsonl` is a public
test set of spoken requests in Turkish and English, each with the right route, project and
session, against a fixed set of five example projects (`eval/projects.json`).

```powershell
python -m sayitship.evaluate --models gemini-3.5-flash-lite,gemini-flash-lite-latest
```

Two sets, both public:

- `eval/dataset.jsonl`, 90 cases. The routing rules and labels were refined while looking at
  results on this set, so it is **in-sample**.
- `eval/holdout.jsonl`, 20 cases written after the rules were frozen and run once
  (`--dataset holdout`). Small, but never tuned on.

| set | model | exact | route | project | session | p50 | cost / 1000 requests |
|---|---|---|---|---|---|---|---|
| dataset (90) | gemini-3.5-flash-lite | **97%** | 100% | 97% | 98% | 2.6 s | $0.44 |
| dataset (90) | gemini-flash-lite-latest | 94% | 99% | 97% | 97% | 1.6 s | – |
| holdout (20) | gemini-3.5-flash-lite | **100%** | 100% | 100% | 100% | 1.3 s | $0.44 |

Full reports: [eval/results.md](eval/results.md), [eval/results-holdout.md](eval/results-holdout.md);
per-case output in `eval/results/`.

Notes:

- **Rules before models.** A first run scored 80% on sessions, mostly because the labels
  themselves were inconsistent. Writing the rule down (continue if the project was active in the
  last 30 minutes or the request points at the last task; a spoken "fresh start" always wins)
  fixed both the labels and the prompt.
- **Dictation repair on text.** "pay torç notbukuna batç normalizasyon ekle" becomes
  "PyTorch notebook'una batch normalization ekle"; all 10 noisy cases were routed correctly.
- **The eval covers the text path.** The recommended Shortcut sends audio, which the router
  transcribes itself; that path is tested by hand, not yet measured by the eval.
- **The free API is often overloaded.** Many calls got `503`, so the server tries the next model
  in `ROUTER_MODELS` and, if all fail, falls back to running the request as a new task.

## Quick start (Windows)

You need Python 3.12+, [Claude Code](https://claude.com/claude-code) signed in (`claude` on your
PATH), [Tailscale](https://tailscale.com) on your PC and iPhone, the [ntfy](https://ntfy.sh) app
on your iPhone and, for the router, a [Gemini API key](https://aistudio.google.com/apikey).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                    # token, ntfy topic, Tailscale IP
copy projects.example.json projects.json  # your project folders, with one-line descriptions
python -m sayitship
```

Set `GEMINI_API_KEY` in `.env` or as a user environment variable. Without it, every request
runs as a new task in the first project.

Then build the Shortcuts: [docs/shortcut.md](docs/shortcut.md).

To start the server automatically when you log in (Windows Task Scheduler; logs go to
`data\sayitship.log`):

```powershell
.\scripts\install-autostart.ps1
```

## API

| method | path | auth | what it does |
|---|---|---|---|
| `POST` | `/task` | token | queue a request; returns `202` and an id |
| `GET` | `/tasks` | token | recent requests with the router's decision and the result |
| `GET` | `/tasks/{id}` | token | one request |
| `POST` | `/approvals/{id}/allow\|deny?key=…` | one-time key | pressed from the notification |
| `GET` | `/health` | none | liveness |

`POST /task` body: `audio` (base64 recording) or `text` (dictation), plus optional `clipboard`,
`url`, `image` (base64) and `project`.

### Why audio instead of Apple dictation

iOS dictation in Turkish turns English technical words into Turkish-sounding nonsense:
"Bash ile pip list komutunu çalıştır" arrived as "Beş ile Bitlis komutanı çalıştır". So the
Shortcut sends the recording, and the router transcribes it in the same Gemini call that routes
it, with the user's project names and a developer vocabulary in the prompt. Text input still
works; the router then tries to repair misheard terms from the text alone.

## Security

Your voice can run code on your computer, so the defaults are strict:

- **Private network only.** The server listens on your Tailscale address, not on the internet.
- **Token on every request.** Compared in constant time.
- **Project allowlist.** Claude Code runs only in folders listed in `projects.json`; a request
  can name a project, never a path.
- **Approval for commands.** Claude may read, edit and search the web on its own. Shell access
  is not in Claude's allowed tools at all: every command goes through a hook. Read-only commands
  (`git status`, `ls`, …) are allowed by the hook; anything else sends you a Yes/No notification
  and waits. No answer in 5 minutes means No. If the hook crashes or cannot start, Claude Code
  falls back to its own default, which in headless mode is No. Both cases were tested with a
  real `claude -p` run.
- **No secrets in notifications.** Yes/No buttons carry a one-time key for that one question,
  stored only as a hash, valid once and only for a few minutes. The main token never goes to ntfy.
- **The agent cannot touch sayitship itself.** Permission rules generated for every run deny
  Claude editing the sayitship folder (so it cannot rewrite its own approval hook) and reading
  `.env`, the database and logs. Shell commands that mention them always need your approval.
  The Claude process also does not inherit the server token, the ntfy topic or the Gemini key.
  Don't list the sayitship folder itself in `projects.json`.
- **Know the limits.** `acceptEdits` lets Claude change files inside the project without asking,
  and `Read` is not limited to the project folder. Use git, and keep projects you can't afford to
  break out of `projects.json`.

## Roadmap

- [x] v0.1: voice → background task → notification
- [x] Router: answer quick questions directly, pick the project, continue or start a session
- [x] Context: attach your clipboard, latest screenshot or a shared link
- [x] Approvals: Yes/No buttons before risky commands
- [x] Router eval: a public test set with accuracy, latency and cost

## Development

```powershell
python -m pytest
```

## License

MIT
