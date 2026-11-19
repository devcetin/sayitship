# sayitship

**Press one button. Say it. Your coding agent ships it.**

Press the iPhone Action Button, speak a task and put the phone back in your pocket. The task runs in the background on your own computer or server with Claude Code, and you get a one-line result as a notification. You never open an app.

> 🚧 Work in progress. v0.1 works end to end; the router is next.

## How it works (v0.1)

```
Action Button → Shortcut (dictate) → your server (over Tailscale) → claude -p → ntfy notification
```

1. The Shortcut turns your voice into text, sends it to your server and returns right away.
2. The server runs the task in the background with Claude Code.
3. When it finishes, you get a one-sentence summary on your phone through ntfy.

## Quick start (Windows)

You need Python 3.12+, [Claude Code](https://claude.com/claude-code) signed in (`claude` on your PATH), [Tailscale](https://tailscale.com) on your PC and iPhone, and the [ntfy](https://ntfy.sh) app on your iPhone.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in your own values
python -m sayitship
```

Send a test task from the PC:

```powershell
$h = @{ Authorization = "Bearer <your-token>" }
Invoke-RestMethod -Method Post -Uri http://<tailscale-ip>:8787/task -Headers $h -ContentType "application/json; charset=utf-8" -Body '{"text":"Create hello.txt that says hi"}'
```

You get `202 Accepted` right away and an ntfy notification when the task finishes.

### API

`POST /task` with header `Authorization: Bearer <token>` and JSON body:

| field | required | meaning |
|---|---|---|
| `text` | yes | the task, in plain words |
| `workdir` | no | a name from `WORKDIRS` (never a raw path); default is the first one |

### What Claude Code may do

By default the task runs with `--permission-mode acceptEdits --allowedTools Read Edit Write Glob Grep`: it can read and edit files inside the chosen workdir, but it cannot run shell commands. Change `CLAUDE_ARGS` in `.env` only if you understand what you allow.

## Roadmap

- [x] v0.1: voice → background task → notification
- [ ] Router: answer quick questions directly, and send a task to the right existing project session
- [ ] Context: attach your clipboard, latest screenshot or a shared link
- [ ] Approvals: Yes/No buttons before risky actions
- [ ] Router eval: a public test set with accuracy, latency and cost

## Security

Your phone's voice can run code on your computer, so security comes first:
- The server is reachable only over your private Tailscale network, never the open internet.
- Every request needs a secret token.
- Claude Code works only inside folders you list in `WORKDIRS`, and by default it cannot run shell commands.
- Risky actions will require your approval.

## License

MIT
