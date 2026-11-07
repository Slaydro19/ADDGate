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

## Storage

Everything lives in one SQLite database, `~/gate/addgate.db`, so there's no database server
to install. It runs in WAL mode, and every change is a short transaction, so parallel requests
(two tabs, a gate answer during a review) can't overwrite each other.

```bash
cd backend
../.venv/bin/python manage.py users            # list accounts
../.venv/bin/python manage.py backup           # safe copy to ~/gate/backups/, even while running
../.venv/bin/python manage.py reset-password jalen
sqlite3 ~/gate/addgate.db ".tables"            # poke around (read-only is safest)
```

Upgrading from an older version? On first start, ADDGate imports the old JSON files
(`users.json`, `vault.json`, `days/`, `usage.json`) into the database and renames each one
with an `.imported` suffix. Nothing is deleted. Files from the May CLI are left alone.

## Daily use

1. Leave ADDGate open and work in Claude Code as usual. Sessions show up on **Capture**.
2. When you're done, click **Close gate & quiz me**. Claude takes about 30–60 seconds to read your day.
3. Answer each question in your own words. The hint unlocks after 60 seconds.
4. Come back the next day: anything you didn't own shows up in **Review** with a different
   scenario. Missing it twice puts it in **relearn**, which starts with a short lesson.

Owned concepts come back at 1, 3, 7, 14 and 30 days.

## Where things live

```
~/gate/                (owner-only)
├── addgate.db         accounts, settings, gate state, concepts, attempts, quizzes, usage
├── secret.key         signs sign-in cookies
├── sessions/          Stop hook index, one file per day
└── backups/           from manage.py backup
```

## Usage meter

The meter counts tokens from **ADDGate's own** Claude calls against the daily budget you set.
It isn't your Claude plan's remaining quota, because there's no supported way to read that. If
Claude returns a usage-limit error, the meter turns red and shows the reset message.

## Developing

```bash
# terminal 1: API
cd backend && ../.venv/bin/python app.py
# terminal 2: UI with hot reload on http://localhost:5173
cd frontend && npm install && npm run dev
```

`npm run build` writes the UI into `backend/static`. Prompts live in `backend/prompts.py`, and
that's the first place to tune if the questions feel off.

## Not built yet

- Docker sabotage drills (break the code, you fix it)
- Shell command capture (OSC 133)
- Notion (dropped)
