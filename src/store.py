"""
SQLite 儲存層 — 重點在「保留每次抓取的版本」。

為什麼要自己存版本？
--------------------
ALFRED 有官方 vintage，但：
  1. 不是每個序列都有完整 vintage 歷史
  2. JOLTS、Claims 這類序列的 vintage 查詢較慢
所以每次執行都把當下抓到的值存一份快照。從第二次執行開始，
就算 ALFRED 不可用，也能靠本地快照比對出「這次跟上次差多少」。

資料表
------
observations : 最新值（每個 series_id + date 只有一列，會被覆寫）
snapshots    : 每次執行的完整快照（append-only，永不覆寫）
runs         : 每次執行的中繼資料
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import clock

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    series_id TEXT NOT NULL,
    obs_date  TEXT NOT NULL,
    value     REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (series_id, obs_date)
);

CREATE TABLE IF NOT EXISTS snapshots (
    run_id    INTEGER NOT NULL,
    series_id TEXT NOT NULL,
    obs_date  TEXT NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (run_id, series_id, obs_date)
);

CREATE INDEX IF NOT EXISTS idx_snap_series ON snapshots(series_id, obs_date);

CREATE TABLE IF NOT EXISTS runs (
    run_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at   TEXT NOT NULL,
    note     TEXT,
    failed   TEXT
);
"""


class Store:
    def __init__(self, path: str | Path = "data/labor.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------
    def start_run(self, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (run_at, note) VALUES (?, ?)",
            (clock.iso(), note),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, failed: list) -> None:
        self.conn.execute(
            "UPDATE runs SET failed = ? WHERE run_id = ?",
            (json.dumps(failed, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    def write(self, run_id: int, series_id: str, rows: list[dict]) -> None:
        """同時寫入最新值與本次快照。"""
        now = clock.iso()
        self.conn.executemany(
            "INSERT INTO observations (series_id, obs_date, value, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(series_id, obs_date) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            [(series_id, r["date"], r["value"], now) for r in rows],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO snapshots (run_id, series_id, obs_date, value) "
            "VALUES (?, ?, ?, ?)",
            [(run_id, series_id, r["date"], r["value"]) for r in rows],
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    def series(self, series_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT obs_date, value FROM observations WHERE series_id = ? ORDER BY obs_date",
            (series_id,),
        ).fetchall()
        return [{"date": r["obs_date"], "value": r["value"]} for r in rows]

    def previous_snapshot(self, series_id: str, before_run: int) -> dict[str, float]:
        """取得上一次執行時，這個序列的值。用來比對修正。"""
        row = self.conn.execute(
            "SELECT MAX(run_id) AS rid FROM snapshots WHERE series_id = ? AND run_id < ?",
            (series_id, before_run),
        ).fetchone()
        if not row or row["rid"] is None:
            return {}
        rows = self.conn.execute(
            "SELECT obs_date, value FROM snapshots WHERE run_id = ? AND series_id = ?",
            (row["rid"], series_id),
        ).fetchall()
        return {r["obs_date"]: r["value"] for r in rows}

    def close(self) -> None:
        self.conn.close()
