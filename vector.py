"""A tiny SVG-subset renderer for a tkinter Canvas.

Handles what the dog art uses: circle, ellipse, rect (rounded), line, polygon, path
(M L H V Q T C S Z, absolute and relative), text, nested <g> and transform attributes.
Every element becomes point lists up front, so animating a part is just point math.

Each shape also gets a `role` from the nearest preceding <!-- comment --> in the file
(tail, ear, feet, arm, pupil, glint, glasses...), which is how the pet knows what to wag.
"""
import math
import re
import xml.etree.ElementTree as ET

IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
NUM = r"-?(?:\d+\.?\d*|\.\d+)(?:[eE]-?\d+)?"
BACKDROP = "#D97706"  # semi-transparent fills are blended against the fur colour


def mul(m, n):
    """m after n."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D,
            a * E + c * F + e, b * E + d * F + f)


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def translate(x, y=0.0):
    return (1.0, 0.0, 0.0, 1.0, x, y)


def scale(sx, sy=None, cx=0.0, cy=0.0):
    sy = sx if sy is None else sy
    return mul(translate(cx, cy), mul((sx, 0.0, 0.0, sy, 0.0, 0.0), translate(-cx, -cy)))


def rotate(deg, cx=0.0, cy=0.0):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return mul(translate(cx, cy), mul((c, s, -s, c, 0.0, 0.0), translate(-cx, -cy)))


def parse_transform(text):
    m = IDENT
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in re.findall(NUM, args)]
        if name == "translate":
            t = translate(v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "rotate":
            t = rotate(v[0], *(v[1:3] if len(v) >= 3 else (0.0, 0.0)))
        elif name == "scale":
            t = scale(v[0], v[1] if len(v) > 1 else None)
        else:
            continue
        m = mul(m, t)
    return m


def blend(color, alpha, under=BACKDROP):
    c1 = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(under[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a * alpha + b * (1 - alpha)):02x}" for a, b in zip(c1, c2))


def path_subpaths(d, steps=10):
    toks = re.findall(r"[MmLlHhVvQqTtCcSsZz]|" + NUM, d)
    subs, cur = [], []
    x = y = sx = sy = 0.0
    cmd, prev_cmd, ctrl = None, None, None
    i = 0

    def take(n):
        nonlocal i
        vals = [float(t) for t in toks[i:i + n]]
        i += n
        return vals

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    subs.append((cur, True))
                cur, x, y, prev_cmd = [], sx, sy, "Z"
                continue
        rel, C = cmd.islower(), cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if C == "M":
            nx, ny = take(2)
            if cur:
                subs.append((cur, False))
            x, y = nx + ox, ny + oy
            sx, sy, cur = x, y, [(x, y)]
            cmd = "l" if rel else "L"
        elif C == "L":
            nx, ny = take(2)
            x, y = nx + ox, ny + oy
            cur.append((x, y))
        elif C == "H":
            x = take(1)[0] + ox
            cur.append((x, y))
        elif C == "V":
            y = take(1)[0] + oy
            cur.append((x, y))
        elif C in "QT":
            if C == "Q":
                qx, qy, nx, ny = take(4)
                qx, qy = qx + ox, qy + oy
            else:
                nx, ny = take(2)
                qx, qy = (2 * x - ctrl[0], 2 * y - ctrl[1]) if prev_cmd in "QT" and ctrl else (x, y)
            nx, ny = nx + ox, ny + oy
            for k in range(1, steps + 1):
                t = k / steps
                cur.append(((1 - t) ** 2 * x + 2 * (1 - t) * t * qx + t * t * nx,
                            (1 - t) ** 2 * y + 2 * (1 - t) * t * qy + t * t * ny))
            ctrl, x, y = (qx, qy), nx, ny
        elif C in "CS":
            if C == "C":
                ax, ay, bx, by, nx, ny = take(6)
                ax, ay = ax + ox, ay + oy
            else:
                bx, by, nx, ny = take(4)
                ax, ay = (2 * x - ctrl[0], 2 * y - ctrl[1]) if prev_cmd in "CS" and ctrl else (x, y)
            bx, by, nx, ny = bx + ox, by + oy, nx + ox, ny + oy
            for k in range(1, steps + 1):
                t = k / steps
                u = 1 - t
                cur.append((u ** 3 * x + 3 * u * u * t * ax + 3 * u * t * t * bx + t ** 3 * nx,
                            u ** 3 * y + 3 * u * u * t * ay + 3 * u * t * t * by + t ** 3 * ny))
            ctrl, x, y = (bx, by), nx, ny
        else:
            i += 1
        prev_cmd = C
    if cur:
        subs.append((cur, False))
    return subs


def ellipse_pts(cx, cy, rx, ry):
    n = max(14, int((rx + ry) * 0.7))
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


def rounded_rect(x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    if r <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for k in range(4):
            a = math.radians(a0 + k * 30)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class Shape:
    def __init__(self, pts, closed, style, role, section):
        self.pts, self.closed, self.role, self.section = pts, closed, role, section
        self.fill, self.stroke, self.width, self.dash, self.round = style
        self.text = None
        self.pivot = pts[0] if pts else (0.0, 0.0)
        xs, ys = [p[0] for p in pts] or [0], [p[1] for p in pts] or [0]
        self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def role_for_class(classes, tag, attrs, fill):
    """Roles for art that labels its parts with CSS classes (the cat)."""
    fill = (fill or "").lower()
    if "tail" in classes:
        return "tail"
    if "eye" in classes:
        if fill in ("white", "#fff", "#ffffff"):
            big = float(attrs.get("rx", attrs.get("r", 0))) > 10
            return "eyeball" if big else "glint"
        return "pupil" if fill else "body"
    if classes & {"wave"}:
        return "arm"
    if classes & {"knead1", "knead2", "groom"}:
        return "feet"
    if classes & {"toy", "hearts"}:
        return "fx"
    return "body"


def role_for(section, tag, attrs, fill):
    s = section.lower()
    words = set(re.findall(r"[a-z]+", s))
    fill = (fill or "").upper()
    r = float(attrs.get("r", 0))
    if tag == "circle" and fill == "#1E293B" and 4 <= r <= 7:
        return "pupil"
    if tag == "circle" and fill == "#FFFFFF" and 1.8 <= r <= 2.5:
        return "glint"
    if tag == "polygon" and fill == "#1E293B" and "sparkle" in words:
        return "pupil"
    if words & {"bubble", "badge", "music", "steam", "wind", "shield", "clipboard", "straw"}:
        return "fx"
    if "tail" in words:
        return "tail"
    if words & {"arm", "arms", "raised"}:
        return "arm"
    if words & {"ear", "ears"}:
        return "ear"
    if s in ("paws", "feet paws"):
        return "feet"
    if words & {"glasses"}:
        return "glasses"
    return "body"


def load(svg_text):
    """Parse SVG text into a list of Shapes in the 0..200 viewBox space."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(svg_text, parser=parser)
    shapes = []
    section = [""]
    tail_paths = set()  # the cat draws its tail twice (outline, then fill): both must wag

    def walk(node, m, inherited):
        for child in node:
            if child.tag is ET.Comment:
                section[0] = (child.text or "").strip()
                continue
            tag = child.tag.split("}")[-1]
            a = child.attrib
            style = dict(inherited)
            for k in ("fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap",
                      "fill-opacity", "opacity"):
                if k in a:
                    style[k] = a[k]
            cm = mul(m, parse_transform(a.get("transform")))
            style["class"] = (inherited.get("class", "") + " " + a.get("class", "")).strip()
            if tag == "g":
                walk(child, cm, style)
                continue
            f = lambda k, d=0.0: float(a.get(k, d))
            if tag == "circle":
                subs = [(ellipse_pts(f("cx"), f("cy"), f("r"), f("r")), True)]
            elif tag == "ellipse":
                subs = [(ellipse_pts(f("cx"), f("cy"), f("rx"), f("ry")), True)]
            elif tag == "rect":
                subs = [(rounded_rect(f("x"), f("y"), f("width"), f("height"), f("rx")), True)]
            elif tag == "line":
                subs = [([(f("x1"), f("y1")), (f("x2"), f("y2"))], False)]
            elif tag == "polygon":
                v = [float(n) for n in re.findall(NUM, a.get("points", ""))]
                subs = [(list(zip(v[::2], v[1::2])), True)]
            elif tag == "path":
                subs = path_subpaths(a.get("d", ""))
            elif tag == "text":
                subs = [([(f("x"), f("y"))], False)]
            else:
                continue

            fill = style.get("fill")
            fill = None if fill in (None, "none") else fill
            alpha = float(style.get("fill-opacity", 1)) * float(style.get("opacity", 1))
            if fill and alpha < 0.25:
                fill = None
            elif fill and alpha < 1:
                fill = blend(fill, alpha)
            stroke = style.get("stroke")
            stroke = None if stroke in (None, "none") else stroke
            dash = tuple(int(float(n)) for n in re.findall(NUM, style.get("stroke-dasharray", ""))) or None
            look = (fill, stroke, float(style.get("stroke-width", 1)), dash, style.get("stroke-linecap") == "round")
            classes = set(style["class"].split())
            if "tail" in classes:
                tail_paths.add(a.get("d"))
            if classes or (tag == "path" and a.get("d") in tail_paths):
                role = "tail" if a.get("d") in tail_paths else role_for_class(classes, tag, a, fill)
            else:
                role = role_for(section[0], tag, a, fill)
            for pts, closed in subs:
                sh = Shape([apply(cm, x, y) for x, y in pts], closed or bool(fill), look, role, section[0])
                if tag == "text":
                    sh.text = (child.text or "", float(a.get("font-size", 12)))
                shapes.append(sh)

    walk(root, IDENT, {"fill": root.attrib.get("fill", "black")})
    return shapes


