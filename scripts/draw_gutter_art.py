"""Draw AstraCore's gutter art: tall space line drawings for the side margins of wide screens.

Writes src/astracore/templates/_gutter_art.html. Run it again after changing a drawing:

    python scripts/draw_gutter_art.py

The drawings are AstraCore's own (no stock, traced or generated art). They use the same classes as the
small doodles (templates/_doodles.html): ink strokes, `d-fill` bodies, `d-soft` shading and hatching,
`d-star`/`d-dot` stars and `d-core`/`d-beam` for the one warm accent, so both themes and print follow.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "astracore" / "templates" / "_gutter_art.html"
W, H = 280, 400


def f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def pts(points) -> str:
    return " ".join(f"{f(x)},{f(y)}" for x, y in points)


def star(x, y, s, cls="d-star"):
    a = s * .22
    return (f"<path class='{cls}' d='M{f(x)} {f(y - s)}L{f(x + a)} {f(y - a)}L{f(x + s)} {f(y)}L{f(x + a)} {f(y + a)}"
            f"L{f(x)} {f(y + s)}L{f(x - a)} {f(y + a)}L{f(x - s)} {f(y)}L{f(x - a)} {f(y - a)}Z'/>")


def dot(x, y, r=1.3):
    return f"<circle class='d-dot' cx='{f(x)}' cy='{f(y)}' r='{f(r)}'/>"


def starfield(seed, count, avoid=()):
    """Scattered dots and a few sparkles, kept out of the given (x, y, r) circles."""
    rnd = random.Random(seed)
    out = []
    while len(out) < count:
        x, y = rnd.uniform(8, W - 8), rnd.uniform(8, H - 8)
        if any(math.hypot(x - ax, y - ay) < ar for ax, ay, ar in avoid):
            continue
        roll = rnd.random()
        out.append(star(x, y, rnd.choice((3, 4, 5, 6))) if roll < .22 else dot(x, y, rnd.choice((1, 1.3, 1.6))))
    return "".join(out)


def hatch(clip_id, clip_shape, cx, cy, r, start=.3, step=6.0, angle=45):
    """Diagonal shading lines over the far side of a body, clipped to its shape."""
    a = math.radians(angle)
    n = (math.cos(a), math.sin(a))          # towards the shadow
    d = (-n[1], n[0])                       # along each line
    lines = []
    t = start * r
    while t < r:
        h = math.sqrt(max(r * r - t * t, 0)) + 2
        px, py = cx + n[0] * t, cy + n[1] * t
        lines.append(f"M{f(px - d[0] * h)} {f(py - d[1] * h)}L{f(px + d[0] * h)} {f(py + d[1] * h)}")
        t += step
    return (f"<clipPath id='{clip_id}'>{clip_shape}</clipPath>"
            f"<path class='d-soft' clip-path='url(#{clip_id})' d='{''.join(lines)}'/>")


def ellipse_point(cx, cy, rx, ry, rot, deg):
    t, r = math.radians(deg), math.radians(rot)
    x, y = rx * math.cos(t), ry * math.sin(t)
    return cx + x * math.cos(r) - y * math.sin(r), cy + x * math.sin(r) + y * math.cos(r)


def rock(seed, cx, cy, r, jag=.28, n=9):
    rnd = random.Random(seed)
    return [(cx + math.cos(2 * math.pi * i / n) * r * (1 - rnd.uniform(0, jag)),
             cy + math.sin(2 * math.pi * i / n) * r * (1 - rnd.uniform(0, jag))) for i in range(n)]


def small_ship(x, y, s=1.0, rot=0, core=False):
    """A compact frigate pointing up, with a plated hull and twin fins."""
    body = (f"<g transform='translate({f(x)} {f(y)}) rotate({f(rot)}) scale({s})'>"
            "<path d='M-10 8L-18 18L-14 20L-6 14M10 8L18 18L14 20L6 14'/>"
            "<path class='d-fill' d='M0 -26L8 -8L9 14L4 20H-4L-9 14L-8 -8Z'/>"
            "<path class='d-soft' d='M-8 -6H8M-9 6H9M0 -18V18'/>")
    tail = "<rect class='d-core' x='-3' y='20' width='6' height='4'/>" if core else "<path d='M-3 22H3'/>"
    return body + tail + "</g>"


def poco():
    cx, cy, r = 150, 276, 96
    rot, rx, ry = -14, 122, 30
    planet = f"<circle cx='{cx}' cy='{cy}' r='{r}'/>"
    bands = "".join(
        f"<path class='d-soft' d='M{f(cx - math.sqrt(r * r - dy * dy))} {f(cy + dy)}Q{cx} {f(cy + dy + 14)} "
        f"{f(cx + math.sqrt(r * r - dy * dy))} {f(cy + dy)}'/>" for dy in (-58, -22, 14, 52))
    craters = "".join(f"<ellipse class='d-soft' cx='{x}' cy='{y}' rx='{a}' ry='{b}'/>"
                      for x, y, a, b in ((112, 236, 10, 6), (132, 262, 5, 3), (96, 290, 7, 4), (166, 224, 4, 2.5)))
    px, py = ellipse_point(cx, cy, rx, ry, rot, 212)
    office = (f"<g transform='translate({f(px)} {f(py)})'>"
              "<path d='M-24 0H-14M14 0H24M0 -14V-26'/>"
              "<path class='d-fill' d='M-36 -6H-24V6H-36ZM24 -6H36V6H24Z'/>"
              "<path class='d-soft' d='M-30 -6V6M30 -6V6'/>"
              "<path class='d-fill' d='M-6 -14H6L14 -6V6L6 14H-6L-14 6V-6Z'/>"
              "<path class='d-soft' d='M-8 0H8M0 -8V8'/>"
              "<circle class='d-core' cx='0' cy='-28' r='3.2'/></g>")
    moon = (f"<circle class='d-fill' cx='222' cy='74' r='18'/>"
            + hatch("ga-poco-moon", "<circle cx='222' cy='74' r='18'/>", 222, 74, 18, .1, 4)
            + "<circle cx='222' cy='74' r='18'/><ellipse class='d-soft' cx='215' cy='68' rx='4' ry='3'/>")
    hauler = (small_ship(88, 120, 1.0, 200)
              + "<path class='d-soft' stroke-dasharray='2 6' d='M96 96Q112 40 150 18'/>")
    return "".join([
        starfield(11, 34, ((cx, cy, r + 14), (222, 74, 26), (88, 120, 30))),
        f"<g transform='rotate({rot} {cx} {cy})'><ellipse stroke-dasharray='5 6' cx='{cx}' cy='{cy}' rx='{rx}' ry='{ry}'/></g>",
        f"<circle class='d-soft' stroke-dasharray='1 5' cx='{cx}' cy='{cy}' r='{r + 8}'/>",
        f"<circle class='d-fill' cx='{cx}' cy='{cy}' r='{r}'/>", bands, craters,
        hatch("ga-poco-planet", planet, cx, cy, r, .28, 6.5), planet,
        f"<g transform='rotate({rot} {cx} {cy})'><path d='M{cx - rx} {cy}A{rx} {ry} 0 0 0 {cx + rx} {cy}'/></g>",
        office, moon, hauler])


def stargate():
    cx, cy = 140, 172
    ticks = []
    for i in range(0, 360, 12):
        a = math.radians(i)
        x1, y1 = cx + 72 * math.cos(a), cy + 104 * math.sin(a)
        x2, y2 = cx + 86 * math.cos(a), cy + 122 * math.sin(a)
        ticks.append(f"M{f(x1)} {f(y1)}L{f(x2)} {f(y2)}")
    pylons = []
    for deg in (45, 135, 225, 315):
        a = math.radians(deg)
        x1, y1 = cx + 86 * math.cos(a), cy + 122 * math.sin(a)
        x2, y2 = cx + 116 * math.cos(a), cy + 156 * math.sin(a)
        pylons.append(f"<path d='M{f(x1)} {f(y1)}L{f(x2)} {f(y2)}'/>"
                      f"<rect class='d-fill' x='{f(x2 - 9)}' y='{f(y2 - 6)}' width='18' height='12' transform='rotate({deg} {f(x2)} {f(y2)})'/>")
    swirl = "".join(f"<ellipse class='d-soft' stroke-dasharray='{d}' cx='{cx}' cy='{cy}' rx='{rx}' ry='{f(rx * 1.42)}'/>"
                    for rx, d in ((56, '3 5'), (40, '2 6'), (26, '6 4'), (13, '2 3')))
    return "".join([
        starfield(23, 36, ((cx, cy, 150), (140, 352, 30))),
        f"<ellipse class='d-fill' cx='{cx}' cy='{cy}' rx='86' ry='122'/>",
        f"<ellipse cx='{cx}' cy='{cy}' rx='86' ry='122'/>",
        f"<ellipse class='d-fill' cx='{cx}' cy='{cy}' rx='72' ry='104'/>",
        f"<ellipse cx='{cx}' cy='{cy}' rx='72' ry='104'/>",
        f"<path class='d-soft' d='{''.join(ticks)}'/>", "".join(pylons), swirl,
        f"<ellipse class='d-core' cx='{cx}' cy='{cy}' rx='5' ry='7'/>",
        small_ship(140, 352, 1.15, 0),
        "<path class='d-soft' d='M134 380V396M146 380V396M140 384V400'/>"])


def miner():
    rocks = [(1, 84, 92, 52), (2, 200, 62, 30), (3, 214, 150, 22), (4, 40, 190, 16)]
    out = [starfield(37, 30, tuple((x, y, r + 14) for _, x, y, r in rocks) + ((150, 300, 90),))]
    for seed, x, y, r in rocks:
        shape = f"<polygon points='{pts(rock(seed, x, y, r))}'/>"
        out.append(f"<polygon class='d-fill' points='{pts(rock(seed, x, y, r))}'/>")
        out.append(hatch(f"ga-miner-{seed}", shape, x, y, r, .2, 5.5))
        out.append(shape)
        rnd = random.Random(seed * 7)
        for _ in range(max(1, r // 14)):
            out.append(f"<ellipse class='d-soft' cx='{f(x + rnd.uniform(-r * .4, r * .2))}' cy='{f(y + rnd.uniform(-r * .4, r * .2))}' "
                       f"rx='{f(r * .16)}' ry='{f(r * .1)}'/>")
    for i, (x, y) in enumerate(((132, 168), (150, 190), (118, 204))):
        out.append(f"<polygon class='d-fill' points='{pts(rock(40 + i, x, y, 4, .3, 6))}'/>")
    barge = ("<g transform='translate(150 306) rotate(-24)'>"
             "<path d='M-40 -18L-58 -52M-10 -22L-14 -60'/>"
             "<path class='d-fill' d='M-62 -60H-50V-48H-62ZM-20 -68H-8V-56H-20Z'/>"
             "<path class='d-fill' d='M-70 -10L-40 -26H44L76 -10L80 12L44 26H-40L-74 14Z'/>"
             "<path class='d-soft' d='M-40 -26V26M0 -26V26M44 -26V26M-70 2H78'/>"
             "<path class='d-fill' d='M76 -12L96 -6V8L78 12Z'/>"
             "<path d='M-74 -6H-86M-74 8H-86'/>"
             "<rect class='d-core' x='-92' y='-1' width='6' height='5'/></g>")
    beams = "<path class='d-beam' d='M139 250L103 128M161 246L113 116'/>"
    return "".join(out) + beams + barge


def station():
    cx = 140
    panels = ""
    for x0 in (34, 176):
        cells = "".join(f"M{x0 + i * 14} 76V104" for i in range(1, 5)) + f"M{x0} 90H{x0 + 70}"
        panels += f"<path class='d-fill' d='M{x0} 76H{x0 + 70}V104H{x0}Z'/><path class='d-soft' d='{cells}'/>"
    windows = "".join(f"<rect class='d-dot' x='{x}' y='{y}' width='3' height='3'/>"
                      for x, y in ((128, 160), (138, 160), (148, 160), (128, 236), (148, 236), (138, 300)))
    return "".join([
        starfield(51, 32, ((cx, 200, 120),)),
        f"<path d='M{cx} 22V380'/>",
        f"<path d='M{cx - 6} 30L{cx} 18L{cx + 6} 30M{cx - 14} 46H{cx + 14}M{cx - 9} 38H{cx + 9}'/>",
        "<path d='M104 90H176'/>", panels,
        f"<ellipse cx='{cx}' cy='196' rx='104' ry='26'/>",
        f"<path class='d-fill' d='M{cx - 22} 130H{cx + 22}L{cx + 30} 150V250L{cx + 22} 268H{cx - 22}L{cx - 30} 250V150Z'/>",
        f"<path class='d-soft' d='M{cx - 30} 172H{cx + 30}M{cx - 30} 220H{cx + 30}M{cx - 14} 130V268M{cx + 14} 130V268'/>",
        f"<path d='M36 196A104 26 0 0 0 244 196'/>",
        f"<path class='d-soft' d='M48 196A92 18 0 0 0 232 196'/>",
        f"<path class='d-fill' d='M{cx - 16} 284H{cx + 16}V330H{cx - 16}Z'/>",
        f"<path class='d-soft' d='M{cx - 16} 300H{cx + 16}M{cx - 16} 315H{cx + 16}'/>",
        f"<path d='M{cx - 34} 360Q{cx} 336 {cx + 34} 360'/>",
        windows, f"<circle class='d-core' cx='{cx}' cy='14' r='3.5'/>",
        small_ship(222, 300, .8, -40),
        "<path class='d-soft' stroke-dasharray='2 6' d='M210 290Q180 262 172 236'/>"])


def fleet():
    ships = [(186, 96, 1.1, True), (120, 196, .95, False), (200, 262, .8, False)]
    out = [starfield(67, 30, tuple((x, y, 60) for x, y, _, _ in ships))]
    angle = 210
    for x, y, s, core in ships:
        a = math.radians(angle - 180)
        for off, length in ((-6, 120), (0, 170), (6, 110)):
            ox, oy = -math.sin(a) * off * s, math.cos(a) * off * s
            sx, sy = x + math.cos(a) * 26 * s + ox, y + math.sin(a) * 26 * s + oy
            ex, ey = sx + math.cos(a) * length * s, sy + math.sin(a) * length * s
            cls = " class='d-soft'" if off else ""
            out.append(f"<path{cls} d='M{f(sx)} {f(sy)}L{f(ex)} {f(ey)}'/>")
        out.append(small_ship(x, y, s * 1.5, angle - 270, core))
    return "".join(out)


ART = {"poco": poco, "stargate": stargate, "miner": miner, "station": station, "fleet": fleet}


def render() -> str:
    lines = ["{# Gutter art: AstraCore's own tall space line drawings for the side margins of wide screens.",
             "   GENERATED by scripts/draw_gutter_art.py; edit the drawings there. Decorative only: aria-hidden,",
             "   colours from the --doodle-* tokens and --signal, so both themes and print follow. #}",
             "{% macro gutter_art(name, side='right') -%}",
             "<div class=\"gutter-art gutter-art--{{ side }}\" aria-hidden=\"true\">"]
    for i, (name, draw) in enumerate(ART.items()):
        lines.append(f"{{%- {'if' if i == 0 else 'elif'} name == '{name}' -%}}"
                     f"<svg class=\"doodle doodle--{name}\" viewBox=\"0 0 {W} {H}\" focusable=\"false\">{draw()}</svg>")
    lines += ["{%- endif -%}", "</div>", "{%- endmacro %}", ""]
    return "\n".join(lines)


def main():
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT}")


if __name__ == "__main__":
    main()
