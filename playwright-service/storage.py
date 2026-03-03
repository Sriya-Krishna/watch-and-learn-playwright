"""
Storage layer: SQLite for metadata, file system for script versions.

Script directory layout:
  scripts/{scriptId}/
    script.py          # current version
    script_v1.py       # original
    script_v2.py       # first heal
    metadata.json      # quick-access metadata
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone

from config import SCRIPT_STORAGE_PATH, DB_PATH

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scripts (
            script_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            intent_json TEXT NOT NULL,
            extract_schema_json TEXT,
            config_json TEXT,
            recording_json TEXT,
            current_version INTEGER DEFAULT 1,
            status TEXT DEFAULT 'ready',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id TEXT NOT NULL REFERENCES scripts(script_id),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            success INTEGER,
            script_version INTEGER,
            duration_seconds REAL,
            items_extracted INTEGER,
            error_message TEXT,
            healed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS heals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id TEXT NOT NULL REFERENCES scripts(script_id),
            version_before INTEGER,
            version_after INTEGER,
            error_trigger TEXT,
            changes_summary TEXT,
            success INTEGER,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    os.makedirs(SCRIPT_STORAGE_PATH, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _script_dir(script_id: str) -> str:
    return os.path.join(SCRIPT_STORAGE_PATH, script_id)


# ── Script CRUD ──────────────────────────────────────────────


def create_script(script_id: str, task_id: str, intent: dict,
                  extract_schema: dict | None, config: dict | None,
                  recording: list, code: str):
    """Create a new script: insert DB row + write v1 + current to disk."""
    now = _now()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO scripts
           (script_id, task_id, intent_json, extract_schema_json, config_json,
            recording_json, current_version, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, 'ready', ?, ?)""",
        (script_id, task_id, json.dumps(intent),
         json.dumps(extract_schema) if extract_schema else None,
         json.dumps(config) if config else None,
         json.dumps(recording), now, now)
    )
    conn.commit()

    # Write to disk
    d = _script_dir(script_id)
    os.makedirs(d, exist_ok=True)
    for name in ("script.py", "script_v1.py"):
        with open(os.path.join(d, name), "w") as f:
            f.write(code)
    with open(os.path.join(d, "metadata.json"), "w") as f:
        json.dump({"scriptId": script_id, "taskId": task_id, "currentVersion": 1}, f)


def get_script(script_id: str) -> dict | None:
    """Get script metadata from DB."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM scripts WHERE script_id = ?", (script_id,)).fetchone()
    if not row:
        return None
    return dict(row)


def get_script_code(script_id: str) -> str | None:
    """Read the current script.py from disk."""
    path = os.path.join(_script_dir(script_id), "script.py")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def get_script_context(script_id: str) -> dict | None:
    """Load intent + extract_schema for heal context."""
    meta = get_script(script_id)
    if not meta:
        return None
    return {
        "intent": json.loads(meta["intent_json"]),
        "extract_schema": json.loads(meta["extract_schema_json"]) if meta["extract_schema_json"] else None,
        "recording": json.loads(meta["recording_json"]) if meta["recording_json"] else None,
    }


def save_new_version(script_id: str, code: str, version: int):
    """Write script_v{N}.py + overwrite script.py, update DB version."""
    d = _script_dir(script_id)
    with open(os.path.join(d, f"script_v{version}.py"), "w") as f:
        f.write(code)
    with open(os.path.join(d, "script.py"), "w") as f:
        f.write(code)

    # Update metadata.json
    meta_path = os.path.join(d, "metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        meta["currentVersion"] = version
        with open(meta_path, "w") as f:
            json.dump(meta, f)

    conn = _get_conn()
    conn.execute(
        "UPDATE scripts SET current_version = ?, updated_at = ? WHERE script_id = ?",
        (version, _now(), script_id)
    )
    conn.commit()


def update_script_status(script_id: str, status: str):
    """Update script status (ready, healing, failed)."""
    conn = _get_conn()
    conn.execute(
        "UPDATE scripts SET status = ?, updated_at = ? WHERE script_id = ?",
        (status, _now(), script_id)
    )
    conn.commit()


def delete_script(script_id: str):
    """Delete script from DB and remove directory from disk."""
    conn = _get_conn()
    conn.execute("DELETE FROM heals WHERE script_id = ?", (script_id,))
    conn.execute("DELETE FROM executions WHERE script_id = ?", (script_id,))
    conn.execute("DELETE FROM scripts WHERE script_id = ?", (script_id,))
    conn.commit()

    d = _script_dir(script_id)
    if os.path.exists(d):
        shutil.rmtree(d)


def list_scripts() -> list[dict]:
    """Return summary of all scripts."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT script_id, task_id, status, current_version, created_at, updated_at FROM scripts ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Execution Logging ────────────────────────────────────────


def log_execution(script_id: str, version: int, success: bool,
                  duration: float, items: int | None, error: str | None,
                  healed: bool = False):
    """Log an execution attempt."""
    now = _now()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO executions
           (script_id, started_at, finished_at, success, script_version,
            duration_seconds, items_extracted, error_message, healed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (script_id, now, now, 1 if success else 0, version,
         duration, items, error, 1 if healed else 0)
    )
    conn.commit()


# ── Heal Logging ─────────────────────────────────────────────


def log_heal(script_id: str, v_before: int, v_after: int,
             error: str, changes: str, success: bool):
    """Log a heal attempt."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO heals
           (script_id, version_before, version_after, error_trigger,
            changes_summary, success, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (script_id, v_before, v_after, error, changes, 1 if success else 0, _now())
    )
    conn.commit()


# ── History & Stats ──────────────────────────────────────────


def get_script_history(script_id: str) -> dict:
    """Get execution and heal history for a script."""
    conn = _get_conn()
    executions = conn.execute(
        "SELECT * FROM executions WHERE script_id = ? ORDER BY id DESC", (script_id,)
    ).fetchall()
    heals = conn.execute(
        "SELECT * FROM heals WHERE script_id = ? ORDER BY id DESC", (script_id,)
    ).fetchall()
    return {
        "executions": [dict(r) for r in executions],
        "heals": [dict(r) for r in heals],
    }


def get_script_stats(script_id: str) -> dict:
    """Get success rate and counts for a script."""
    conn = _get_conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM executions WHERE script_id = ?", (script_id,)
    ).fetchone()[0]
    successes = conn.execute(
        "SELECT COUNT(*) FROM executions WHERE script_id = ? AND success = 1", (script_id,)
    ).fetchone()[0]
    total_heals = conn.execute(
        "SELECT COUNT(*) FROM heals WHERE script_id = ?", (script_id,)
    ).fetchone()[0]
    return {
        "total_executions": total,
        "success_rate": round(successes / total, 2) if total > 0 else None,
        "total_heals": total_heals,
    }
