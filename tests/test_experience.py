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
