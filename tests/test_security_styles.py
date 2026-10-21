"""The style policy denies HTML style attributes without relaxing script nonces."""
from html.parser import HTMLParser
from pathlib import Path
import re

from test_core import browser, eve, new_id, sso_login  # noqa: F401


class Styles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline = []

    def handle_starttag(self, tag, attrs):
        if any(name == "style" for name, value in attrs):
            self.inline.append(tag)


def test_rendered_public_and_profile_pages_deny_style_attributes_and_use_unique_nonces(browser, eve):
    client = browser()
    nonces = set()
    for path in ("/", "/about", "/what-we-read", "/privacy", "/credits", "/releases"):
        response = client.get(path)
        assert response.status_code == 200
        policy = response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in policy and "'unsafe-hashes'" not in policy
        assert "style-src-attr 'none'" in policy
        script_nonce = re.search(r"script-src 'self' 'nonce-([^']+)'", policy)[1]
        assert f"style-src 'self' 'nonce-{script_nonce}'" in policy
        assert script_nonce not in nonces
        nonces.add(script_nonce)
        assert f'nonce="{script_nonce}"' in response.text
        parser = Styles()
        parser.feed(response.text)
        assert not parser.inline, (path, parser.inline)
    sso_login(client, eve, new_id(), "Fictional style pilot")
    parser = Styles()
    parser.feed(client.get("/profile").text)
    assert not parser.inline


def test_templates_and_generated_html_cannot_reintroduce_style_attributes():
    source = Path(__file__).resolve().parents[1] / "src" / "astracore"
    paths = list(source.rglob("*.html")) + list((source / "static" / "js").glob("*.js"))
    for path in paths:
        assert not re.search(r'\bstyle\s*=\s*["\x27]', path.read_text()), path
        assert not re.search(r'\.style\.cssText|setAttribute\(["\x27]style["\x27]', path.read_text()), path
