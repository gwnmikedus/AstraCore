"""The public introduction remains accessible without disturbing a pilot's session."""
from test_core import browser, eve, me, new_id, sso_login  # noqa: F401


def test_public_introduction_without_login(browser):
    client = browser()
    response = client.get("/about")
    assert response.status_code == 200
    assert 'data-pi-preview' in response.text
    assert 'href="/auth/login" class="primary-link"' in response.text


def test_introduction_keeps_signed_in_profile_and_links_to_pi(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "Explorer")
    profile_id = me(client)
    response = client.get("/about")
    assert response.status_code == 200
    assert 'href="/pi" class="primary-link"' in response.text
    assert me(client) == profile_id
    assert client.get("/", follow_redirects=False).headers["location"] == "/welcome"


def test_public_navigation_is_available_on_every_information_page(browser):
    client = browser()
    for path in ("/", "/about", "/what-we-read", "/privacy", "/credits"):
        response = client.get(path)
        assert response.status_code == 200
        header = response.text.split('<header class="topbar site-header">')[1].split('</header>')[0]
        for href in ("/", "/about#preview", "/what-we-read", "/privacy", "/credits", "/auth/login"):
            assert f'href="{href}"' in header
        assert 'aria-controls="site-navigation"' in header
        assert 'href="/profile"' not in header
        assert '/auth/logout' not in header


def test_signed_in_navigation_keeps_operation_and_account_actions_on_public_pages(browser, eve):
    client = browser()
    sso_login(client, eve, new_id(), "Navigator")
    profile_id = me(client)
    for path in ("/about", "/what-we-read"):
        response = client.get(path)
        assert response.status_code == 200
        header = response.text.split('<header class="topbar site-header">')[1].split('</header>')[0]
        for href in ("/pi/operate", "/pi/plan", "/pi/area", "/pi/settings", "/profile"):
            assert f'href="{href}"' in header
        assert 'method="post" action="/auth/logout"' in header
        assert 'name="csrf_token"' in header
        assert 'href="/auth/login"' not in header
    assert me(client) == profile_id


class OutboundLinks:
    """Inspect rendered links without relying on a particular template layout."""

    @staticmethod
    def parse(html):
        from html.parser import HTMLParser

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'a':
                    self.current = {'attrs': attrs, 'indicators': 0, 'symbols': [], 'text': ''}
                    self.links.append(self.current)
                elif self.current and tag == 'svg':
                    classes = attrs.get('class', '').split()
                    self.current['indicators'] += 'external-indicator' in classes
                    self.current['symbols'].extend(classes)

            def handle_endtag(self, tag):
                if tag == 'a':
                    self.current = None

            def handle_data(self, text):
                if self.current:
                    self.current['text'] += text

        parser = Parser()
        parser.feed(html)
        return parser.links


def test_outbound_links_have_one_indicator_and_accurate_new_tab_labels(browser):
    client = browser()
    for path in ('/', '/project', '/credits', '/roadmap', '/releases', '/feedback'):
        response = client.get(path)
        assert response.status_code == 200
        links = OutboundLinks.parse(response.text)
        external = [link for link in links if link['attrs']['href'].startswith('https://')]
        assert external
        for link in external:
            assert link['indicators'] == 1, (path, link['attrs']['href'])
            assert 'external site' in link['text']
            if link['attrs'].get('target') == '_blank':
                assert {'noopener', 'noreferrer'} <= set(link['attrs']['rel'].split())
                assert 'opens in a new tab' in link['text']
            else:
                assert 'opens in a new tab' not in link['text']
            if link['attrs']['href'].startswith('https://github.com/'):
                assert 'icon-github' in link['symbols']
        assert all(link['indicators'] == 0 for link in links if link['attrs']['href'].startswith('/'))


def test_feedback_routes_have_distinct_idea_and_bug_icons(browser):
    links = OutboundLinks.parse(browser().get('/project').text)
    for kind, symbol in (('idea', 'lightbulb'), ('bug', 'bug')):
        actions = [link for link in links if link['attrs']['href'] == f'/feedback?kind={kind}']
        assert actions
        assert any(f'icon-{symbol}' in link['symbols'] for link in actions)


def test_icon_library_is_generated_and_contains_the_new_symbols():
    from astracore.core import icons

    assert (icons.ICON_DIR.parent / 'js/icons.js').read_text() == icons.build_js()
    for name in ('github', 'bug', 'coffee', 'server'):
        assert '<path' in icons.svg(name) or '<rect' in icons.svg(name)


def test_feedback_menu_marks_only_the_selected_report_kind(browser):
    client = browser()
    for kind in ('idea', 'bug'):
        links = OutboundLinks.parse(client.get(f'/feedback?kind={kind}').text)
        current = [link['attrs']['href'] for link in links if link['attrs'].get('aria-current') == 'page']
        assert current == [f'/feedback?kind={kind}']
