"""Claude Pet for Windows: a dog or a cat that roams your desktop and reacts to Claude Code.

Claude Code hooks POST their JSON to http://127.0.0.1:<port>/event (see pet_hook.py).
The pet follows the session that matters most: one that needs you wins over one that
is working, which wins over one that is thinking.

  idle      wanders along the taskbar: hops about, plays, chases your cursor, naps, hides
  thinking  sits and watches you, thought bubble
  working   busy pose, bubble shows the tool
  waiting   runs to your cursor and jumps
  happy     zoomies, then dances
  error     sad or puzzled face
  sleeping  eyes closed, breathing, zzz

Click it to pet it, drag it, right-click for the menu (switch pets, rename, reminders).
Which pet uses which pose is in pets.py; the art is in art/<kind>/. Run with:  pythonw pet.py
"""
import ctypes
import ctypes.wintypes
import json
import math
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import vector
from pets import DOG_CLOSED_EYES, MIC_SVG, PETS
from vector import mul, rotate, scale, translate

HOME = Path.home() / ".claude-pet"
ENDPOINT = HOME / "endpoint"
POS_FILE = HOME / "pos.json"
SETTINGS_FILE = HOME / "settings.json"
STATS_FILE = HOME / "stats.json"
ART =Path(__file__).resolve().parent / "art"
BASE_PORT = 47319

KEY = "#ff00fe"  # transparent (and click-through) colour; never draw with it
BUBBLE, INK, DOTS_OFF, ZZZ = "#fffaf3", "#3a2a22", "#cbbfb5", "#7aa2f7"
SOUND_WAVES = """<svg fill="none"><g transform="{transform}">
  <path d="M60 80 Q54 92 60 104" stroke="#7aa2f7" stroke-width="3" stroke-linecap="round"/>
  <path d="M50 74 Q40 92 50 110" stroke="#7aa2f7" stroke-width="3" stroke-linecap="round"/>
</g></svg>"""
HEART_SVG ="""<svg fill="none"><path d="M12 21 C12 21 2 14 2 8 C2 4.5 4.5 2 8 2 C10 2 11.5 3 12 4.5
  C12.5 3 14 2 16 2 C19.5 2 22 4.5 22 8 C22 14 12 21 12 21 Z" fill="#FF5D7A"/></svg>"""

SLEEP_AFTER = 60        # seconds without keyboard or mouse input before napping
STALE_AFTER = 30 * 60   # forget sessions that went silent this long ago
GRAVITY = 2200          # px/s², scaled with the art like every speed below

# Wellbeing reminders: minutes of active screen use between reminders (0 = off).
# "screen" is a milestone: an alert each time today's screen time passes another multiple.
REMINDERS = {
    "water": {"label": "Water", "default": 45, "choices": [30, 45, 60, 90]},
    "stretch": {"label": "Stretch / move", "default": 60, "choices": [30, 45, 60, 90]},
    "eyes": {"label": "Eye break (20-20-20)", "default": 20, "choices": [20, 30, 60]},
    "screen": {"label": "Screen time alert", "default": 120, "choices": [60, 120, 180]},
}
ACTIVE_IDLE = 120        # input within this many seconds counts as being at the screen
BREAK_IDLE = 5 * 60      # this long away counts as a break: resets the stretch and eye timers
REMINDER_FOR = 60        # a reminder waits this long for a click before giving up
EYE_BREAK = 20

# Usage-limit messages Claude Code writes to the transcript, old and new wording:
#   "Claude AI usage limit reached|1761234567"   "5-hour limit reached ∙ resets 3pm (Asia/Calcutta)"
LIMIT_EPOCH = re.compile(r"usage limit reached\|(\d{10})")
LIMIT_TEXT = re.compile(r"(?:limit reached|hit your (?:usage )?limit)[^\n\"]{0,40}?resets?\s+(?:at\s+)?"
                        r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)", re.I)

PRIORITY = {"waiting": 6, "limit": 5.5, "error": 5, "working": 4, "thinking": 3, "happy": 2, "idle": 1, "sleeping": 0}
TOOL_LABELS = {"bash": ">_ shell", "edit": "editing", "read": "reading", "web": "browsing",
               "agent": "agents", "other": "working"}


def tool_kind(name):
    n = (name or "").lower()
    if n in ("bash", "powershell", "bashoutput", "killshell"):
        return "bash"
    if n in ("edit", "write", "multiedit", "notebookedit"):
        return "edit"
    if n in ("read", "grep", "glob", "ls"):
        return "read"
    if n in ("webfetch", "websearch") or "browser" in n or "chrome" in n:
        return "web"
    if n in ("task", "agent"):
        return "agent"
    return "other"


def local_opener():
    # Never route 127.0.0.1 through a system proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def work_area(root):
    rect = ctypes.wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def user_idle_seconds():
    """Seconds since the last keyboard or mouse input anywhere on the PC."""
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def claude_mic_in_use():
    """True while a Claude app holds the microphone, per Windows' own mic-usage records
    (the ones behind the tray's microphone icon): in use = started and not yet stopped."""
    import winreg
    root = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def scan(path):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        with key:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    return False
                i += 1
                if "claude" not in name.lower():
                    continue
                try:
                    with winreg.OpenKey(key, name) as app:
                        start = winreg.QueryValueEx(app, "LastUsedTimeStart")[0]
                        stop = winreg.QueryValueEx(app, "LastUsedTimeStop")[0]
                except OSError:
                    continue
                if start and stop == 0:
                    return True

    return scan(root) or scan(root + r"\NonPackaged")


