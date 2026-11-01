"""Maintenance entrypoint executed in the platform image, without API or schedulers."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from control.archives import create_snapshot, restore_snapshot, inspect_snapshot, encrypt_archive
from control.locking import FileLock
from control.vault import atomic_write
from backend.app.services.restore_fence import suspend_external_actions


def schemas() -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    backend = Path(__file__).resolve().parents[1] / "backend"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    return {revision.revision for revision in ScriptDirectory.from_config(cfg).walk_revisions()}


def main() -> None:
    data = Path(os.environ.get("APP_DATA_DIR", "/data"))
    operation, identity = sys.argv[1:3]
    if operation == "schemas":
        print(json.dumps(sorted(schemas())))
        return
    with FileLock(data / ".hcc-operation.lock"):
        if operation == "snapshot":
            sys.stdout.buffer.write(create_snapshot(data, identity))
        elif operation == "restore":
            with FileLock(data / ".server.lock", blocking=False):
                blob = sys.stdin.buffer.read(512 * 1024 * 1024 + 1)
                manifest = inspect_snapshot(blob)
                if (data / "hackathon.db").exists():
                    key = (Path(os.environ["APP_SECRETS_DIR"]) / "operator").read_text()
                    if not key:
                        raise ValueError("A recovery key is required for the safety copy")
                    safety = create_snapshot(data, identity)
                    atomic_write(data / "restore-safety" / f"before-{time.time_ns()}.hcc", encrypt_archive(safety, key))
                restore_snapshot(blob, data, schemas())
                suspend_external_actions(data, manifest["created_at"])
        elif operation == "transfer":
            with FileLock(data / ".server.lock", blocking=False):
                (data / ".transfer-pending").unlink(missing_ok=True)
        else:
            raise ValueError("Unsupported maintenance operation")


if __name__ == "__main__":
    main()
