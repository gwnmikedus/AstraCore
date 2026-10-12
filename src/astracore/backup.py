"""Manual encrypted SQLite snapshots; no uploads, secret discovery or live restores."""
from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from cryptography.fernet import Fernet, InvalidToken

MAGIC = b"ASTRACORE-BACKUP-V1\n"


def _write_new(path: Path, data: bytes) -> None:
    """Refuse existing files and symlinks; create private files from the first byte."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink()
        raise


def _cipher(key_file: Path) -> Fernet:
    if key_file.stat().st_mode & 0o077:
        raise ValueError("Backup key file must be private (chmod 600).")
    try:
        return Fernet(key_file.read_bytes().strip())
    except (ValueError, TypeError):
        raise ValueError("Invalid backup key file.") from None


def _validate(path: Path) -> None:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed.")


def generate_key(output: Path) -> None:
    _write_new(output, Fernet.generate_key() + b"\n")


def export_database(source: Path, output: Path, key_file: Path) -> None:
    cipher = _cipher(key_file)
    if not source.is_file():
        raise ValueError("Source database does not exist.")
    # SQLite's backup API includes committed WAL data without changing the source.
    with tempfile.TemporaryDirectory(prefix="astracore-backup-") as folder:
        snapshot = Path(folder) / "snapshot.sqlite3"
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
        snapshot.chmod(0o600)
        _validate(snapshot)
        _write_new(output, MAGIC + cipher.encrypt(snapshot.read_bytes()))


def restore_database(source: Path, output: Path, key_file: Path) -> None:
    # An old WAL can override the restored database even when its main file is absent.
    for suffix in ("", "-wal", "-shm", "-journal"):
        destination = Path(str(output) + suffix)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Restore destination or SQLite sidecar already exists.")
    cipher = _cipher(key_file)
    artifact = source.read_bytes()
    if not artifact.startswith(MAGIC):
        raise ValueError("Unsupported backup format.")
    try:
        plain = cipher.decrypt(artifact[len(MAGIC):])
    except InvalidToken:
        raise ValueError("Backup authentication failed: wrong key or damaged artifact.") from None
    if not plain.startswith(b"SQLite format 3\x00"):
        raise ValueError("Backup does not contain a SQLite database.")
    with tempfile.TemporaryDirectory(prefix="astracore-restore-") as folder:
        candidate = Path(folder) / "candidate.sqlite3"
        _write_new(candidate, plain)
        _validate(candidate)
        _write_new(output, plain)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen", help="Create a separate backup encryption key")
    keygen.add_argument("--output", type=Path, required=True)
    for name in ("export", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            generate_key(args.output)
        elif args.command == "export":
            export_database(args.source, args.output, args.key_file)
        else:
            restore_database(args.source, args.output, args.key_file)
    except (OSError, ValueError, sqlite3.Error) as error:
        # Never include SQLite errors or file contents, which may contain private data.
        if isinstance(error, FileExistsError):
            message = "Destination already exists; nothing overwritten."
        elif isinstance(error, ValueError):
            message = str(error)
        else:
            message = "Backup operation failed; check paths, permissions and database integrity."
        print(message)
        return 1
    print(f"{args.command.capitalize()} complete: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