def read_json(path, default):
    try:
        return {**default, **json.loads(path.read_text())}
    except Exception:
        return dict(default)


def fmt_minutes(seconds):
    h, m = divmod(int(seconds // 60), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def find_limit(text, now=None):
    """Reset time (epoch seconds) if text holds a usage-limit message, else None."""
    now = now or time.time()
    found = None
    for m in LIMIT_EPOCH.finditer(text):
        found = float(m.group(1))
    for m in LIMIT_TEXT.finditer(text):
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        t = time.localtime(now)
        reset = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hour, int(m.group(2) or 0), 0, 0, 0, -1))
        found = reset + 86400 if reset <= now else reset
    return found if found and found > now else None


def transcript_tail(path, size=24000):
    """The last few entries of a session transcript."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return "\n".join(lines[-6:])
    except Exception:
        return ""


def load_poses(kind):
    """Shapes for every pose the engine asks for, from art/<kind>/ as mapped in pets.py.

    "<art>-sit" is that art without its props and raised arm; "<art>-sleep" is that with eyes closed.
    """
    cfg = PETS[kind]
    raw = {p.stem: vector.load(p.read_text(encoding="utf-8")) for p in (ART / kind).glob("*.svg")}

    def get(name):
        if name.endswith("-sit"):
            return [s for s in raw[name[:-4]] if s.role not in ("fx", "arm")]
        if name.endswith("-sleep"):
            return [s for s in get(name[:-6] + "-sit") if s.role not in ("pupil", "glint")] + vector.load(DOG_CLOSED_EYES)
        return raw[name]

    poses = {key: get(name) for key, name in cfg["poses"].items() if key != "play"}
    poses["play"] = [get(name) for name in cfg["poses"]["play"]]
    look = {"transform": cfg["mic_transform"], "fur": cfg["fur"], "paw": cfg["paw"], "outline": cfg["outline"]}
    poses["mic"] = poses["sit"] + vector.load(MIC_SVG.format(**look))
    poses["waves"] = vector.load(SOUND_WAVES.format(transform=cfg["mic_transform"]))
    return poses


class Session:
    def __init__(self):
        self.state, self.tool, self.until, self.project = "idle", "other", None, ""
        self.reset = None  # when a usage limit lifts
        self.updated = time.time()


class Pet:
    def __init__(self):
        self.events = queue.Queue()
        self.sessions = {}
        self.last_event = time.time()
        self.public_state = {"state": "idle", "sessions": {}}
        self.heart = vector.load(HEART_SVG)
        self.voice, self.voice_test_until = False, 0.0   # Claude has the microphone
        self.alarm_until, self.intruders = 0.0, []       # wrong-password alarms, cleared by a click

        # wellbeing reminders
        self.settings = read_json(SETTINGS_FILE, {k: r["default"] for k, r in REMINDERS.items()})
        self.settings.setdefault("pet", "dog")
        self.settings["names"] = {**{k: p["default_name"] for k, p in PETS.items()}, **self.settings.get("names", {})}
        if self.settings["pet"] not in PETS:
            self.settings["pet"] = "dog"
        self.stats = read_json(STATS_FILE, {"day": time.strftime("%Y-%m-%d"), "screen": 0.0, "done": 0})
        self.since = {k: 0.0 for k in REMINDERS}   # active seconds since each reminder last fired
        self.reminder = None                       # {"kind", "until", "start"} while one is showing
        self.snooze_until = 0.0
        self.last_track = time.time()
        self.done_project = ""
        self.limit_reset = None

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.title("Claude Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", KEY)
        self.root.configure(bg=KEY)
        self.dpi = self.root.winfo_fpixels("1i") / 96
        self.k = self.dpi               # speeds are tuned for 100% display scaling
        self.top = round(34 * self.dpi)  # room above the head for bubbles
        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.load_pet(self.settings["pet"])

        # body physics and behaviour
        self.area = work_area(self.root)
        self.x, self.y = self._start_x(), float(-self.H)  # drops in from the top of the screen
        self.leaving = False
        self.vy, self.facing, self.step = 0.0, -1, 0.0
        self.squash = 0.0
        self.mode, self.mode_since = None, time.time()
        self.action, self.action_start, self.action_until, self.target = None, 0.0, 0.0, self.x
        self.next_jump = 0.0
        self.next_blink, self.blink_until = time.time() + 3, 0.0
        self.love_until = 0.0
        self.held, self.press, self.drag_vx, self.last_drag = False, None, 0.0, (0.0, 0.0)
        self.pose, self.anim = "sit", {}
        self.moving = False
        self.hide, self.hide_cooldown, self.sink = None, 0.0, 0.0   # hide and seek
        self.play_pose = None
        self.preview = (None, 0.0)
        self.cursor = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        self.cursor_speed = 0.0
        self.last_tick = time.time()
        self.root.geometry(f"{self.W}x{self.H}+{int(self.x)}+{int(self.y)}")

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._menu)

    # ---------- which pet ----------
    def load_pet(self, kind):
        self.kind, self.cfg = kind, PETS[kind]
        self.poses = load_poses(kind)
        self.s = self.cfg["size"] * self.dpi
        self.W = round(self.cfg["view"] * self.s)
        self.H = round(self.top + self.cfg["bottom"] * self.s)
        self.canvas.config(width=self.W, height=self.H)
        self.root.geometry(f"{self.W}x{self.H}")

    @property
    def name(self):
        return self.settings["names"][self.kind]

    def switch_pet(self, kind):
        if kind == self.kind or kind not in PETS:
            return
        self.settings["pet"] = kind
        self.save_settings()
        center = self.x + self.W / 2
        self.load_pet(kind)
        self.x, self.y, self.vy = self.clamp_x(center - self.W / 2), float(-self.H), 0.0  # the new pet drops in
        self.action = self.hide = None
        self.play_pose = None

    def rename(self):
        from tkinter import simpledialog
        new = simpledialog.askstring("Rename", f"New name for your {self.cfg['label'].lower()}:",
                                     initialvalue=self.name, parent=self.root)
        new = (new or "").strip()[:20]
        if not new:
            return
        self.settings["names"][self.kind] = new
        self.save_settings()
        try:
            import petctl
            # /appear<name> and /shoo<name> follow the new name
            self.settings["skills"] = petctl.write_skills(self.settings["names"])
            self.save_settings()
        except Exception:
            pass

    def save_settings(self):
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))
        except Exception:
            pass

    # ---------- window ----------
    def ground(self):
        return self.area[3] - self.H

    def clamp_x(self, x):
        return max(self.area[0], min(self.area[2] - self.W, x))

    def _start_x(self):
        try:
            return self.clamp_x(float(json.loads(POS_FILE.read_text())[0]))
        except Exception:
            return self.clamp_x(self.area[2] - self.W - 120)

    def _press(self, e):
        self.press = (e.x_root, e.y_root, e.x_root - self.x, e.y_root - self.y)
        self.last_drag = (e.x_root, time.time())

    def _drag(self, e):
        if not self.press:
            return
        if not self.held and math.hypot(e.x_root - self.press[0], e.y_root - self.press[1]) > 4:
            self.held = True
        if self.held:
            now = time.time()
            lx, lt = self.last_drag
            if now > lt:
                self.drag_vx = 0.7 * self.drag_vx + 0.3 * (e.x_root - lx) / (now - lt)
            self.last_drag = (e.x_root, now)
            self.x, self.y = e.x_root - self.press[2], e.y_root - self.press[3]
            self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

    def _release(self, _e):
        if self.held:
            self.held, self.vy, self.drag_vx = False, 0.0, 0.0
            self.x = self.clamp_x(self.x)
            self.action = None
            self._save_x()
        else:
            self.reminder = None  # a click dismisses a reminder, finds a hiding dog, and is a pat on the head
            self.intruders, self.alarm_until = [], 0.0
            self.hide = None
            self.hide_cooldown = time.time() + 6
            self.love_until = time.time() + 2.5
        self.press = None

    def _save_x(self):
        try:
            POS_FILE.write_text(json.dumps([int(self.x)]))
        except Exception:
            pass

    def _menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label=self.name, state="disabled")
        pets = tk.Menu(m, tearoff=0)
        choice = tk.StringVar(value=self.kind)
        for kind, cfg in PETS.items():
            pets.add_radiobutton(label=f"{cfg['label']}: {self.settings['names'][kind]}", variable=choice,
                                 value=kind, command=lambda k=kind: self.switch_pet(k))
        pets.add_separator()
        pets.add_command(label=f"Rename {self.name}...", command=self.rename)
        pets.var = choice
        m.add_cascade(label="Pet", menu=pets)
        m.add_separator()
        live = list(self.sessions.values())
        m.add_command(label=f"{len(live)} Claude session(s)", state="disabled")
        for s in live[:6]:
            m.add_command(label=f"  {s.project or 'session'}: {s.state}", state="disabled")
        m.add_separator()
        m.add_command(label=f"Screen time today: {fmt_minutes(self.stats['screen'])}", state="disabled")
        m.add_command(label=f"Claude tasks done today: {self.stats['done']}", state="disabled")
        rem = tk.Menu(m, tearoff=0)
        for kind, r in REMINDERS.items():
            sub = tk.Menu(rem, tearoff=0)
            var = tk.IntVar(value=self.settings[kind])
            sub.add_radiobutton(label="Off", variable=var, value=0, command=lambda k=kind: self.set_interval(k, 0))
            for mins in r["choices"]:
                label = f"Every {fmt_minutes(mins * 60)} of screen time"
                sub.add_radiobutton(label=label, variable=var, value=mins,
                                    command=lambda k=kind, v=mins: self.set_interval(k, v))
            sub.add_separator()
            sub.add_command(label="Show it now", command=lambda k=kind: self.remind(k, force=True))
            sub.var = var  # keep the variable alive while the menu is open
            state = "off" if not self.settings[kind] else fmt_minutes(self.settings[kind] * 60)
            rem.add_cascade(label=f"{r['label']}  ({state})", menu=sub)
        rem.add_separator()
        if time.time() < self.snooze_until:
            rem.add_command(label="Resume reminders", command=lambda: setattr(self, "snooze_until", 0.0))
        else:
            rem.add_command(label="Snooze reminders for 1 hour",
                            command=lambda: setattr(self, "snooze_until", time.time() + 3600))
        m.add_cascade(label="Reminders", menu=rem)
        m.add_separator()
        m.add_command(label="Play demo", command=self.demo)
        m.add_command(label="Come here", command=lambda: self.events.put(
            {"session_id": "call", "pet_state": "waiting", "pet_duration": 3}))
        m.add_command(label=f"Shoo (bye {self.name})", command=lambda: setattr(self, "leaving", True))
        m.tk_popup(e.x_root, e.y_root)

    def set_interval(self, kind, minutes):
        self.settings[kind] = minutes
        self.since[kind] = 0.0
        self.save_settings()

    # ---------- wellbeing reminders ----------
    def track(self, now):
        """Once a second: count screen time and fire reminders that are due."""
        dt, self.last_track = now - self.last_track, now
        try:
            self.voice = claude_mic_in_use()
        except Exception:
            self.voice = False
        day = time.strftime("%Y-%m-%d")
        if self.stats["day"] != day:
            self.stats = {"day": day, "screen": 0.0, "done": 0}
        idle = user_idle_seconds()
        if idle >= BREAK_IDLE:  # stepped away: that was a break
            self.since["stretch"] = self.since["eyes"] = 0.0
        if idle >= ACTIVE_IDLE or dt > 30:  # away, or the PC was asleep
            return
        before = self.stats["screen"]
        self.stats["screen"] += dt
        for kind in ("water", "stretch", "eyes"):
            self.since[kind] += dt
            if self.settings[kind] and self.since[kind] >= self.settings[kind] * 60:
                self.remind(kind)
        step = self.settings["screen"] * 60
        if step and int(before // step) < int(self.stats["screen"] // step):
            self.remind("screen")
        if int(before) // 60 != int(self.stats["screen"]) // 60:
            self.save_stats()

    def remind(self, kind, force=False):
        now = time.time()
        if not force and (now < self.snooze_until or self.reminder):
            return  # stays due; fires on a later tick
        self.since[kind] = 0.0
        self.reminder = {"kind": kind, "start": now,
                         "until": now + (EYE_BREAK + 4 if kind == "eyes" else REMINDER_FOR)}
        self.action = None

    def reminder_text(self, now):
        r = self.reminder
        kind, age = r["kind"], now - r["start"]
        if kind == "water":
            return "drink water!" if int(age * 0.7) % 2 == 0 else "stay hydrated"
        if kind == "stretch":
            return "stretch break!" if int(age * 0.7) % 2 == 0 else "stand up & move"
        if kind == "eyes":
            left = EYE_BREAK - int(age - 2)
            if age < 2:
                return "eye break!"
            return f"look away {left}s" if left > 0 else "thanks!"
        return f"{fmt_minutes(self.stats['screen'])} on screen"

    def save_stats(self):
        try:
            STATS_FILE.write_text(json.dumps(self.stats))
        except Exception:
            pass

    def quit(self):
        self._save_x()
        self.save_stats()
        try:
            if ENDPOINT.read_text().strip() == str(self.port):
                ENDPOINT.unlink()
        except Exception:
            pass
        self.root.destroy()

    # ---------- Claude events ----------
    def apply(self, ev):
        now = time.time()
        sid = str(ev.get("session_id") or "default")
        self.last_event = now
        if ev.get("pet_control") == "shoo":  # /shoo<name>: run off the screen, then quit
            self.leaving = True
            return
        if ev.get("pet_control") == "switch":  # /appear<name> for the other pet
            self.switch_pet(ev.get("pet"))
            return
        if "pet_preview" in ev:  # for checking art: {"pet_preview": "work", "pet_duration": 3}
            self.preview = (ev["pet_preview"], now + float(ev.get("pet_duration") or 3))
            return
        if "pet_alarm" in ev and not ev["pet_alarm"]:
            self.intruders, self.alarm_until = [], 0.0
            return
        if ev.get("pet_alarm"):  # a wrong password at the lock screen (see petctl.py growl)
            self.alarm_until = now + 6
            self.intruders.append(now)
            self.hide, self.reminder = None, None
            return
        if "pet_voice" in ev:  # for testing the mic pose: {"pet_voice": 5} holds it 5 s
            self.voice_test_until = now + float(ev["pet_voice"] or 0)
            return
        if "pet_remind" in ev:  # for scripts: {"pet_remind": "water"}, or "clear"
            if ev["pet_remind"] in REMINDERS:
                self.remind(ev["pet_remind"], force=True)
            else:
                self.reminder = None
            return
        if ev.get("hook_event_name") == "SessionEnd":
            self.sessions.pop(sid, None)
            return
        s = self.sessions.setdefault(sid, Session())
        s.updated = now
        if ev.get("cwd"):
            s.project = Path(ev["cwd"]).name

        if "pet_state" in ev:  # forced state, for scripts and the demo
            dur = ev.get("pet_duration")
            s.state, s.tool = ev["pet_state"], ev.get("pet_tool", "other")
            s.until = s.reset = now + float(dur) if dur else None
            return

        name = ev.get("hook_event_name")
        s.until = None
        if name == "SessionStart":
            s.state = "idle"
        elif name in ("UserPromptSubmit", "PreCompact", "PostToolUse"):
            s.state = "thinking"
        elif name == "PreToolUse":
            if ev.get("tool_name") == "AskUserQuestion":
                s.state = "waiting"
            else:
                s.state, s.tool = "working", tool_kind(ev.get("tool_name"))
        elif name == "PostToolUseFailure":
            s.state, s.until = "error", now + 2
        elif name == "Notification":
            msg = (ev.get("message") or "").lower()
            idle_ping = ev.get("notification_type") == "idle_prompt" or "waiting for your input" in msg
            if not idle_ping:
                s.state = "waiting"
        elif name == "Stop":
            reset = find_limit(transcript_tail(ev.get("transcript_path") or "") + "\n" + str(ev.get("message", "")))
            if reset:
                s.state, s.until, s.reset = "limit", reset, reset
            else:
                s.state, s.until = "happy", now + 5
                self.done_project = s.project
                self.stats["done"] += 1
                self.save_stats()
        if name == "Notification" and find_limit(ev.get("message") or ""):
            s.reset = find_limit(ev["message"])
            s.state, s.until = "limit", s.reset

    def current(self):
        now = time.time()
        for sid, s in list(self.sessions.items()):
            if now - s.updated > STALE_AFTER:
                del self.sessions[sid]
            elif s.until and now >= s.until:
                if s.state == "error":
                    s.state = "thinking"
                elif s.state == "waiting" and sid == "call":
                    del self.sessions[sid]
                    continue
                else:
                    s.state = "idle"
                s.until = None
        best = max(self.sessions.values(), key=lambda s: PRIORITY.get(s.state, 0), default=None)
        state, tool = (best.state, best.tool) if best else ("idle", "other")
        self.limit_reset = best.reset if best and state == "limit" else None
        if state == "idle" and user_idle_seconds() > SLEEP_AFTER and now > self.love_until:
            state = "sleeping"
        return state, tool

    # ---------- behaviour ----------
    def cursor_x(self):
        return self.clamp_x(self.root.winfo_pointerx() - self.W / 2)

    def face_cursor(self):
        self.facing = 1 if self.root.winfo_pointerx() > self.x + self.W / 2 else -1

    def move_toward(self, tx, speed, dt):
        """Head toward window-x tx; returns True once there."""
        dx = tx - self.x
        if abs(dx) < 3 * self.k:
            return True
        self.facing = 1 if dx > 0 else -1
        d = min(abs(dx), speed * self.k * dt)
        self.x += self.facing * d
        self.step += d
        self.moving = True
        return False

    def jump(self, power):
        if self.y >= self.ground() - 0.5:
            self.vy = -power * self.k

    def pick_action(self, now):
        a = random.choices(["walk", "sit", "play", "dance", "chase", "nap", "spin"],
                           [32, 20, 16, 8, 10, 9, 5])[0]
        span = {"walk": (4, 8), "sit": (3, 6), "play": (3, 6), "dance": (2.5, 4), "chase": (4, 6),
                "nap": (4, 7), "spin": (1.2, 1.2)}[a]
        self.action, self.action_start, self.action_until = a, now, now + random.uniform(*span)
        if a == "play":
            self.play_pose = f"play:{random.randrange(len(self.poses['play']))}"
        if a == "walk":
            reach = random.uniform(80, 380) * self.k
            self.target = self.clamp_x(self.x + random.choice((-1, 1)) * reach)

    def behave(self, state, now, dt):
        self.moving = False
        anim = {"tail": "slow", "ears": 0.0, "look": "cursor", "gait": None, "tilt": 0.0, "bob": 0.0,
                "arms": 0.0, "breathe": False}
        if state != self.mode:
            self.mode, self.mode_since, self.action, self.hide = state, now, None, None

        # gravity, with a squash on landing
        g = self.ground()
        if not self.held and (self.y < g - 0.5 or self.vy < 0):
            self.vy += GRAVITY * self.k * dt
            self.y += self.vy * dt
            self.moving = True
            if self.y >= g:
                self.y = g
                self.squash = min(0.25, self.vy / (5000 * self.k))
                self.vy = -self.vy * 0.25 if self.vy > 900 * self.k else 0.0
        elif not self.held:
            self.y = g
        airborne = self.y < g - 0.5

        pose = "sit"
        if self.leaving:
            left, right = self.area[0] - self.W - 10, self.area[2] + 10
            exit_x = left if self.x - left < right - self.x else right
            self.facing = 1 if exit_x > self.x else -1
            self.x += self.facing * min(abs(exit_x - self.x), 700 * self.k * dt)
            self.moving = True
            if abs(exit_x - self.x) < 1:
                self.root.after(0, self.quit)
            anim.update(tail="fast", look="ahead", bob=-12 + 4 * math.sin(now * 16))
            self.pose, self.anim = "run", anim
            return
        if self.held:
            pose = "held"
            anim.update(tail="still", look="ahead", tilt=max(-25.0, min(25.0, -self.drag_vx / 40)))
            self.drag_vx *= 0.9
        elif state == "sleeping":
            pose = "sleep"
            anim.update(tail="still", look="ahead", breathe=True)
        elif state in ("error", "limit"):
            pose = "sad" if state == "error" else "rest"
            anim.update(tail="still", look="down", tilt=3 * math.sin(now * 1.5))
        elif state == "thinking":
            anim.update(look="up", ears=4.0, tilt=2 * math.sin(now * 1.2))
        elif state == "working":
            pose = "work"
            anim.update(look="work", tail="slow", tilt=1.5 * math.sin(now * 3))
        elif state == "waiting":
            anim.update(tail="fast", ears=8.0)
            if self.move_toward(self.cursor_x(), 520, dt):
                if not airborne:
                    self.face_cursor()
                    if now >= self.next_jump:
                        self.jump(620)
                        self.next_jump = now + 0.9
                pose = "alert"
            else:
                pose = "run"
                anim.update(look="ahead", bob=-10 + 4 * math.sin(now * 14))
        elif state == "happy":
            anim.update(tail="fast", ears=8.0)
            if now - self.mode_since < 3:
                if self.action != "zoom" or self.move_toward(self.target, 700, dt):
                    self.action = "zoom"
                    self.target = self.clamp_x(self.x + random.choice((-1, 1)) * random.uniform(150, 380) * self.k)
                    if random.random() < 0.4:
                        self.jump(480)
                pose = "run"
                anim.update(look="ahead", bob=-12 + 4 * math.sin(now * 16))
            else:
                pose = "dance" if int(now - self.mode_since) % 3 else "excited"
                anim.update(tilt=8 * math.sin(now * 6), bob=-abs(math.sin(now * 6)) * 8, arms=1.0)
        elif not self.reminder:
            pose = self.hide_and_seek(now, dt, anim) or self.wander(now, dt, anim)

        # A reminder interrupts anything but Claude needing you: come to the cursor, then act it out.
        if self.reminder and not self.held and state != "waiting":
            kind = self.reminder["kind"]
            anim.update(gait=None, arms=0.0, breathe=False, tilt=0.0, bob=0.0, tail="slow", ears=0.0)
            if not self.reminder.get("arrived") and not self.move_toward(self.cursor_x(), 520, dt):
                pose = "run"
                anim.update(look="ahead", bob=-10 + 4 * math.sin(now * 14))
            else:
                self.reminder["arrived"] = True
                self.face_cursor()
                if kind == "water":
                    pose = "drink"
                    anim.update(look="down", bob=1.5 * abs(math.sin(now * 5)))
                elif kind == "stretch":
                    pose = "stretch"
                    anim.update(tail="fast", ears=8.0, arms=1.0, tilt=10 * math.sin(now * 5),
                                bob=-abs(math.sin(now * 5)) * 10)
                elif kind == "eyes":
                    age = now - self.reminder["start"]
                    pose = "alert" if age < 2 or age > EYE_BREAK + 2 else "sleep"
                    anim.update(look="ahead", breathe=pose == "sleep")
                else:
                    pose = "alert"
                    anim.update(ears=6.0, tail="fast")
                    if now >= self.next_jump and not airborne:
                        self.jump(420)
                        self.next_jump = now + 1.6

        # You're talking to Claude: stop, face you and hold up the mic.
        if (self.voice or now < self.voice_test_until) and not self.held:
            self.hide = None
            pose = "mic"
            anim.update(gait=None, arms=0.0, breathe=False, sink=0.0, tail="slow", ears=3.0, look="cursor",
                        tilt=2 * math.sin(now * 2), bob=-abs(math.sin(now * 7)) * 1.5)

        # Guard pet: cross at a wrong password, and stays cross until you click.
        if self.intruders and not self.held:
            self.hide = None
            pose = "angry"
            anim.update(gait=None, arms=0.0, breathe=False, sink=0.0, tail="still", ears=-6.0, look="cursor",
                        tilt=4 * math.sin(now * 30) if now < self.alarm_until else 2 * math.sin(now * 2), bob=0.0)
            if now < self.alarm_until and now >= self.next_jump and not airborne:
                self.jump(380)
                self.next_jump = now + 0.7

        if now < self.love_until and not self.held and pose not in ("mic", "angry"):
            pose = "love"
            anim.update(tail="fast", ears=6.0, look="ahead", tilt=4 * math.sin(now * 10),
                        bob=-abs(math.sin(now * 10)) * 4)
        if airborne and pose not in ("run", "held"):
            anim["stretch"] = True
        if now < self.preview[1] and (self.preview[0] in self.poses or self.preview[0].startswith("play:")):
            pose = self.preview[0]
        if not self.moving and not self.held and pose != "run" and self.action != "spin":
            self.face_cursor()  # whenever it stands still, it turns to you
        self.pose, self.anim = pose, anim

    def hide_and_seek(self, now, dt, anim):
        """Rush the cursor at the pet and it hops off and hides, peeking over the taskbar edge."""
        px, py = self.cursor
        dist = math.hypot(px - (self.x + self.W / 2), py - (self.y + self.H * 0.6))
        h = self.hide
        if h is None:
            if now < self.hide_cooldown or dist > 170 * self.k or self.cursor_speed < 250 * self.k:
                return None
            away = -1 if px > self.x + self.W / 2 else 1
            reach = random.uniform(130, 230) * self.k
            h = self.hide = {"phase": "dash", "t": now, "target": self.clamp_x(self.x + away * reach)}
            if abs(h["target"] - self.x) < 40 * self.k:  # cornered at the screen edge: hide right here
                h.update(phase="hidden")
        anim.update(tail="fast", ears=6.0)
        if h["phase"] == "dash":
            if self.move_toward(h["target"], 460, dt):
                h.update(phase="hidden", t=now)
            else:
                anim.update(gait="hop")
                return "excited"
        if h["phase"] == "hidden":
            anim.update(sink=float(self.cfg["peek_sink"]), tilt=7 * math.sin(now * 4))
            near = dist < 220 * self.k
            if now - h["t"] > (3.0 if near else 1.4):
                h.update(phase="peek", t=now)
                self.jump(560)
            return "sit"
        anim.update(bob=-abs(math.sin(now * 10)) * 6, ears=9.0)  # peekaboo!
        if now - h["t"] > 1.8:
            self.hide, self.hide_cooldown = None, now + 4
        return "excited"

    def wander(self, now, dt, anim):
        if self.action is None or now >= self.action_until:
            self.pick_action(now)
        a = self.action
        if a == "walk":
            if self.move_toward(self.target, 95, dt):
                self.action_until = min(self.action_until, now + 0.6)
            else:
                anim.update(gait="hop", look="ahead")
            return "sit"
        if a == "chase":
            if self.move_toward(self.cursor_x(), 360, dt):
                self.face_cursor()
                anim.update(tail="fast", ears=6.0)
                return "excited"
            anim.update(look="ahead", bob=-10 + 4 * math.sin(now * 14))
            return "run"
        if a == "play":
            anim.update(tail="slow", bob=1.5 * abs(math.sin(now * 4)))
            return self.play_pose or "sit"
        if a == "dance":
            anim.update(tail="fast", ears=8.0, arms=1.0, tilt=8 * math.sin(now * 6),
                        bob=-abs(math.sin(now * 6)) * 8)
            return "dance"
        if a == "nap":
            anim.update(tail="still", look="ahead", breathe=True)
            return "nap" if now - self.action_start > 0.8 else "sit"
        if a == "spin":
            self.facing = 1 if int(now * 7) % 2 else -1
            anim.update(tail="fast", look="ahead", bob=-abs(math.sin(now * 14)) * 5)
            return "excited"
        return "sit"  # sit and watch the cursor

    # ---------- loop ----------
    def tick(self):
        now = time.time()
        dt, self.last_tick = min(0.1, now - self.last_tick), now
        try:
            while True:
                self.apply(self.events.get_nowait())
        except queue.Empty:
            pass
        state, tool = self.current()
        cursor = (self.root.winfo_pointerx(), self.root.winfo_pointery())
        if dt > 0:
            speed = math.hypot(cursor[0] - self.cursor[0], cursor[1] - self.cursor[1]) / dt
            self.cursor_speed = 0.6 * self.cursor_speed + 0.4 * speed
        self.cursor = cursor
        if now - self.last_track >= 1:
            self.track(now)
        if self.reminder and now >= self.reminder["until"]:
            self.reminder = None
        if self.reminder and state == "sleeping":
            state = "idle"  # a reminder wakes the dog up
        self.behave(state, now, dt)
        self.public_state = {"state": state, "tool": tool, "pose": self.pose,
                             "reminder": self.reminder and self.reminder["kind"],
                             "screen_today": int(self.stats["screen"]), "done_today": self.stats["done"],
                             "window": [int(self.x), int(self.y), self.W, self.H],
                             "sessions": {k: v.state for k, v in self.sessions.items()}}
        if not self.held:
            self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
        self.draw(state, tool, now)
        self.root.after(120 if state == "sleeping" else 40, self.tick)

    def demo(self):
        steps = [("thinking", "other", 3), ("working", "bash", 3), ("working", "edit", 2.5),
                 ("waiting", "other", 4), ("error", "other", 2.5), ("happy", "other", 6)]
        t = 0
        for st, tool, dur in steps:
            self.root.after(int(t * 1000), self.events.put,
                            {"session_id": "demo", "pet_state": st, "pet_tool": tool, "pet_duration": dur})
            t += dur
        self.root.after(int(t * 1000), self.events.put, {"session_id": "demo", "hook_event_name": "SessionEnd"})

    # ---------- drawing ----------
    def draw(self, state, tool, now):
        c, a = self.canvas, self.anim
        c.delete("all")

        # whole-body motion, in viewBox units around the paws
        bob, tilt = a["bob"], a["tilt"]
        self.sink += (a.get("sink", 0.0) - self.sink) * 0.3  # duck down to hide, ease back up
        bob += self.sink
        sx = sy = 1.0
        phase = self.step / (14 * self.k) * math.pi
        if a["gait"] == "hop":
            bob -= abs(math.sin(phase)) * 9
            tilt += 5 * math.sin(phase)
        if a["breathe"]:
            sy = 1 + 0.025 * math.sin(now * 2.2)
            sx = 2 - sy
        if a.get("stretch"):
            sy, sx = 1.07, 0.95
        if self.squash > 0.01:
            sy, sx = 1 - self.squash, 1 + self.squash * 0.8
            self.squash *= 0.75
        cx, feet = self.cfg["center"], self.cfg["feet"]
        m = mul(translate(0, self.top), scale(self.s))
        m = mul(m, translate(0, bob))
        m = mul(m, rotate(tilt, cx, feet))
        m = mul(m, scale(sx, sy, cx, feet))
        if self.facing < 0:
            m = mul(m, scale(-1, 1, cx, 0))

        # parts
        wag = {"fast": 20 * math.sin(now * 20), "slow": 10 * math.sin(now * 5), "still": 0.0}[a["tail"]]
        flap = a["ears"] * math.sin(now * 9)
        lift = (max(0.0, math.sin(phase)) * 7, max(0.0, -math.sin(phase)) * 7) if a["gait"] else (0.0, 0.0)
        arms = a["arms"] * 16 * math.sin(now * 12)
        if now >= self.next_blink:
            self.blink_until, self.next_blink = now + 0.15, now + random.uniform(2.5, 6)
        blink = now < self.blink_until
        look = self.look_offset()

        def part(sh):
            r = sh.role
            side = -1 if sh.pivot[0] < cx else 1
            if r == "tail":
                return rotate(wag, *sh.pivot)
            if r == "ear":
                return rotate(flap * side, *sh.pivot)
            if r == "arm" and arms:
                return rotate(arms * side, *sh.pivot)
            if r == "feet":
                return translate(0, -(lift[0] if sh.center[0] < cx else lift[1]))
            if r == "pupil":
                t = translate(*look)
                return mul(t, scale(1, 0.15, *sh.center)) if blink else t
            if r == "eyeball":
                return scale(1, 0.15, *sh.center) if blink else vector.IDENT
            if r == "glint":
                return None if blink else translate(*look)
            return vector.IDENT

        shapes = (self.poses["play"][int(self.pose[5:])] if self.pose.startswith("play:")
                  else self.poses[self.pose])
        vector.draw(c, shapes, m, self.s, part)

        # overlays, anchored above the head
        words = self.cfg["words"]
        hx, hy = vector.apply(m, *self.cfg["head"])
        hx = max(30, min(self.W - 30, hx))
        if self.leaving:
            self.bubble(hx, hy, "bye!")
        elif self.intruders and not self.held:
            if now < self.alarm_until:
                self.bubble(hx, hy, words["growl"] if now - self.intruders[-1] < 1.4 else words["bark"])
            else:
                n = len(self.intruders)
                clock = time.strftime("%I:%M %p", time.localtime(self.intruders[-1])).lstrip("0")
                texts = ["wrong password!", f"x{n} at {clock}" if n > 1 else f"at {clock}", "click: ok"]
                self.bubble(hx, hy, texts[int(now / 1.6) % 3])
        elif self.pose == "mic":
            if int(now * 3) % 2:
                vector.draw(c, self.poses["waves"], m, self.s)
            self.bubble(hx, hy, "listening...")
        elif now < self.love_until:
            for i in range(2):
                rise = ((now * 1.6 + i * 0.5) % 1) * 26 * self.k
                hm = mul(translate(hx - 30 * self.k + i * 34 * self.k, hy - 4 - rise), scale(0.9 * self.k))
                vector.draw(c, self.heart, hm, self.k)
        elif self.hide and self.hide["phase"] == "peek":
            self.bubble(hx, hy, "peekaboo!")
        elif self.reminder and state != "waiting" and self.reminder.get("arrived"):
            self.bubble(hx, hy, self.reminder_text(now))
        elif self.pose in ("sleep", "nap"):
            for i, size in enumerate((9, 12, 15)):
                rise = ((now * 0.5 + i / 3) % 1) * 18 * self.k
                c.create_text(hx + (12 + i * 9) * self.k, hy - rise, text="z", fill=ZZZ,
                              font=("Segoe UI", size, "bold"))
        elif state == "thinking":
            self.bubble(hx, hy, None, int(now * 3) % 4)
        elif state == "working":
            self.bubble(hx, hy, TOOL_LABELS.get(tool, "working"))
        elif state == "waiting":
            self.bubble(hx, hy, words["call"] if int(now * 1.2) % 2 else "needs you!")
        elif state == "happy":
            project = self.done_project[:14]
            self.bubble(hx, hy, f"{project} done!" if project and int(now) % 2 else "work done!")
        elif state == "error":
            self.bubble(hx, hy, "oops...")
        elif state == "limit":
            reset = self.limit_reset or now
            clock = time.strftime("%I:%M %p", time.localtime(reset)).lstrip("0")
            texts = ["limit reached", f"resets {clock}", f"in {fmt_minutes(max(60, reset - now))}"]
            self.bubble(hx, hy, texts[int(now / 1.5) % 3])

    def look_offset(self):
        """Pupil offset so the eyes always follow the cursor."""
        px, py = self.cursor
        eye_y = self.y + self.top + (self.cfg["head"][1] + 40 + self.sink) * self.s
        reach = self.cfg["look"]
        dx = max(-1.0, min(1.0, (px - (self.x + self.W / 2)) / (250 * self.k))) * reach
        dy = max(-1.0, min(1.0, (py - eye_y) / (250 * self.k))) * reach * 0.85
        return (dx * self.facing, dy)  # the art is mirrored when facing left

    def bubble(self, ax, ay, text, dots=0):
        c, k = self.canvas, self.k
        pad = round(6 * k)
        tw = self.font.measure(text) if text else round(26 * k)
        th = self.font.metrics("linespace")
        w, h = tw + 2 * pad, th + pad
        x0 = max(2, min(self.W - w - 2, ax - w / 2))
        y0 = max(2, ay - h - 8 * k)
        c.create_rectangle(x0, y0, x0 + w, y0 + h, fill=BUBBLE, outline=INK, width=2)
        c.create_polygon(ax - 4 * k, y0 + h - 1, ax + 4 * k, y0 + h - 1, ax, y0 + h + 6 * k,
                         fill=BUBBLE, outline="")
        if text:
            c.create_text(x0 + w / 2, y0 + h / 2, text=text, fill=INK, font=self.font)
        else:
            d = round(5 * k)
            for i in range(3):
                cx = x0 + pad + i * (d + 4 * k)
                c.create_oval(cx, y0 + h / 2 - d / 2, cx + d, y0 + h / 2 + d / 2,
                              fill=INK if i < dots else DOTS_OFF, outline="")

    # ---------- server ----------
    def serve(self):
        pet = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.headers.get("Origin"):
                    return self._send(403, {"error": "browsers not allowed"})
                if self.path == "/health":
                    self._send(200, {"app": "claude-pet", "ok": True})
                elif self.path == "/state":
                    self._send(200, pet.public_state)
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                # Web pages always send Origin, and can't send JSON without a preflight we never answer.
                if self.headers.get("Origin") or "json" not in (self.headers.get("Content-Type") or ""):
                    return self._send(403, {"error": "rejected"})
                if self.path != "/event":
                    return self._send(404, {"error": "not found"})
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    ev = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._send(400, {"error": "bad json"})
                if isinstance(ev, dict):
                    pet.events.put(ev)
                self._send(200, {"ok": True})

            def log_message(self, *_):
                pass

        for port in range(BASE_PORT, BASE_PORT + 10):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError:
                continue
        else:
            raise SystemExit("no free port for Claude Pet")
        self.port = port
        ENDPOINT.write_text(str(port))
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def run(self):
        self.serve()
        if "--demo" in sys.argv:
            self.root.after(500, self.demo)
        self.tick()
        self.root.mainloop()


def already_running():
    try:
        port = int(ENDPOINT.read_text().strip())
        with local_opener().open(f"http://127.0.0.1:{port}/health", timeout=0.5) as r:
            return json.load(r).get("app") == "claude-pet"
    except Exception:
        return False


if __name__ == "__main__":
    HOME.mkdir(exist_ok=True)
    if already_running():
        sys.exit(0)
    Pet().run()
