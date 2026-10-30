"""Install or remove Claude Pet.

    python install.py install [--pet dog|cat] [--name NAME] [--start] [--guard] [--dry-run]
    python install.py uninstall [--dry-run]

install copies the pet to ~/.claude-pet, adds Claude Code hooks to ~/.claude/settings.json,
writes the /appear<name> and /shoo<name> skills, and adds a "Claude Pet" Start menu shortcut.
--guard also registers a task that makes the pet cross at a wrong Windows password (needs admin).
~/.claude/settings.json is backed up before every write; nothing else in it changes.
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home() / ".claude-pet"
SETTINGS = Path.home() / ".claude" / "settings.json"
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Claude Pet.lnk"
FILES = ("pet.py", "pet_hook.py", "vector.py", "pets.py", "petctl.py")
GUARD_TASK = "Claude Pet - guard"
# Failed sign-ins typed at this PC (interactive, unlock, cached): event 4625 in the Security log.
GUARD_QUERY = ("*[System[(EventID=4625)]] and *[EventData[Data[@Name='LogonType']='2' "
               "or Data[@Name='LogonType']='7' or Data[@Name='LogonType']='11']]")
MARK = "pet_hook.py"
EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification",
          "Stop", "PreCompact", "SessionEnd"]
TOOL_EVENTS = {"PreToolUse", "PostToolUse"}


def arg(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv[:-1] else None


def pythonw():
    w = Path(sys.executable).with_name("pythonw.exe")
    return w if w.exists() else Path(sys.executable)


def hook_command():
    return f'"{pythonw().as_posix()}" "{(HOME / "pet_hook.py").as_posix()}"'


def register_guard_task():
    """A Task Scheduler task that runs `petctl.py growl` whenever a wrong password is typed here."""
    from xml.sax.saxutils import escape
    query = (f'<QueryList><Query Id="0" Path="Security"><Select Path="Security">{GUARD_QUERY}'
             f'</Select></Query></QueryList>')
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Claude Pet gets cross at a wrong password.</Description></RegistrationInfo>
  <Triggers><EventTrigger><Enabled>true</Enabled><Subscription>{escape(query)}</Subscription></EventTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT1M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{escape(str(pythonw()))}</Command>
    <Arguments>"{escape(str(HOME / 'petctl.py'))}" growl</Arguments>
    <WorkingDirectory>{escape(str(HOME))}</WorkingDirectory>
  </Exec></Actions>
</Task>
"""
    path = HOME / "guard-task.xml"
    path.write_text(xml, encoding="utf-16")
    r = subprocess.run(["schtasks", "/Create", "/TN", GUARD_TASK, "/XML", str(path), "/F"],
                       capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    if r.returncode:
        print("The guard task needs an administrator: run this from an admin terminal to add it.")


def make_shortcut():
    q = lambda p: str(p).replace("'", "''")  # PowerShell single-quote escaping
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(SHORTCUT)}');"
          f"$s.TargetPath='{q(pythonw())}';$s.Arguments='\"{q(HOME / 'pet.py')}\"';"
          f"$s.WorkingDirectory='{q(HOME)}';$s.Description='Claude Pet';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)


def strip_ours(settings):
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            group["hooks"] = [h for h in group.get("hooks", []) if MARK not in h.get("command", "")]
            if group["hooks"]:
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)


def add_ours(settings):
    hooks = settings.setdefault("hooks", {})
    entry = {"type": "command", "command": hook_command(), "timeout": 5}
    for event in EVENTS:
        group = {"matcher": "*", "hooks": [entry]} if event in TOOL_EVENTS else {"hooks": [entry]}
        hooks.setdefault(event, []).append(group)


def pet_settings():
    """Apply --pet / --name to ~/.claude-pet/settings.json."""
    path = HOME / "settings.json"
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    kind, name = arg("--pet"), arg("--name")
    if kind in ("dog", "cat"):
        data["pet"] = kind
    if name:
        data.setdefault("names", {})[data.get("pet", "dog")] = name.strip()[:20]
    path.write_text(json.dumps(data, indent=2))


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    dry = "--dry-run" in sys.argv
    if action not in ("install", "uninstall"):
        raise SystemExit(__doc__)
    before_text = SETTINGS.read_text(encoding="utf-8") if SETTINGS.exists() else "{}\n"
    settings = json.loads(before_text)
    strip_ours(settings)
    if action == "install":
        add_ours(settings)
    after_text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"

    diff = "".join(difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True),
                                        str(SETTINGS), str(SETTINGS) + " (new)"))
    print(diff or "Claude Code settings: hooks already in place")
    if dry:
        if action == "install":
            print(f"\nWould copy {', '.join(FILES)} and art/ to {HOME}")
            print("Would add /appear<name> and /shoo<name> skills for each pet")
            print(f"Would create Start menu shortcut: {SHORTCUT}")
        return

    sys.path.insert(0, str(HERE))
    import petctl

    if action == "install":
        HOME.mkdir(exist_ok=True)
        for name in FILES:
            shutil.copy2(HERE / name, HOME / name)
        shutil.copytree(HERE / "art", HOME / "art", dirs_exist_ok=True)
        (HOME / "rocky.py").unlink(missing_ok=True)  # replaced by petctl.py
        pet_settings()
        petctl.HOME = HOME
        print("Skills: /" + " /".join(petctl.write_skills()))
        if "--guard" in sys.argv:
            register_guard_task()
        make_shortcut()
    else:
        if petctl.running():
            petctl.shoo()
        SHORTCUT.unlink(missing_ok=True)
        for skill in petctl.settings().get("skills", []):
            shutil.rmtree(petctl.SKILLS_DIR / skill, ignore_errors=True)
        subprocess.run(["schtasks", "/Delete", "/TN", GUARD_TASK, "/F"], capture_output=True)

    if diff:
        SETTINGS.parent.mkdir(exist_ok=True)
        if SETTINGS.exists():
            backup = SETTINGS.with_name(f"settings.json.claude-pet-backup-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(SETTINGS, backup)
            print(f"Backed up Claude Code settings to {backup}")
        SETTINGS.write_text(after_text, encoding="utf-8")
        print("Claude Code hooks " + ("added" if action == "install" else "removed"))

    if action == "install" and "--start" in sys.argv:
        petctl.appear()
    if action == "uninstall":
        print(f"Removed. Your pet's files are still in {HOME}; delete that folder to remove them too.")


if __name__ == "__main__":
    main()
