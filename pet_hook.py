"""Claude Code hook relay: forwards the hook's JSON to Claude Pet.

Prints nothing and always exits 0, so it can never change or block what Claude does.
When the pet isn't running it gives up immediately (connection refused) or after 1 s at most.
"""
import sys
import urllib.request
from pathlib import Path


def main():
    data = sys.stdin.buffer.read() or b"{}"
    try:
        port = int((Path.home() / ".claude-pet" / "endpoint").read_text().strip())
    except Exception:
        return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(f"http://127.0.0.1:{port}/event", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        opener.open(req, timeout=1).close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
