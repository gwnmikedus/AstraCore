"""Regenerates the AstraCore logo SVGs in this folder: `python3 docs/brand/logos/generate.py docs/brand/logos`.
The app copies live in src/astracore/static/img/ (favicon/mark = app icon, logo = wordmark on dark, modules/pi.svg on a void plate)
and src/astracore/templates/_logo.html (inline wordmark in currentColor)."""
import sys, os
out = sys.argv[1]
SIGNAL, INK_D, INK_L, VOID = "#ff6a1a", "#ece8df", "#17181a", "#0b0c0d"
OCT = "M6 6H44L58 20V58H20L6 44Z"                    # frame: 6-unit stroke, two 14-unit chamfers (top-right, bottom-left)
L = {  # 16 x 24 glyph cells, 4-unit strokes, 4-unit chamfers: the same geometry as the mark
 "A": "M2 24V7L7 2H9L14 7V24M2 14H14",
 "S": "M16 2H6L2 6V9L5 12H11L14 15V18L10 22H0",
 "T": "M0 2H16M8 2V24",
 "R": "M2 24V2H10L14 6V9L11 12H2M11 12L14 15V24",
 "C": "M16 2H6L2 6V18L6 22H16",
 "O": "M6 2H10L14 6V18L10 22H6L2 18V6Z",
 "E": "M16 2H2V22H16M2 12H12",
}
def svg(vb, body, label="AstraCore"):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="{label}">\n  {body}\n</svg>\n'
def mark(ink, core, bg=""):
    b = f'<rect width="64" height="64" fill="{bg}"/>' if bg else ""
    return f'{b}<path d="{OCT}" fill="none" stroke="{ink}" stroke-width="6" stroke-linejoin="miter"/>\n  <rect x="24" y="24" width="16" height="16" fill="{core}"/>'
def word(ink, core):
    s = []
    for i, ch in enumerate("ASTRACORE"):
        x = i * 21
        s.append(f'<path transform="translate({x} 0)" d="{L[ch]}"/>')
        if ch == "O":
            core_el = f'<rect x="{x+5.5}" y="9.5" width="5" height="5" fill="{core}"/>'
    return f'<g fill="none" stroke="{ink}" stroke-width="4" stroke-linejoin="miter">' + "".join(s) + "</g>\n  " + core_el
def pi(ink, core, cut):
    return (f'<path d="{OCT}" fill="none" stroke="{ink}" stroke-width="6" stroke-linejoin="miter"/>\n  '
            f'<circle cx="32" cy="32" r="9.5" fill="{core}"/>')
files = {
 "astracore-wordmark-on-dark.svg": svg("0 0 184 24", word(INK_D, SIGNAL)),
 "astracore-wordmark-on-light.svg": svg("0 0 184 24", word(INK_L, SIGNAL)),
 "astracore-wordmark-mono-dark.svg": svg("0 0 184 24", word(INK_L, INK_L)),
 "astracore-wordmark-mono-light.svg": svg("0 0 184 24", word(INK_D, INK_D)),
 "astracore-mark-on-dark.svg": svg("0 0 64 64", mark(INK_D, SIGNAL)),
 "astracore-mark-on-light.svg": svg("0 0 64 64", mark(INK_L, SIGNAL)),
 "astracore-app-icon.svg": svg("0 0 64 64", f'<rect width="64" height="64" fill="{VOID}"/><g transform="translate(12 12) scale(.625)">' + mark(INK_D, SIGNAL) + "</g>"),
 "astracore-pi-module-on-dark.svg": svg("0 0 64 64", pi(INK_D, SIGNAL, "#131517"), "AstraCore PI"),
 "astracore-pi-module-on-light.svg": svg("0 0 64 64", pi(INK_L, SIGNAL, "#f4f1ea"), "AstraCore PI"),
}
for n, t in files.items():
    open(os.path.join(out, n), "w").write(t)
