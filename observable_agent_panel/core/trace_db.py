"""
Persistent trace logger for Observable Agent Control Panel.

Every agent run writes a complete structured record to SQLite so runs
can be queried, filtered, and analyzed after the process ends.
This is the foundation for OctaClaw-style agent observability.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(ROOT_DIR, "data", "traces.db")


class TraceDB:
    """
    Single-process SQLite trace store.
    Lifecycle: start_trace() → update_* → finalize_trace()
    """

    def __init__(self, db_path: str = DB_PATH):
        # Ensure directory exists for persistent files
        dir_name = os.path.dirname(db_path)
        if dir_name:  # skip for ":memory:" or bare filenames
            os.makedirs(dir_name, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self.current_run_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _init_db(self) -> None:
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    run_id            TEXT PRIMARY KEY,
                    timestamp         TEXT NOT NULL,
                    query             TEXT NOT NULL,
                    similarity_score  REAL,
                    routing_decision  TEXT,
                    hops              TEXT DEFAULT '[]',
                    final_answer      TEXT,
                    outcome           TEXT,
                    memory_facts_used TEXT DEFAULT '[]',
                    explanation       TEXT,
                    hop_limit_hit     INTEGER DEFAULT 0
                )
            """)

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------
    def start_trace(self, query: str) -> str:
        self.current_run_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO traces (run_id, timestamp, query) VALUES (?, ?, ?)",
                (self.current_run_id, datetime.utcnow().isoformat(), query),
            )
        return self.current_run_id

    def update_triage(self, score: float, decision: str) -> None:
        if not self.current_run_id:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE traces SET similarity_score=?, routing_decision=? WHERE run_id=?",
                (score, decision, self.current_run_id),
            )

    def log_hop(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result_status: str,
        latency_ms: Optional[float] = None,
    ) -> None:
        if not self.current_run_id:
            return
        with self.conn:
            row = self.conn.execute(
                "SELECT hops FROM traces WHERE run_id=?", (self.current_run_id,)
            ).fetchone()
            hops = json.loads(row["hops"]) if row else []
            hops.append(
                {
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": result_status,
                    "latency_ms": latency_ms,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            self.conn.execute(
                "UPDATE traces SET hops=? WHERE run_id=?",
                (json.dumps(hops), self.current_run_id),
            )

    def set_memory_facts(self, facts: List[Any]) -> None:
        if not self.current_run_id:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE traces SET memory_facts_used=? WHERE run_id=?",
                (json.dumps(facts), self.current_run_id),
            )

    def finalize_trace(
        self,
        final_answer: str,
        hop_limit_hit: bool = False,
        explanation: Optional[str] = None,
    ) -> None:
        if not self.current_run_id:
            return
        with self.conn:
            self.conn.execute(
                """UPDATE traces
                   SET final_answer=?, hop_limit_hit=?, explanation=?
                   WHERE run_id=?""",
                (
                    final_answer,
                    1 if hop_limit_hit else 0,
                    explanation,
                    self.current_run_id,
                ),
            )

    def set_outcome(self, outcome: str) -> None:
        """Called after user rates the answer (y/n)."""
        if not self.current_run_id:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE traces SET outcome=? WHERE run_id=?",
                (outcome, self.current_run_id),
            )

    def set_explanation(self, text: str) -> None:
        if not self.current_run_id:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE traces SET explanation=? WHERE run_id=?",
                (text, self.current_run_id),
            )

    # ------------------------------------------------------------------
    # Read path — used by analysis commands
    # ------------------------------------------------------------------
    def get_recent_traces(self, n: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM traces ORDER BY timestamp DESC, rowid DESC LIMIT ?", (n,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_trace(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM traces WHERE run_id=?", (run_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def search_traces(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search historical logs for specific error patterns or queries."""
        # Split query into keywords for a slightly smarter search
        keywords = query.split()
        conditions = []
        params = []
        for kw in keywords:
            conditions.append("(query LIKE ? OR final_answer LIKE ? OR explanation LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT run_id, timestamp, query, final_answer, outcome, explanation
            FROM traces 
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["hops"] = json.loads(d.get("hops") or "[]")
        d["memory_facts_used"] = json.loads(d.get("memory_facts_used") or "[]")
        return d


# Singleton used by orchestrator and CLI
trace_db = TraceDB()
