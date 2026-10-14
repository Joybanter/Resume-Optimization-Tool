"""SQLite 历史记录存储（PRD 3.2.9）。

使用标准库 sqlite3，数据文件位于用户目录 ~/.resume_optimizer/history.db。
每次操作使用独立连接、用完即关，规避多线程（GUI 线程 / 优化工作线程）
交叉访问问题。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .. import config

#: JD 摘要长度（PRD 3.2.9：JD 文本前 200 字摘要）
_JD_SUMMARY_LEN = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    resume_path TEXT NOT NULL DEFAULT '',
    jd_title TEXT NOT NULL DEFAULT '',
    jd_summary TEXT NOT NULL DEFAULT '',
    jd_text TEXT NOT NULL DEFAULT '',
    rewrite_level TEXT NOT NULL DEFAULT 'moderate',
    model TEXT NOT NULL DEFAULT '',
    output_docx TEXT NOT NULL DEFAULT '',
    output_pdf TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC);
"""


class HistoryDB:
    """历史记录数据库访问层。"""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(db_path) if db_path else str(config.DB_FILE)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {key: row[key] for key in row.keys()}

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def add_record(
        self,
        resume_path: str,
        jd_title: str,
        jd_text: str,
        rewrite_level: str,
        model: str,
        output_docx: str = "",
        output_pdf: str = "",
        summary: str = "",
    ) -> int:
        """新增一条历史记录，返回记录 ID。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        jd_summary = (jd_text or "").strip().replace("\n", " ")[:_JD_SUMMARY_LEN]
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO history (
                    created_at, resume_path, jd_title, jd_summary, jd_text,
                    rewrite_level, model, output_docx, output_pdf, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    resume_path,
                    (jd_title or "").strip(),
                    jd_summary,
                    jd_text or "",
                    rewrite_level,
                    model,
                    output_docx,
                    output_pdf,
                    summary or "",
                ),
            )
            return int(cursor.lastrowid)

    def delete_record(self, record_id: int) -> dict | None:
        """删除一条记录，返回被删除的记录（供调用方决定是否删除文件）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM history WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM history WHERE id = ?", (record_id,))
            return self._row_to_dict(row)

    # ------------------------------------------------------------------
    # 读操作
    # ------------------------------------------------------------------

    def list_records(self, keyword: str | None = None, limit: int = 200) -> list[dict]:
        """按时间倒序列出记录；keyword 非空时按 JD 关键词模糊搜索（PRD 3.2.9）。"""
        with self._connect() as conn:
            if keyword:
                rows = conn.execute(
                    """
                    SELECT * FROM history
                    WHERE jd_summary LIKE ? OR jd_title LIKE ? OR summary LIKE ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM history ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_record(self, record_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM history WHERE id = ?", (record_id,)
            ).fetchone()
            return self._row_to_dict(row) if row is not None else None

    def close(self) -> None:
        """连接按次创建，无需显式关闭；保留方法以兼容调用方。"""
        return None
