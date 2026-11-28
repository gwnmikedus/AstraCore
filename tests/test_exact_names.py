"""Character, corporation and alliance names keep EVE's exact spelling.

Uppercasing a name makes look-alikes impossible to tell apart: `C0smicCarrot` (zero) and `CosmicCarrot` (letter O)
both become `C0SMICCARROT`/`COSMICCARROT`. Decorative uppercase labels may surround a name, but the name itself sits
in a `.eve-name` element, which switches the transform off.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from astracore import db
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401

ROOT = Path(__file__).resolve().parents[1] / "src" / "astracore"
CSS_FILES = sorted((ROOT / "static" / "css").glob("*.css"))
TEMPLATES = sorted([*(ROOT / "templates").rglob("*.html"), *(ROOT / "modules").rglob("*.html")])
SCRIPTS = sorted(p for p in (ROOT / "static" / "js").glob("*.js") if not p.name.startswith("hero-film"))

# A Jinja `{{ … }}` or JS `${ … }` interpolation of something that is (or may be) an EVE name.
NAME_EXPR = re.compile(r"(?:\{\{|\$\{)(?:(?!\}\}|\}).)*?\b(?:display_name|name|names|character|characters|corp|"
                       r"corporation|corporation_name|corp_name|alliance|alliance_name|pilot|seller|credit)\b", re.S)
# Interpolations that match the pattern above but are never an EVE character, corporation or alliance name.
NOT_EVE_NAMES = re.compile(r"\b(?:m|module|t\.module|tool|project|b\.bundle|bundle|sc|scope)\.(?:name|title|license_name)\b")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --------------------------------------------------------------------------- the CSS that uppercases text
def _rules():
    for path in CSS_FILES:
        css = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            yield path.name, [s.strip() for s in selectors.split(",") if s.strip()], body


def _compound(text):
    """`a.outline[role="button"]:hover` → (tag, classes, attributes); pseudo-classes are ignored."""
    text = re.sub(r"::?[\w-]+(\([^)]*\))?", "", text)
    tag = re.match(r"[a-z][\w-]*|\*", text)
    attrs = dict((k, v) for k, v in re.findall(r'\[([\w-]+)(?:="?([^"\]]*)"?)?\]', text))
    return (tag.group(0) if tag and tag.group(0) != "*" else None, set(re.findall(r"\.([\w-]+)", text)),
            set(re.findall(r"#([\w-]+)", text)), attrs)


def _uppercase_selectors():
    out = []
    for name, selectors, body in _rules():
        if re.search(r"text-transform\s*:\s*uppercase|font-variant(?:-caps)?\s*:\s*(?:all-)?small-caps", body):
            for sel in selectors:
                if "@" in sel or sel.startswith(("from", "to")) or "%" in sel:
                    continue
                out.append((name, sel, [_compound(c) for c in re.split(r"\s*[> +~]\s*|\s+", sel) if c]))
    return out


UPPERCASE = _uppercase_selectors()


def _matches(compound, element):
    tag, classes, ids, attrs = compound
    etag, eattrs = element
    eclasses = set((eattrs.get("class") or "").split())
    if tag and tag != etag:
        return False
    if not classes <= eclasses or (ids and eattrs.get("id") not in ids):
        return False
    for key, value in attrs.items():
        if key not in eattrs or (value and eattrs[key] != value):
            return False
    return True


def _selector_matches(compounds, stack, index):
    """Does the selector match stack[index], with its earlier compounds on ancestors (descendant semantics)?"""
    if not _matches(compounds[-1], stack[index]):
        return False
    want, i = len(compounds) - 2, index - 1
    while want >= 0 and i >= 0:
        if _matches(compounds[want], stack[i]):
            want -= 1
        i -= 1
    return want < 0


class _Scanner(HTMLParser):
    """Tracks open elements; reports name interpolations whose rendered text would be uppercased."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.problems = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        for m in NAME_EXPR.finditer(data):
            if NOT_EVE_NAMES.search(m.group(0)):
                continue
            # The nearest element that sets the transform decides: `.eve-name` resets it to none.
            for i in range(len(self.stack) - 1, -1, -1):
                if "eve-name" in (self.stack[i][1].get("class") or "").split():
                    break
                hit = next((sel for _, sel, comps in UPPERCASE if _selector_matches(comps, self.stack, i)), None)
                if hit:
                    self.problems.append(f"line {self.getpos()[0]}: {m.group(0)[:60]!r} inside `{hit}`")
                    break


