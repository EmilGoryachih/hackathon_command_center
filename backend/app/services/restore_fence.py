"""Shared restore fence for the local hub and legacy backup API; no external calls."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

def suspend_external_actions(data: Path, snapshot_at: str, *, database: Path | None = None) -> None:
    """Snapshot state cannot prove delivery or provider usage after its timestamp."""
    with closing(sqlite3.connect(database or data / "hackathon.db")) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "advisor_jobs" in tables:
            db.execute("UPDATE advisor_jobs SET state='failed', error_code='RESTORED_INSTALLATION', lease_token=NULL, lease_until=NULL WHERE state IN ('queued','running','retry','waiting')")
        if "telegram_deliveries" in tables:
            db.execute("UPDATE telegram_deliveries SET state='uncertain', error_code='RESTORED_INSTALLATION', lease_token=NULL, lease_until=NULL WHERE state IN ('pending','sending')")
        if "ai_settings" in tables:
            db.execute("UPDATE ai_settings SET enabled=0, auto_enabled=0")
        if "situation_settings" in tables:
            db.execute("UPDATE situation_settings SET enabled=0, initialized_at=NULL, checked_at=NULL")
        if "sessions" in tables:
            db.execute("DELETE FROM sessions")
        cutoff = datetime.fromisoformat(snapshot_at).astimezone(timezone.utc).replace(tzinfo=None)
        if "task_timers" in tables:
            for timer_id, accumulated, started in db.execute("SELECT id,accumulated_seconds,last_started_at FROM task_timers WHERE state='running'").fetchall():
                start = datetime.fromisoformat(started).replace(tzinfo=None) if started else cutoff
                elapsed = max(0, int((cutoff - start).total_seconds()))
                db.execute("UPDATE task_timers SET state='paused', accumulated_seconds=?, last_started_at=NULL WHERE id=?", (accumulated + elapsed, timer_id))
        if "timer_segments" in tables:
            db.execute("UPDATE timer_segments SET ended_at=? WHERE ended_at IS NULL", (cutoff.isoformat(sep=" "),))
        db.commit()
    # Managed installations require explicit activation in the local panel.
    (data / ".transfer-pending").write_text("External actions suspended after restore\n", encoding="utf-8")

