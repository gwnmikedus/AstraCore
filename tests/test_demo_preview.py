"""The screenshot runner must stay isolated from any existing instance."""
import os
from pathlib import Path
import subprocess
import sys


def test_fictional_demo_is_isolated_and_disables_live_actions():
    script = Path(__file__).resolve().parents[1] / "scripts" / "demo_preview.py"
    code = '''
import importlib.util, os, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("demo_preview", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
with tempfile.TemporaryDirectory() as tmp:
    os.environ["ASTRACORE_MODE"] = "production"
    os.environ["EVE_CLIENT_ID"] = "must-not-be-read"
    demo.isolated_environment(Path(tmp), 19115)
    app = demo.create_demo()
    from astracore import config, db
    assert not config.PRODUCTION
    assert config.HOME == Path(tmp).resolve()
    assert config.env("EVE_CLIENT_ID") == ""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        for scene in ("characters", "area", "question", "result", "operate"):
            r = c.get("/demo/" + scene)
            assert r.status_code == 200, (scene, r.text)
            assert "FICTIONAL DEMO" in r.text
            assert "https://images.evetech.net/characters/" not in r.text
        assert "Demo Pilot Aurora" in c.get("/demo/characters").text
        assert "Demo Harbour" in c.get("/demo/area").text
        assert c.get("/auth/login").status_code == 403
        assert c.get("/pi/export/templates.zip").status_code == 403
        assert c.post("/pi/api/save", json={"effort":100}).status_code == 200
        from astracore.modules.pi import store
        assert store.load_settings(1).effort == 50
        assert c.post("/pi/api/plan/save", json={}).status_code == 403
        r = c.post("/pi/api/suggest", json={})
        assert r.status_code == 200 and r.json()["templates_needed"] == []
        assert "Fictional summary" in r.json()["warnings"][0]["text"]
        with db.session() as sql:
            assert sql.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 0
            assert all(row[0] < 0 for row in sql.execute("SELECT character_id FROM characters"))
'''.replace("SCRIPT", repr(str(script)))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(script.parent.parent / "src")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
