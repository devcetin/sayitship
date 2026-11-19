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
│ Shortcut: dictate   │   Bearer token  │    │                                         │
│ (+ clipboard,       │                 │    ▼  background                             │
│    screenshot, link)│                 │ Router (Gemini Flash-Lite, ~1.5–4 s)          │
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

> A plain-language walkthrough of the code is coming in the owner's own words.

## Router eval

The router is the part that can be wrong, so it is measured. `eval/dataset.jsonl` is a public
test set of spoken requests in Turkish and English, each with the right route, project and
session, against a fixed set of five example projects (`eval/projects.json`).

```powershell
python -m sayitship.evaluate --models gemini-3.5-flash-lite,gemini-flash-lite-latest
```

Latest results: [eval/results.md](eval/results.md).

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

To start the server automatically when you log in:

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

`POST /task` body: `text` (required), `clipboard`, `url`, `image` (base64), `project`.

## Security

Your voice can run code on your computer, so the defaults are strict:

- **Private network only.** The server listens on your Tailscale address, not on the internet.
- **Token on every request.** Compared in constant time.
- **Project allowlist.** Claude Code runs only in folders listed in `projects.json`; a request
  can name a project, never a path.
- **Approval for commands.** Claude may read, edit, search the web and run read-only commands
  (`git status`, `ls`, …) on its own. Any other shell command goes through a hook that sends you a
  Yes/No notification and waits. No answer in 5 minutes means No. If the approval system fails,
  the answer is No.
- **No secrets in notifications.** Yes/No buttons carry a one-time key for that one question,
  stored only as a hash, valid once and only for a few minutes. The main token never goes to ntfy.
- **Secrets stay out of the agent.** The Claude process does not inherit the server token, the
  ntfy topic or the Gemini key.
- **Know the limits.** `acceptEdits` lets Claude change files inside the project without asking.
  Use git, and keep projects you can't afford to break out of `projects.json`.

## Roadmap

- [x] v0.1: voice → background task → notification
- [x] Router: answer quick questions directly, pick the project, continue or start a session
- [x] Context: attach your clipboard, latest screenshot or a shared link
- [x] Approvals: Yes/No buttons before risky commands
- [x] Router eval: a public test set with accuracy, latency and cost
- [ ] Demo video

## Development

```powershell
python -m pytest
```

## License

MIT
