"""Start a managed service outside the caller's terminal session (stdlib only)."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--pid", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a service command is required")
    with open(args.log, "ab", buffering=0) as log:
        child = subprocess.Popen(command, cwd=args.cwd, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT,
                                 close_fds=True, start_new_session=True)
    pid_file = Path(args.pid)
    temporary = pid_file.with_name(pid_file.name + ".tmp")
    try:
        temporary.write_text(str(child.pid) + "\n", encoding="ascii")
        temporary.chmod(0o600)
        os.replace(temporary, pid_file)
    except Exception:
        child.terminate()
        child.wait()
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
