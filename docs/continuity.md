# Backup and recovery preparation

Startup SQLite backups keep the newest 14 copies on the same machine. They help with a bad
change, but cannot recover a lost machine. The manual encrypted export below prepares a
copy for separate storage. It does not upload it or establish off-site protection by itself.

## Separate custody

Keep three things separately:

1. The encrypted database artifact, in an off-site destination selected by the maintainer.
2. Its dedicated backup key, in a separate protected location. Do not put it next to the
   artifact or reuse `ASTRACORE_TOKEN_KEY` as the backup key.
3. Recovery secrets, including the current and retained EVE token encryption keys and the
   EVE application configuration. The artifact contains the database, not `.env` files.
   Losing the token keys requires pilots to sign in again. Keep a recoverable record of
   the deployed commit and deployment configuration too.

The maintainer must choose the off-site provider, access holders, transfer schedule and
retention policy. Encrypted copies still contain private pilot data. Apply the same access
and deletion policy to them as to the original database; don't keep old copies indefinitely.

## Manual commands

Run from an isolated checkout with installed dependencies. Every path is explicit; these
commands do not discover production secrets, upload files, start the app or replace a
running database. Parent directories must already exist.

```sh
PYTHONPATH=src python -m astracore.backup keygen --output /secure-location/backup.key
PYTHONPATH=src python -m astracore.backup export \
  --source /chosen-data-directory/astracore.sqlite3 \
  --output /chosen-export-directory/astracore-backup.enc \
  --key-file /secure-location/backup.key
PYTHONPATH=src python -m astracore.backup restore \
  --source /chosen-export-directory/astracore-backup.enc \
  --output /isolated-recovery-directory/astracore.sqlite3 \
  --key-file /secure-location/backup.key
```

The export uses SQLite's backup API, including committed WAL changes, and validates the
snapshot with `PRAGMA quick_check`. Fernet authenticates and encrypts the snapshot. A restore
authenticates and validates the database before writing anything to the destination.
Key, artifact and restored database files are created with mode `600`; existing files and
symlinks are refused, including orphaned `-wal`, `-shm` and `-journal` files at a restore
destination. Use a new private recovery directory, never a directory used by a running app.
Temporary plaintext snapshots live in private temporary directories
and are removed on normal completion or handled failures. This is not secure erasure of
the underlying disk. Use encrypted local storage for temporary files too.

Encryption and decryption load the snapshot into memory. Allow several times the database
size in free memory; this helper is intended for the current small SQLite installation.
Do not use it for a large database without measuring resource needs first.

After export, copy only the encrypted artifact to the selected off-site destination using
its approved transfer tool. Record the time, deployed commit, artifact checksum and result
without recording pilot data or keys. Retrieve that remote copy for a restore drill; testing
only the local copy does not prove off-site recovery works.

## Fictional-data restore drill

The offline regression suite creates fictional SQLite data with committed WAL changes,
exports it, restores to a new path and checks the recovered rows. It also checks that a
wrong key, modified artifact, invalid database and existing destination fail safely:

```sh
PYTHONPATH=src python -m pytest -q tests/test_backup.py
```

For an operational drill, use the same three manual commands with a disposable fictional
database first. Then, after the maintainer authorizes access to a real backup, retrieve an
off-site artifact and restore into a private isolated directory. Verify database integrity,
the expected schema and aggregate row counts without printing pilot records. Do not start
background ESI work or point a running production app at the restored file during a drill.
Record who tested recovery, the artifact date, result and recovery time. Remove the
isolated restored data under the retention policy when finished.

## Remaining continuity work

Parent [#99](https://github.com/gwnmikedus/AstraCore/issues/99) remains open until off-site
storage, external `/healthz` monitoring, a pilot notice channel and a succession plan are
configured and tested. A successor needs the maintainer's authorization, hosting access,
EVE application custody and a clear privacy/deletion responsibility. The existing licence
is unchanged; this document grants no additional hosting or commercial rights.
