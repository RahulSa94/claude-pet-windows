"""The pets you can pick, and how each one's art maps onto the pet's moods.

Every pose key on the left is something the engine asks for; the value is an SVG in art/<kind>/
(or a list, from which one is picked at random). Coordinates are in that art's own viewBox.
"""

# A paw holding a microphone up to the mouth, drawn in the dog's 200x200 viewBox;
# other pets place it with `mic_transform`.
MIC_SVG = """<svg fill="none"><g transform="{transform}">
  <path d="M79 97 L86 99 L80 122 L73 120 Z" fill="#334155"/>
  <path class="micarm" d="M66 126 C62 114 66 104 74 102 C80 104 82 112 78 124 Z" fill="{fur}" stroke="{outline}" stroke-width="1.5"/>
  <circle class="micarm" cx="78" cy="106" r="6.5" fill="{paw}"/>
  <circle cx="84" cy="92" r="8.5" fill="#64748B" stroke="#1E293B" stroke-width="2"/>
  <path d="M78 89 L90 89 M77 93 L91 93 M79 97 L89 97" stroke="#94A3B8" stroke-width="1.5" stroke-linecap="round"/>
</g></svg>"""

# Closed eyes for art that has no sleeping pose of its own (the dog).
DOG_CLOSED_EYES = """<svg fill="none">
  <path d="M71 72 Q79 78 87 72" stroke="#1E293B" stroke-width="3" stroke-linecap="round"/>
  <path d="M103 72 Q111 78 119 72" stroke="#1E293B" stroke-width="3" stroke-linecap="round"/>
</svg>"""

PETS = {
    "dog": {
        "label": "Dog",
        "default_name": "Rocky",
        "view": 200, "size": 0.62,       # viewBox width, and on-screen scale at 100% display scaling
        "center": 100, "feet": 174, "bottom": 176,
        "head": (100, 30),               # where speech bubbles point
        "look": 4.0,                     # how far the pupils travel to follow the cursor
        "peek_sink": 96,                 # how far it ducks to hide, leaving only ears and eyes
        "fur": "#D97706", "paw": "#FEF3C7", "outline": "#B45309",
        "mic_transform": "",
        "words": {"call": "woof!", "growl": "GRRR...", "bark": "WOOF! WOOF!"},
        "poses": {
            "sit": "emojis-sit", "love": "emojis", "sleep": "emojis-sleep", "nap": "emojis-sleep",
            "work": "task-reminder", "alert": "screen-time-alert", "run": "flying",
            "dance": "dancing", "excited": "happy-excited", "sad": "sad-face", "rest": "sad-face",
            "held": "angry-pouting", "angry": "angry-pouting", "drink": "drinking-water",
            "stretch": "dancing", "play": ["dancing", "happy-excited", "drinking-water"],
        },
    },
    "cat": {
        "label": "Cat",
        "default_name": "Snowy",
        "view": 300, "size": 0.46,
        "center": 150, "feet": 234, "bottom": 246,
        "head": (150, 40),
        "look": 5.0,
        "peek_sink": 118,
        "fur": "#FFFFFF", "paw": "#F1A8BF", "outline": "#BFC2C9",
        "mic_transform": "translate(17 -4) scale(1.4)",
        "words": {"call": "meow!", "growl": "HISSS...", "bark": "MROW!"},
        "poses": {
            "sit": "sit", "love": "love", "sleep": "sleep", "nap": "loaf",
            "work": "knead", "alert": "wave", "run": "walk",
            "dance": "chase", "excited": "pounce", "sad": "curious", "rest": "loaf",
            "held": "curious", "angry": "pounce", "drink": "drink",
            "stretch": "stretch",
            "play": ["yarn", "box", "peek", "groom", "scratch", "eat", "drink", "chase", "yawn", "blink"],
        },
    },
}
