"""Pull the dog SVGs out of the vector showcase page into art/dog/<id>.svg.

    python tools/extract_dog.py "path/to/claude_pet_vector_showcase.html"
"""
import re
import sys
from pathlib import Path

html = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(__file__).resolve().parent.parent / "art" / "dog"
out.mkdir(exist_ok=True)
for art_id, svg in re.findall(r"id:\s*'([\w-]+)'.*?svg:\s*`(.*?)`", html, re.S):
    (out / f"{art_id}.svg").write_text(svg.strip() + "\n", encoding="utf-8")
    print("wrote", art_id)
