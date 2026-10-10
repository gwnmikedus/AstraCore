import os
import tempfile

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
