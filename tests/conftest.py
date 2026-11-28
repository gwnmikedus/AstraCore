import asyncio
import os
import tempfile

import pytest

# Isolated data and env for tests - never touch the real data/ directory or the real .env files.
_tmp = tempfile.mkdtemp(prefix="astracore_test_")
os.environ["ASTRACORE_MODE"] = "local"
os.environ["ASTRACORE_DATA"] = _tmp
os.environ["ASTRACORE_ENV_FILE"] = os.path.join(_tmp, ".env.test")
os.environ["ASTRACORE_STATIC_DATA"] = os.path.join(_tmp, "static")
os.environ["ASTRACORE_PUBLIC_URL"] = "http://testserver"
os.environ["EVE_CLIENT_ID"] = "test-client"
os.environ["EVE_CLIENT_SECRET"] = "test-secret"
os.environ["ASTRACORE_TOKEN_KEY"] = "LzXbW8vH3sYv0vY3t0X8m3N2yQ0Zq1b8m7k6l5j4h3g="
os.environ["ASTRACORE_SESSION_SECRET"] = "test-session-secret"
os.environ["ASTRACORE_ADMIN_CHARACTER_IDS"] = "90000001"

from astracore import db  # noqa: E402

db.init()

import astracore.modules.pi.module  # noqa: E402,F401  (registers AstracorePI)


@pytest.fixture(autouse=True)
def isolated_request_limits():
    from astracore.core.ratelimit import LIMITER

    LIMITER.clear()
    yield
    LIMITER.clear()


@pytest.fixture(autouse=True)
def isolated_community_worker(monkeypatch):
    from astracore.core import community

    async def idle():
        await asyncio.Event().wait()

    # API behavior is exercised explicitly with mocked transports, never a live repository.
    monkeypatch.setattr(community, "run_sync_loop", idle)
    for field in ("APP_ID", "INSTALLATION_ID", "PRIVATE_KEY_PATH", "WEBHOOK_SECRET", "TOKEN"):
        monkeypatch.setenv(f"ASTRACORE_GITHUB_{field}", "")


@pytest.fixture(autouse=True)
def isolated_market_history(monkeypatch):
    from astracore.modules.pi import service

    async def idle():
        return None

    # The startup warm-up of regional trade history calls ESI; tests never reach the network.
    monkeypatch.setattr(service, "warm_history", idle)


@pytest.fixture(autouse=True)
def all_courier_providers(monkeypatch):
    """Planner tests run with every courier provider active (including VOC's Delve routes and buyback), so they
    don't depend on which provider a deployment uses. Tests of the defaults set `config.COURIERS` themselves."""
    from astracore import config

    monkeypatch.setattr(config, "COURIERS", ["humpback", "voc"])


@pytest.fixture(autouse=True)
def offline_courier_tariffs(monkeypatch):
    """Courier tariffs are never read from the providers' sites in tests: every request fails, so the cached or
    fallback routes stay in use. Tests of the refresh itself install their own mock transport."""
    import httpx

    from astracore.modules.pi.static_data import carrier

    def unreachable(request):
        raise httpx.ConnectError("tests never reach courier sites", request=request)

    monkeypatch.setattr(carrier, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(unreachable)))


@pytest.fixture(autouse=True)
def home_regions_include_delve(monkeypatch):
    """Planner tests use Delve systems (VOC's pickups) as a local drop-off: count Delve as a home region too.
    Tests of the default home regions set `config.HOME_REGIONS` themselves."""
    from astracore import config

    monkeypatch.setattr(config, "HOME_REGIONS", ["Paragon Soul", "Esoteria", "Delve"])


@pytest.fixture(autouse=True)
def offline_affiliations(monkeypatch):
    """Area loads and profile refreshes read every character's alliance from ESI (#298); tests never reach it.
    Tests of that refresh put `REAL_REFRESH_AFFILIATIONS` back and answer it with a fake ESI."""
    from astracore.esi import character

    async def unchanged(esi, characters):
        return []

    monkeypatch.setattr(character, "refresh_affiliations", unchanged)


from astracore.esi.character import refresh_affiliations as REAL_REFRESH_AFFILIATIONS  # noqa: E402,F401