def _scan(text):
    scanner = _Scanner()
    scanner.feed(text)
    return scanner.problems


def test_the_scanner_knows_which_rules_uppercase_text():
    selectors = {sel for _, sel, _ in UPPERCASE}
    assert {"button", "th", ".eyebrow", ".pill", ".header-action"} <= selectors
    assert _scan('<a class="header-action"><span>{{ user.display_name }}</span></a>')
    assert _scan('<button class="outline">Log in as {{ c.name }}</button>')
    assert _scan("<div class='card'><div class=\"l\">${esc(ch.name)}</div></div>")
    assert not _scan('<a class="header-action"><span class="eve-name">{{ user.display_name }}</span></a>')
    assert not _scan('<p>Welcome back, {{ user.display_name }}.</p>')
    assert not _scan('<button>Open {{ m.name }}</button>')


def test_the_name_class_switches_uppercase_off():
    bodies = [body for _, selectors, body in _rules() if ".eve-name" in selectors]
    assert bodies, "astracore.css defines .eve-name"
    assert all(re.search(r"text-transform\s*:\s*none", b) for b in bodies)
    for name, selectors, body in _rules():
        if any("eve-name" in s for s in selectors):
            assert not re.search(r"text-transform\s*:\s*(?:uppercase|capitalize|lowercase)|small-caps", body), name


@pytest.mark.parametrize("path", TEMPLATES + SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_name_is_rendered_inside_uppercase_styling(path):
    text = path.read_text()
    parts = [text] if path.suffix == ".js" else [text, *re.findall(r"<script[^>]*>(.*?)</script>", text, re.S)]
    problems = [p for part in parts for p in _scan(part)]
    assert not problems, f"{path.name}: wrap the name in <span class=\"eve-name\">: " + "; ".join(problems)


@pytest.mark.parametrize("path", TEMPLATES + SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_names_are_never_case_converted_in_code(path):
    text = path.read_text()
    jinja = re.findall(r"\{\{[^}]*\b(?:name|character|corp\w*|alliance\w*|pilot)\b[^}]*\|\s*(?:upper|title|capitalize)\b",
                       text)
    js = re.findall(r"\b(?:name|character|corp\w*|alliance\w*|pilot)\w*\)?\.(?:toUpperCase|toLocaleUpperCase)\(",
                    text, re.I)
    assert not jinja and not js, (jinja, js)


def test_python_never_case_converts_names():
    offenders = []
    for path in ROOT.rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\b(?:\w*_name|name|display_name|corp\w*|alliance\w*)\b(?:\[[^\]]*\])?\.(?:upper|title|capitalize|"
                         r"swapcase)\(\)", line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, offenders


# --------------------------------------------------------------------------- rendered pages
def test_header_and_menu_show_the_exact_character_name(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "C0smicCarrot")
    db.update_profile(me(client), onboarded=1)
    html = client.get("/profile").text
    assert '<span class="eve-name">C0smicCarrot</span>' in html
    assert "Signed in as <strong>C0smicCarrot</strong>" in html
    assert 'aria-label="Your profile: C0smicCarrot"' in html
    assert "C0SMICCARROT" not in html


def test_look_alike_characters_stay_distinct_on_the_connect_page(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "C0smicCarrot", scopes="")
    sso_login(client, eve, new_id(), "CosmicCarrot", path="/auth/login?intent=add", scopes="")
    html = client.get("/pi").text
    assert 'Log in as <span class="eve-name">C0smicCarrot</span>' in html
    assert 'Log in as <span class="eve-name">CosmicCarrot</span>' in html
    assert "C0SMICCARROT" not in html and "COSMICCARROT" not in html
