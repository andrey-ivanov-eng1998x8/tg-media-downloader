import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any


class Queue:
    """Job store backed by SQLite with minimal state transitions."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # WAL mode is mandatory here, otherwise concurrent reads from prometheus lock writes
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    file_unique_id TEXT,
                    media_type TEXT NOT NULL,
                    file_name TEXT,
                    file_size INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(channel_id, message_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_file_uniq ON download_jobs(file_unique_id)"
            )

    def reset_stuck_jobs(self, lease_seconds: int = 600) -> int:
        cutoff = time.time() - lease_seconds
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE download_jobs
                SET status = 'pending', updated_at = ?
                WHERE status = 'downloading' AND updated_at < ?
                """,
                (time.time(), cutoff),
            )
            return cur.rowcount

    def is_known_file(self, file_unique_id: str) -> bool:
        if not file_unique_id:
            return False
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM download_jobs WHERE file_unique_id = ? AND status = 'done' LIMIT 1",
                (file_unique_id,),
            )
            return cur.fetchone() is not None

    def enqueue(
        self,
        channel_id: int,
        message_id: int,
        media_type: str,
        file_unique_id: Optional[str] = None,
        file_name: Optional[str] = None,
        file_size: int = 0,
    ) -> bool:
        now = time.time()
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO download_jobs (
                        channel_id, message_id, file_unique_id, media_type,
                        file_name, file_size, status, attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (
                        channel_id,
                        message_id,
                        file_unique_id,
                        media_type,
                        file_name,
                        file_size,
                        now,
                        now,
                    ),
                )
                return True
        except sqlite3.IntegrityError:
            # print(f"duplicate skip: {channel_id}/{message_id}")
            return False

    def fetch_next(self) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM download_jobs
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return None

            job_id = row["id"]
            now = time.time()
            cursor.execute(
                """
                UPDATE download_jobs
                SET status = 'downloading', updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, job_id),
            )
            if cursor.rowcount == 0:
                return None

            return dict(row)

    def mark_done(self, job_id: int):
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE download_jobs
                SET status = 'done', updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )

    def mark_failed(self, job_id: int, error: str, max_retries: int = 3):
        now = time.time()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT attempts FROM download_jobs WHERE id = ?", (job_id,)
            )
            row = cursor.fetchone()
            attempts = (row["attempts"] if row else 0) + 1

            # FIXME: backoff delay before re-queueing instead of immediate pending
            new_status = "pending" if attempts < max_retries else "failed"
            cursor.execute(
                """
                UPDATE download_jobs
                SET status = ?, attempts = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, attempts, str(error)[:500], now, job_id),
            )

    def count_by_status(self) -> Dict[str, int]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status, COUNT(*) as cnt
                FROM download_jobs
                GROUP BY status
                """
            )
            counts = {"pending": 0, "downloading": 0, "done": 0, "failed": 0}
            for row in cursor.fetchall():
                counts[row["status"]] = row["cnt"]
            return counts
