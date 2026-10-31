# Claude Pet for Windows

A dog or a cat that lives on your Windows desktop, wanders along the taskbar and reacts to what
[Claude Code](https://claude.com/claude-code) is doing: the CLI and the Code tab of the Claude desktop app.

- **Rocky** the dog, in glasses, or **Snowy** the white cat with a pink bow. Switch any time, and name them whatever you like.
- **Follows Claude:** thinks while Claude thinks, gets busy while it runs tools (the bubble says which), runs to your cursor when Claude needs an answer or a permission, does zoomies when a task is done ("my-app done!"). It settles down by itself when you press Esc or reject a tool. With several sessions open, the one that needs you comes first, then one that just finished, then busy ones.
- **Usage limit:** when Claude hits its limit, the pet tells you when it resets ("resets 3:00 PM", "in 1h 12m").
- **Voice:** when you talk to Claude, the pet holds up a microphone.
- **Wellbeing reminders:** water, stretch breaks, 20-20-20 eye breaks and screen-time milestones. They count only time you're actually at the PC.
- **Playful:** its eyes follow your cursor, it chases the cursor, naps when you're away, and plays hide and seek if you rush at it. Click to pet, drag to carry.
- **Silent and light:** no sounds, no extra installs, just Python's standard library.

## Install

You need Windows 10 or 11 and [Python 3.10+](https://www.python.org/downloads/windows/) (tick **Add python.exe to PATH**).

1. Download this repo (**Code › Download ZIP**, then unzip it) or `git clone` it.
2. Double-click **`install.bat`**, pick a dog or a cat, and give it a name.
3. Restart any open Claude Code sessions so they pick up the hooks.

Or from a terminal:

```bash
python install.py install --pet cat --name Snowy --start
```

The installer:

- copies the pet to `%USERPROFILE%\.claude-pet`
- adds hooks to `%USERPROFILE%\.claude\settings.json`, after making a backup (nothing else in that file changes)
- adds `/appear<name>` and `/shoo<name>` skills to Claude Code
- adds a **Claude Pet** shortcut to the Start menu

Preview the changes first with `--dry-run`.

## Using it

| | |
|---|---|
| **Click** | pet it (hearts), dismiss a reminder, find it when it's hiding |
| **Drag** | carry it; it drops back down when you let go |
| **Right-click** | switch pet, rename, reminders, today's screen time and Claude tasks, demo, shoo |
| **`/appearrocky`, `/appearsnowy`** | in Claude Code: summon that pet (it swaps in if the other one is out) |
| **`/shoorocky`, `/shoosnowy`** | send it off the screen |

The skills follow your pets' names: rename the cat to Mochi and you get `/appearmochi`.

### Reminders

Each reminder fires after that many minutes of *active* screen time. Stepping away for 5 minutes resets the stretch and eye timers. Change them or turn them off from **right-click › Reminders**; there's also a one-hour snooze.

| Reminder | Default | What the pet does |
|---|---|---|
| Water | 45 min | runs over and drinks |
| Stretch / move | 60 min | stretches |
| Eye break (20-20-20) | 20 min | closes its eyes for a 20 s countdown |
| Screen time | every 2 h | "2h on screen" |

### Optional: wrong-password guard

`python install.py install --guard`, run from an **administrator** terminal, adds a task that makes the pet cross ("GRRR...") when a wrong password is typed at the lock screen. After you unlock, it shows the time of the attempt until you click it. Windows only lets administrators watch failed sign-ins.

## Uninstall

```bash
python install.py uninstall
```

This removes the hooks, the skills, the Start menu shortcut and the guard task. Then delete `%USERPROFILE%\.claude-pet` if you want your settings gone too.

## How it works

```
Claude Code ──hook──▶ pet_hook.py ──POST 127.0.0.1:47319/event──▶ pet.py ──▶ your desktop
```

- `pet_hook.py` forwards each hook's JSON to the pet. It prints nothing and always exits 0, so it can never change what Claude does. If the pet isn't running, it gives up immediately, never taking more than a second.
- `pet.py` is a borderless, always-on-top tkinter window. Clicks pass through everywhere except the pet itself. The poses are SVGs in `art/dog` and `art/cat`, drawn by a small vector renderer (`vector.py`) that also wags tails, flaps ears, blinks and moves pupils.
- `pets.py` maps each mood to a pose for each pet. Add a pet by dropping its SVGs into `art/<kind>/` and adding an entry there.
- Everything stays on your PC. The pet only listens on `127.0.0.1` and refuses requests from web pages. Microphone use is read from Windows' own privacy records, the same ones behind the tray icon; the pet never opens the microphone itself.

### Local API

| Request | Effect |
|---|---|
| `POST /event` with a Claude Code hook's JSON | what the hooks do |
| `POST /event {"pet_state": "happy", "pet_duration": 3}` | force a state: `idle`, `thinking`, `working`, `waiting`, `happy`, `error`, `limit`, `sleeping` |
| `POST /event {"pet_remind": "water"}` | show a reminder now: `water`, `stretch`, `eyes`, `screen` |
| `POST /event {"pet_control": "switch", "pet": "cat"}` | swap pets |
| `GET /state`, `GET /health` | current state, and whether it's running |
| `GET /events` | the last 60 hooks received, for checking that Claude Code is reaching the pet |

## Art

- `art/dog`: Rocky, from the Claude Pet Dog vector library (`tools/extract_dog.py`)
- `art/cat`: Snowy, from the Snowwhite cat vector study (`tools/extract_cat.js`)

## License

[MIT](LICENSE) © 2026 Rahul Saha

---

Not affiliated with Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic, PBC.