def draw(canvas, shapes, m, s, part_matrix=None):
    """Draw shapes through matrix m (s = its rough scale, for stroke widths).

    part_matrix(shape) may return None to hide a shape, or a matrix applied before m.
    """
    for sh in shapes:
        pm = part_matrix(sh) if part_matrix else IDENT
        if pm is None:
            continue
        mm = mul(m, pm) if pm is not IDENT else m
        if sh.text:
            x, y = apply(mm, *sh.pts[0])
            canvas.create_text(x, y, text=sh.text[0], fill=sh.fill or "#000",
                               font=("Segoe UI", max(6, int(sh.text[1] * s * 0.75)), "bold"), anchor="s")
            continue
        flat = []
        for x, y in sh.pts:
            flat.extend(apply(mm, x, y))
        if len(flat) < 4:
            continue
        w = max(1, round(sh.width * s))
        if sh.fill and sh.closed and len(flat) >= 6:
            canvas.create_polygon(flat, fill=sh.fill, outline=sh.stroke or "", width=w if sh.stroke else 0)
        elif sh.stroke:
            if sh.closed:
                flat.extend(flat[:2])
            canvas.create_line(flat, fill=sh.stroke, width=w, dash=sh.dash or "",
                               capstyle="round" if sh.round else "butt", joinstyle="round")
