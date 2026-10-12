"""Offline launcher lifecycle checks against disposable services, never production."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Synthetic service did not reach the expected state")


def executable(path, text):
    path.write_text(text)
    path.chmod(0o700)


@pytest.mark.skipif(os.name != "posix", reason="The Bash launcher manages POSIX processes")
@pytest.mark.parametrize("tunnel_launch_fails", [False, True])
def test_app_and_tunnel_outlive_terminated_invoking_session_and_stop_cleanly(tmp_path, tunnel_launch_fails):
    home = tmp_path / "synthetic-home"
    code = tmp_path / "synthetic-pinned-code"
    home.mkdir()
    code.mkdir()
    (home / ".venv/bin").mkdir(parents=True)
    (home / ".venv/bin/python").symlink_to(sys.executable)
    (home / "scripts").mkdir()
    shutil.copy(ROOT / "astracore", home / "astracore")
    shutil.copy(ROOT / "scripts/launch_service.py", home / "scripts/launch_service.py")
    package = code / "src/astracore"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "ops.py").write_text("# Synthetic no-op: no migrations, secrets or database.\n")
    service = '''import json, os, signal, sys, time
from pathlib import Path
kind = sys.argv[1] if len(sys.argv) > 1 else "app"
home = Path(os.environ["ASTRACORE_HOME"])
record = {"pid": os.getpid(), "session": os.getsid(0), "cwd": os.getcwd(),
          "mode": os.environ.get("ASTRACORE_MODE"), "stdin": sys.stdin.read(),
          "token_in_environment": bool(os.environ.get("TUNNEL_TOKEN"))}
temporary = home / (kind + ".json.tmp")
temporary.write_text(json.dumps(record))
temporary.replace(home / (kind + ".json"))
print(kind + " synthetic stdout", flush=True)
print(kind + " synthetic stderr", file=sys.stderr, flush=True)
def stop(signum, frame):
    (home / (kind + ".stopped")).touch()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
while True:
    temporary = home / (kind + ".heartbeat.tmp")
    temporary.write_text(str(time.monotonic_ns()))
    temporary.replace(home / (kind + ".heartbeat"))
    time.sleep(.05)
'''
    (package / "__main__.py").write_text(service)
    (home / "bin").mkdir()
    tunnel_script = home / "synthetic_tunnel.py"
    tunnel_script.write_text(service)
    executable(home / "bin/cloudflared", f'#!/bin/bash\nexec "{sys.executable}" "{tunnel_script}" tunnel\n')
    if tunnel_launch_fails:
        executable(home / "bin/cloudflared", "invalid executable format\n")
    fake_path = tmp_path / "commands"
    fake_path.mkdir()
    executable(fake_path / "curl", "#!/bin/bash\nexit 0\n")
    executable(fake_path / "lsof", "#!/bin/bash\nexit 1\n")
    (home / ".env.production").write_text("ASTRACORE_PORT=12345\nCLOUDFLARE_TUNNEL_TOKEN=synthetic-only\n")
    env = {key: value for key, value in os.environ.items() if not key.startswith(("ASTRACORE_", "EVE_"))}
    env.update(ASTRACORE_PROD_CHECKOUT=str(code), PATH=str(fake_path) + os.pathsep + env["PATH"])
    ready = home / "caller.ready"
    caller = subprocess.Popen(["bash", "-c", '"$1" start --prod && touch "$2" && sleep 120', "caller",
                               str(home / "astracore"), str(ready)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, start_new_session=True)
    children = []
    try:
        run = home / "data/run"
        app_record = json.loads(wait_for(lambda: (home / "app.json").read_text()
                                        if (home / "app.json").exists() else None))
        children.append(app_record["pid"])
        if tunnel_launch_fails:
            output = caller.communicate(timeout=30)[0].decode()
            assert caller.returncode != 0 and "The tunnel couldn't start" in output
            assert "synthetic-only" not in output
            assert (home / "app.stopped").exists()
            assert not any((run / name).exists() for name in ("app.pid", "tunnel.pid"))
            return
        wait_for(lambda: (run / "tunnel.pid").exists())
        records = {kind: json.loads(wait_for(lambda: (home / (kind + ".json")).read_text()
                                             if (home / (kind + ".json")).exists() else None))
                   for kind in ("app", "tunnel")}
        children = [record["pid"] for record in records.values()]
        wait_for(ready.exists)
        for kind, record in records.items():
            assert record["session"] == record["pid"] != os.getsid(caller.pid)
            assert int((run / (kind + ".pid")).read_text()) == record["pid"]
            assert record["cwd"] == str(code) and record["mode"] == "production"
            assert record["stdin"] == ""
        assert records["tunnel"]["token_in_environment"]
        os.killpg(caller.pid, signal.SIGTERM)
        output = caller.communicate(timeout=5)[0].decode()
        assert "synthetic-only" not in output
        for kind, record in records.items():
            heartbeat = home / (kind + ".heartbeat")
            previous = heartbeat.read_text()
            wait_for(lambda: heartbeat.read_text() != previous)
            os.kill(record["pid"], 0)
        for kind, filename in (("app", "app-production.out"), ("tunnel", "tunnel.out")):
            log = (home / "data/logs" / filename).read_text()
            assert kind + " synthetic stdout" in log and kind + " synthetic stderr" in log
            assert "synthetic-only" not in log
        command = subprocess.run(["ps", "-p", str(records["tunnel"]["pid"]), "-o", "command="],
                                 capture_output=True, text=True, check=True).stdout
        assert "synthetic-only" not in command
        # Verify the actual stop path sends TERM to the stored service PIDs.
        stopped = subprocess.run([str(home / "astracore"), "stop"], env=env, capture_output=True,
                                 text=True, timeout=30)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        assert all((home / (kind + ".stopped")).exists() for kind in ("app", "tunnel"))
        assert not any((run / name).exists() for name in ("app.pid", "tunnel.pid", "mode"))
    finally:
        if caller.poll() is None:
            os.killpg(caller.pid, signal.SIGKILL)
            caller.wait(timeout=5)
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
