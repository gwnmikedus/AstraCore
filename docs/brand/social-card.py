"""Build the share-cover SVG from AstraCore fonts, tokens, and bundled EVE images.

Requires fonttools and brotli for the WOFF2 masters. Rasterize the SVG to
static/img/share-card.png with an SVG renderer after running this script.
"""
import base64
import json
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / 'src/astracore/static'
TOKENS = json.loads((ROOT / 'docs/brand/tokens.json').read_text())
COLORS = {token['name']: token['value']['hull'] for token in TOKENS['color']['tokens']
          if isinstance(token['value'], dict)}


def image(name, x, y, width, height):
    file = STATIC / 'img' / name
    mime = 'image/svg+xml' if file.suffix == '.svg' else 'image/png'
    encoded = base64.b64encode(file.read_bytes()).decode()
    return f'<image x="{x}" y="{y}" width="{width}" height="{height}" href="data:{mime};base64,{encoded}"/>'


def text(value, x, y, size, color, family='barlow-condensed-600'):
    font = TTFont(STATIC / 'fonts' / f'{family}.woff2')
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    scale = size / font['head'].unitsPerEm
    paths = []
    for char in value:
        glyph = cmap[ord(char)]
        pen = SVGPathPen(glyphs)
        glyphs[glyph].draw(pen)
        paths.append(f'<path transform="translate({x:.2f} {y}) scale({scale} {-scale})" d="{pen.getCommands()}"/>')
        x += font['hmtx'][glyph][0] * scale
    return f'<g fill="{color}">{"".join(paths)}</g>'


parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630"><title>AstraCore: Your planets. Your pace. One clear plan.</title><rect width="1200" height="630" fill="{COLORS["void"]}"/>']
parts.append(image('logo.svg', 60, 48, 246, 32))
parts.append(text('PI / PLANETARY OPERATIONS', 60, 147, 16, COLORS['signal']))
for value, y, color in [('Your planets.', 244, 'ink'), ('Your pace.', 334, 'ink'), ('One clear plan.', 424, 'ink-muted')]:
    parts.append(text(value, 60, y, 88, COLORS[color]))
parts.append(text('Every alt. One operation.', 60, 484, 24, COLORS['ink'], 'barlow-400'))
parts.append(text('PLAN / BUILD / OPERATE', 60, 563, 16, COLORS['ink-muted'], 'ibm-plex-mono-400'))
parts.append(f'<path d="M668 108H1120L1144 132V524H692L668 500Z" fill="{COLORS["hull"]}" stroke="{COLORS["line"]}"/>')
parts.append(f'<g fill="none" stroke="{COLORS["line"]}"><circle cx="906" cy="316" r="164"/><circle cx="906" cy="316" r="104"/><path d="M668 316H1144M906 108V524"/></g>')
parts.append(f'<path d="M776 215L906 316L1042 205M906 316L1036 436M906 316L780 433" fill="none" stroke="{COLORS["line-strong"]}"/>')
for name, x, y in [('11-planet-temperate', 734, 164), ('2015-planet-lava', 1002, 156), ('2016-planet-barren', 998, 397), ('2014-planet-oceanic', 740, 392)]:
    parts.append(image(f'eve/pi/planets/{name}.png', x, y, 80, 80))
parts.append(image('mark.svg', 868, 278, 76, 76))
parts.append(text('MANY COLONIES. ONE CORE.', 718, 572, 15, COLORS['ink-muted'], 'ibm-plex-mono-400'))
parts.append('</svg>')
(ROOT / 'docs/brand/social-card.svg').write_text(''.join(parts))
print('Built docs/brand/social-card.svg (1200 × 630).')
