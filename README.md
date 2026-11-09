# ADDGate

Quizzes you on what you built with Claude, so you own it instead of borrowing it.

While you work in Claude Code, ADDGate captures each session. When you're done, you
**close the gate**: Claude reads the day's work and writes cold questions about the decisions
it made. Anything you can't explain comes back in **Review** on later days, in a new scenario,
until you own it.

Runs locally on your Mac and uses your Claude subscription through Claude Code (`claude -p`).
No API key. The server only listens on 127.0.0.1.

## Setup (Mac)

You need Python 3.10+ and Claude Code, signed in (`claude` works in your terminal).

```bash
# put the folder where you want it, e.g.
mv ~/Downloads/ADDGate ~/tools/ADDGate
cd ~/tools/ADDGate
chmod +x start.sh
./start.sh
```

The first run creates a Python venv and installs Flask. The UI is prebuilt, so you don't
need Node unless you change the front end. Your browser opens to http://localhost:5055.

Then, in the app:

1. **Settings → Install Stop hook.** Adds one entry to `~/.claude/settings.json` (backed up
   first). Without it, ADDGate scans today's transcripts in `~/.claude/projects` instead,
   which also works.
2. **Settings → Git repos.** Add the repos you work in so commits count too.

## Accounts

The first screen asks you to create an account. Each account has its own quizzes, vault,
review schedule and settings. Everyone shares the Mac's Claude Code sign-in and its session
history, though, so they all see the same Capture sessions.

- Passwords are hashed with scrypt. Sign-in uses an HttpOnly, SameSite=Strict cookie, and
  every API route except sign-in requires it.
- The **first** account created adopts any ADDGate data from before accounts existed.
- Forgot a password? There's no email on a local app, so reset it from Terminal:
  `cd backend && ../.venv/bin/python manage.py reset-password <username>`

## Stats

The **Stats** page shows your ownership rate, streak, answers per day for the last 30 days,
the categories you borrow most, your hardest concepts and the reviews coming up this week.
Every stats query is scoped to the signed-in account (`WHERE user_id = ?`), with the id taken
from the server-side session, so no account can see another's numbers.

## Terminal

A real shell on your Mac inside ADDGate (xterm.js in the browser, a PTY on the server). Claude
Code sessions you run there get captured like any other. It runs as your Mac user, so it is
locked down:

| Threat | Defense |
|---|---|
| Other ADDGate accounts on this Mac | **Owner only**: the first account created. Nobody else sees it. |
| Someone at your unlocked browser, a stolen cookie | **Off by default**; turning it on and opening it need your password (re-confirmed every 15 min). |
| A malicious website connecting to localhost | WebSocket needs a **single-use ticket** (30 s, tied to your account) and an exact **Origin** match, checked before the connection is accepted. |
| DNS rebinding | Every request's **Host** must be `localhost` / `127.0.0.1`. |
| Injected scripts (XSS would mean shell access) | Strict **Content-Security-Policy**: only ADDGate's own scripts. |
| Clickjacking | Framing is blocked (`frame-ancestors 'none'`, `X-Frame-Options: DENY`). |
| Password guessing | 5 wrong passwords locks that login for 5 minutes. |
| Forgotten shells | 30-minute idle timeout, max 3 per account, closed on sign-out. |
| Your network | The server only listens on 127.0.0.1. |

Every terminal open/close, refused connection and lockout is in **Settings → Terminal and security
log** (events only, never keystrokes). What it can't stop: someone who knows your password sitting
at your unlocked Mac, who could open Terminal.app anyway.

## Shell capture

Records the commands **you** type yourself (never their output), so gate questions can cover your
own work, not just Claude's. Owner only, off by default: turn it on in **Settings → Shell capture**.

- **Where:** ADDGate's built-in Terminal captures automatically (zsh). For your regular Terminal
  app, Settings can add one line to `~/.zshrc` (it backs the file up first), or add it yourself:
  `source "/path/to/ADDGate/backend/hooks/shell_capture.zsh"`.
- **Only in folders you choose** (default: your git repos). Everything else is ignored.
- **Start a command with a space** and it's never recorded.
- **Secrets are redacted before saving:** API keys and tokens, `Authorization` headers,
  `user:pass@` in URLs, `-p`/`--password`/`--token` flags, `export SOMETHING_TOKEN=...`, and long
  random strings. The raw record is deleted as soon as it's imported.
- Noise like `ls` and `cd` is skipped. You can delete everything captured at any time.

## Storage

Everything lives in one SQLite database, `~/gate/addgate.db`, so there's no database server
to install. It runs in WAL mode, and every change is a short transaction, so parallel requests
(two tabs, a gate answer during a review) can't overwrite each other.

