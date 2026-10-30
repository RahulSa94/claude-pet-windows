"""Summon, dismiss or switch your Claude Pet.

    python petctl.py appear [--pet dog|cat]   drops in from the top of the screen (or swaps to that pet)
    python petctl.py shoo                     runs off the edge of the screen and quits
    python petctl.py growl                    gets cross at a wrong password (run by the guard task)
    python petctl.py skills                   (re)writes the /appear<name> and /shoo<name> Claude Code skills
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home() / ".claude-pet"
SETTINGS_FILE = HOME / "settings.json"
SKILLS_DIR = Path.home() / ".claude" / "skills"
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Claude Pet.lnk"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEFAULT_NAMES = {"dog": "Rocky", "cat": "Snowy"}


def settings():
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        return {}


def save_settings(data):
    HOME.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def names():
    return {**DEFAULT_NAMES, **settings().get("names", {})}


def call(path, body=None):
    port = int((HOME / "endpoint").read_text().strip())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=1) as r:
        return json.load(r)


def running():
    try:
        return call("/health").get("app") == "claude-pet"
    except Exception:
        return False


def appear(kind=None):
    name = names()[kind or settings().get("pet", "dog")]
    if running():
        if kind:
            call("/event", {"pet_control": "switch", "pet": kind})
            print(f"{name} is here!")
        else:
            print(f"{name} is already here.")
        return
    if kind:  # start as the pet that was asked for
        data = settings()
        data["pet"] = kind
        save_settings(data)
    # Launch through Explorer so the pet outlives the shell that ran this command.
    if SHORTCUT.exists():
        subprocess.run(["explorer.exe", str(SHORTCUT)])
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), str(HOME / "pet.py")],
                         creationflags=0x00000008 | 0x00000200, close_fds=True)  # detached, own group
    for _ in range(50):
        if running():
            print(f"{name} dropped in!")
            return
        time.sleep(0.1)
    print("The pet didn't show up: try the Claude Pet shortcut in the Start menu.")


def shoo():
    name = names()[settings().get("pet", "dog")]
    if not running():
        print(f"{name} isn't here.")
        return
    call("/event", {"pet_control": "shoo"})
    for _ in range(60):
        if not running():
            print(f"{name} ran off. Bye!")
            return
        time.sleep(0.1)
    print(f"{name} is still on the way out...")


def growl():
    if running():
        call("/event", {"pet_alarm": 1})


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower()) or "pet"


def write_skills(pet_names=None):
    """/appear<name> and /shoo<name> for each pet, replacing the ones made for older names."""
    pet_names = pet_names or names()
    data = settings()
    for old in data.get("skills", []):
        shutil.rmtree(SKILLS_DIR / old, ignore_errors=True)
    python = Path(sys.executable).with_name("python.exe")
    python = (python if python.exists() else Path(sys.executable)).as_posix()
    me = (HOME / "petctl.py").as_posix()
    made = []
    for kind, name in pet_names.items():
        for verb, args, what in (("appear", f"appear --pet {kind}", f"Make {name}, your Claude Pet {kind}, appear on the desktop."),
                                 ("shoo", "shoo", f"Shoo {name}, your Claude Pet {kind}, off the desktop.")):
            skill = f"{verb}{slug(name)}"
            if skill in made:
                continue
            d = SKILLS_DIR / skill
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: {what}\ndisable-model-invocation: true\n---\n\n"
                f"Run this command and reply with its one-line output, nothing else:\n\n"
                f"```bash\n\"{python}\" \"{me}\" {args}\n```\n", encoding="utf-8")
            made.append(skill)
    data = settings()
    data["skills"] = made
    save_settings(data)
    return made


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    pet = sys.argv[sys.argv.index("--pet") + 1] if "--pet" in sys.argv[:-1] else None
    if cmd == "appear":
        appear(pet if pet in DEFAULT_NAMES else None)
    elif cmd == "shoo":
        shoo()
    elif cmd == "growl":
        growl()
    elif cmd == "skills":
        print("skills: /" + " /".join(write_skills()))
    else:
        print(__doc__)
