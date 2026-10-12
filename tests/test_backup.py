import sqlite3

import pytest
from cryptography.fernet import Fernet

from astracore import backup


@pytest.fixture
def snapshot(tmp_path):
    source, key, artifact = [tmp_path / name for name in ("source.sqlite3", "key", "backup.enc")]
    backup.generate_key(key)
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE fictional (name TEXT)")
    connection.execute("INSERT INTO fictional VALUES ('Synthetic pilot')")
    connection.commit()
    # Keep the connection open so committed rows remain in WAL during the export.
    yield source, key, artifact
    connection.close()


def test_round_trip_includes_committed_wal_and_keeps_keys_separate(snapshot, tmp_path):
    source, key, artifact = snapshot
    backup.export_database(source, artifact, key)
    assert b"Synthetic pilot" not in artifact.read_bytes()
    assert key.read_bytes().strip() not in artifact.read_bytes()
    restored = tmp_path / "restored.sqlite3"
    backup.restore_database(artifact, restored, key)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT name FROM fictional").fetchall() == [("Synthetic pilot",)]
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (key, artifact, restored))
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT name FROM fictional").fetchall() == [("Synthetic pilot",)]


def test_wrong_key_and_tampering_never_create_a_restore(snapshot, tmp_path):
    source, key, artifact = snapshot
    backup.export_database(source, artifact, key)
    wrong = tmp_path / "wrong-key"
    backup.generate_key(wrong)
    restored = tmp_path / "restored.sqlite3"
    with pytest.raises(ValueError, match="authentication failed"):
        backup.restore_database(artifact, restored, wrong)
    raw = bytearray(artifact.read_bytes())
    raw[-12] = ord("A") if raw[-12] != ord("A") else ord("B")
    artifact.write_bytes(raw)
    with pytest.raises(ValueError, match="authentication failed"):
        backup.restore_database(artifact, restored, key)
    assert not restored.exists()


def test_existing_files_and_symlinks_are_never_overwritten(snapshot, tmp_path):
    source, key, artifact = snapshot
    backup.export_database(source, artifact, key)
    for operation in (lambda: backup.generate_key(key),
                      lambda: backup.export_database(source, artifact, key),
                      lambda: backup.restore_database(artifact, source, key)):
        with pytest.raises(FileExistsError):
            operation()
    link = tmp_path / "destination"
    link.symlink_to(source)
    with pytest.raises(FileExistsError):
        backup.restore_database(artifact, link, key)
    assert link.is_symlink()


def test_invalid_database_and_public_key_file_are_rejected(snapshot, tmp_path):
    source, key, artifact = snapshot
    source = tmp_path / "not-a-database"
    source.write_bytes(b"fictional invalid database")
    with pytest.raises(sqlite3.DatabaseError):
        backup.export_database(source, artifact, key)
    artifact.write_bytes(backup.MAGIC + Fernet(key.read_bytes().strip()).encrypt(b"not SQLite"))
    output = tmp_path / "restore.sqlite3"
    with pytest.raises(ValueError, match="SQLite database"):
        backup.restore_database(artifact, output, key)
    key.chmod(0o644)
    with pytest.raises(ValueError, match="must be private"):
        backup.restore_database(artifact, output, key)
    assert not output.exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("symlink", [False, True])
def test_restore_refuses_orphaned_sidecars_and_broken_symlinks(snapshot, tmp_path, suffix, symlink):
    source, key, artifact = snapshot
    backup.export_database(source, artifact, key)
    output = tmp_path / "restored.sqlite3"
    sidecar = tmp_path / (output.name + suffix)
    if symlink:
        sidecar.symlink_to(tmp_path / "missing-target")
    else:
        sidecar.write_bytes(b"unrelated old SQLite sidecar")
    with pytest.raises(FileExistsError):
        backup.restore_database(artifact, output, key)
    assert not output.exists()
    assert sidecar.is_symlink() if symlink else sidecar.read_bytes() == b"unrelated old SQLite sidecar"


def test_cli_fails_without_creating_missing_source_or_exposing_contents(tmp_path, capsys):
    key, output, missing = [tmp_path / name for name in ("key", "backup.enc", "missing.sqlite3")]
    assert backup.main(["keygen", "--output", str(key)]) == 0
    assert backup.main(["export", "--source", str(missing), "--output", str(output), "--key-file", str(key)]) == 1
    assert not missing.exists() and not output.exists()
    key.write_bytes(b"PRIVATE INVALID KEY CONTENT")
    assert backup.main(["export", "--source", str(missing), "--output", str(output), "--key-file", str(key)]) == 1
    assert "PRIVATE INVALID KEY CONTENT" not in capsys.readouterr().out