```bash
cd backend
../.venv/bin/python manage.py users            # list accounts
../.venv/bin/python manage.py backup           # safe copy to ~/gate/backups/, even while running
../.venv/bin/python manage.py reset-password <username>
sqlite3 ~/gate/addgate.db ".tables"            # poke around (read-only is safest)
```

Upgrading from an older version? On first start, ADDGate imports the old JSON files
(`users.json`, `vault.json`, `days/`, `usage.json`) into the database and renames each one
with an `.imported` suffix. Nothing is deleted. Files from the May CLI are left alone.

## Admins

Admins get an **Admin** tab: accounts, access, backups, health and an activity log. The first account on a
Mac is an admin; any admin can make or remove others from the Accounts list.

- **Accounts:** see who has an account, when they were last active and how much they use (counts and token
  totals, never answers, vault entries, transcripts or typed commands). Add accounts, make or remove admins,
  reset a password (a temporary one, shown once, that the person must change at next sign-in), unlock, sign
  out everywhere, turn an account off, set a daily Claude token cap, or delete it (a backup is saved first).
- **Access:** open or admin-only sign-up, and the starting settings new accounts get.
- **Backups:** one a day automatically (last 14 kept), on demand, and before deleting an account or restoring.
- **Health** and **Activity:** connection status, versions, and every sign-in and admin action.

Deleting, restoring, resetting a password or changing a role asks for your own password again (15 minutes).
The last admin can't be removed, turned off or deleted. If no admin is left, run from `backend/`:
`../.venv/bin/python manage.py make-admin <username>`.

Tests: `cd backend && ../.venv/bin/python -m unittest tests.test_admin`

## Desktop app (Mac)

ADDGate can run as a real Mac app, like Claude Desktop: its own window, Dock icon and Cmd+Q.

```bash
./build_app.sh
```

It packages ADDGate into `ADDGate.app` (Python included, about 60 MB), puts it in Applications and opens
it. Opening the app starts ADDGate's server; quitting stops it. If `./start.sh` is already running, the
app uses that server instead. Re-run `./build_app.sh` after each update.

No Apple Developer account is needed: an app you build on your own Mac isn't quarantined, so it opens
without a warning. Sharing the built `.app` with someone else would show Gatekeeper's warning (they'd
right-click → Open); they can build it themselves from this repo instead.

## Daily use

1. Leave ADDGate open and work in Claude Code as usual. Sessions show up on **Capture**.
2. When you're done, click **Close gate & quiz me**. Claude takes about 30–60 seconds to read your day.
3. Pick an answer, say how sure you are, and explain **why** in your own words. The why is
   what gets graded: a right pick with no real reasoning counts as partial. The hint unlocks
   after 60 seconds.
4. Come back the next day: anything you didn't own shows up in **Review** with a different
   scenario. Missing it twice puts it in **relearn**, which starts with a short lesson.

Owned concepts come back at 1, 3, 7, 14 and 30 days.

## Honesty, not policing

ADDGate can't stop you from pasting a question into another AI, and it doesn't try. It's not an
exam, so the only person cheating hurts is you. Instead it makes honesty easy and keeps a record:

- **I looked it up**: no penalty, the concept just comes back tomorrow.
- **Signals, not blocks**: pasting an explanation, typing faster than a person can, or saying
  you were guessing caps that answer at *partial*. Leaving the tab is only noted.
- **Did it hold?** Concepts you owned the first time get asked again in new scenarios. Stats
  shows how many held up, and the Vault marks the ones that didn't. That's the number a
  screenshot can't fake.

Gate questions are multiple choice plus a why. The wrong choices are real misconceptions, so a
wrong pick tells you exactly what you misunderstood. Reviews switch to open recall, which is harder.

## Where things live

```
~/gate/                (owner-only)
├── addgate.db         accounts, settings, gate state, concepts, attempts, quizzes, usage
├── secret.key         signs sign-in cookies
├── sessions/          Stop hook index, one file per day
└── backups/           from manage.py backup
```

## Usage meter

The top bar shows **ADDGate's own** Claude calls today and roughly how many tokens they used.
Cached instructions that Claude Code re-reads on every call are left out, because they count
far less toward your plan. It is **not** your plan's remaining quota; that's in Claude under
Settings, then Usage. You can set an optional warning threshold in Settings. Connection checks
only call Claude on startup, when you press Refresh, or after a call fails to sign in.

## Developing

```bash
./dev.sh    # API with auto-reload on :5055 + UI with hot reload on http://localhost:5173
```

ADDGate runs on **gunicorn** with one worker and many threads (`start.sh`). Keep it at one worker:
terminal tickets and sessions live in that process's memory.

`npm run build` writes the UI into `backend/static`. Prompts live in `backend/prompts.py`, and
that's the first place to tune if the questions feel off.

## Not built yet

- Docker sabotage drills (break the code, you fix it)
- Notion (dropped)
